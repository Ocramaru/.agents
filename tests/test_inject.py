"""What an edit is actually charged for: which notes go out, which are only named, and once each.

A note is sent whole while it is short, as its section map once it is long, and part by part once it
is split: a part that names `applies` for those files, the rest advertised. Every route has been
wrong at least once: splitting a context.md silently took its rules out of every session, and
stamping rebuilt a part's name from the wrong parent so a part would have been re-sent every edit.

Author: Marco Cassar (@Ocramaru)
"""

import re
import uuid
from pathlib import Path

import pytest
from conftest import agent, git

from agentkit import doctor, inject, notes, profile, tree

SECTIONS = """# r

The preamble, which stays in the index.

## Reviews

REVIEW-RULE the ledger is append-only

## Hooks

HOOK-RULE hooks stay thin bash

## Shared

SHARED-RULE dependencies point one way
"""


def rules(text: str) -> set[str]:
  return {r for r in ("REVIEW-RULE", "HOOK-RULE", "SHARED-RULE") if r in text}


def applies(part: Path, globs: str) -> None:
  """Give a split part an applies line, the way a person would after splitting."""
  before = part.read_text()
  after = re.sub(r"^(kind: \w+)$", rf"\1\napplies: {globs}", before, count=1, flags=re.MULTILINE)
  assert after != before, f"no kind line to add applies after in {part.name}"   # else tests pass vacuously
  part.write_text(after)


@pytest.fixture
def site(tmp_path):
  """A repo whose root context.md has three sections, and files for a part to name."""
  git(tmp_path)
  a = tmp_path / ".agents"
  a.mkdir()
  (a / "context.md").write_text(f"---\nname: context\nkind: context\n---\n\n{SECTIONS}")
  for name in ("review.py", "hook.sh", "notes.txt"):
    (tmp_path / name).write_text("x\n")
  return tmp_path


def split(site: Path) -> dict[str, Path]:
  parts = notes.split(site / ".agents" / "context.md")
  return {p.stem.split("-", 1)[1]: p for p in parts}


def configure(tmp_path: Path, monkeypatch, config: str) -> None:
  """A profile holding only this config.toml, layered over the shipped one."""
  (mine := tmp_path / "profile").mkdir(exist_ok=True)
  (mine / "config.toml").write_text(config)
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")   # never this machine's


def big(n: int) -> str:
  return "x" * n


def test_a_split_context_sends_each_part_to_its_files_once_and_names_the_rest(site):
  """A part naming `applies` goes to those files once per session; every other part is named."""
  assert rules(tree.payload(site / "review.py")[0]) == {"REVIEW-RULE", "HOOK-RULE", "SHARED-RULE"}
  parts = split(site)
  assert "A part naming `applies` is sent for those files" in (site / ".agents" / "context.md").read_text()
  after, mention, _ = tree.payload(site / "review.py")
  assert "The preamble" in after and rules(after) == set()      # the index, carrying the map
  assert [m.split("/")[-1].split(" ")[0] for m in mention] == ["01-reviews.md", "02-hooks.md", "03-shared.md"]

  applies(parts["reviews"], "review.py, reviews.py")
  applies(parts["hooks"], "*.sh")
  body, mention, _ = tree.payload(site / "notes.txt")
  assert rules(body) == set() and len([m for m in mention if "03-shared" in m]) == 1

  session = f"split-{uuid.uuid4().hex}"   # stamps outlive a run in /tmp, and tmp dir names repeat

  def edit(name: str) -> set[str]:
    text, keys, _ = inject.payload(site / name, session)
    inject.mark(session, keys)
    return rules(text)

  assert edit("review.py") == {"REVIEW-RULE"}
  assert inject.payload(site / "review.py", session)[0] == ""   # nothing new at all, not just no rules
  assert edit("hook.sh") == {"HOOK-RULE"}           # only the part not already sent

  out = agent(["context", "review.py"], cwd=site).stdout
  assert "./context/01-reviews.md" in out and "REVIEW-RULE" in out and "03-shared.md" in out


def test_every_split_note_routes_its_parts_outermost_first(site):
  """A split learned.md is named unless `inject = "full"`, and a nested part lands after the root."""
  a = site / ".agents"
  (a / "learned.md").write_text("---\nname: learned\nkind: learned\n---\n\n# L\n\n## Traps\n\nTRAP-FINDING\n")
  traps, = notes.split(a / "learned.md")
  applies(traps, "review.py")
  body, mention, _ = tree.payload(site / "review.py")
  assert "TRAP-FINDING" not in body and any("learned/01-traps.md" in m for m in mention)

  (a / "agents.toml").write_text('inject = "full"\n')
  body, _, _ = tree.payload(site / "review.py")
  assert "TRAP-FINDING" in body and "./learned/01-traps.md" in body

  pkg = site / "pkg"
  (pkg / ".agents").mkdir(parents=True)
  (pkg / ".agents" / "context.md").write_text("---\nname: context\nkind: context\n---\n\n# p\n\n## Inner\n\nINNER-RULE\n")
  inner, = notes.split(pkg / ".agents" / "context.md")
  applies(inner, "*.py")
  (pkg / "mod.py").write_text("x\n")
  body, _, _ = tree.payload(pkg / "mod.py")
  assert body.index("# r") < body.index("INNER-RULE")


def test_a_standard_or_section_is_stamped_only_once_it_has_gone_out(repo):
  """Nothing is stamped until marked, and a section scoped to one file is stamped on its own."""
  session = f"stamp-{uuid.uuid4().hex}"   # stamps outlive a run in /tmp, and tmp dir names repeat
  first, keys, _ = inject.payload(repo / "mod.py", session)
  assert "--- python" in first
  assert "--- python" in inject.payload(repo / "mod.py", session)[0]      # not marked, so offered again
  inject.mark(session, keys)
  assert inject.payload(repo / "mod.py", session)[0] == ""

  agents = repo / ".agents"
  for name in ("learned.md", "todo.md"): (agents / name).write_text("# x\n")

  def edit(name: str) -> str:
    text, keys, _ = inject.payload(agents / name, session)
    inject.mark(session, keys)
    return text

  first = edit("learned.md")
  assert "--- agent-notes" in first and "move finished items" not in first
  second = edit("todo.md")
  assert "move finished items to `todo.archive.md`" in second
  assert "Four files, each answering" not in second               # the rest of it is not sent twice
  assert edit("todo.md") == ""


def test_a_config_only_agents_does_not_demote_the_nearest_notes(site, tmp_path, monkeypatch):
  """`nearest` is the closest directory with notes; an `.agents` holding only agents.toml is not one."""
  configure(tmp_path, monkeypatch, '[inject]\nnearest = "full"\nancestors = "context"\n')
  (site / ".agents" / "learned.md").write_text("---\nname: learned\nkind: learned\n---\n\n# L\n\nNEAR-FINDING\n")
  pkg = site / "pkg"
  (pkg / ".agents").mkdir(parents=True)
  (pkg / ".agents" / "agents.toml").write_text('[applies]\nvoice = ["x.json"]\n')
  (pkg / "mod.py").write_text("x\n")
  assert len(tree.chain(pkg / "mod.py")) == 2          # the config-only directory is in the chain
  assert "NEAR-FINDING" in tree.payload(pkg / "mod.py")[0]


def test_doctor_reports_what_a_context_sends_and_never_fails_on_it(site, monkeypatch):
  """A size is a reason to split, not a reason to stop writing, so it is never a failing check."""
  a = site / ".agents"
  (a / "context.md").write_text("---\nname: context\nkind: context\n---\n\n# r\n\n"
                                + "".join(f"## S{i}\n\n{big(1900)}\n\n" for i in range(5)))
  (ok, what, _), = doctor.context_size(a, site)
  assert ok and "sends its map," in what            # a long note costs its table, not its body

  notes.split(a / "context.md")
  (ok, what, _), = doctor.context_size(a, site)
  assert ok and "5 parts to read on demand" in what


def test_a_note_over_the_budget_is_cut_at_a_line_or_named_when_there_is_no_room(site, tmp_path, monkeypatch):
  """Over budget, a note is truncated on a newline while room is left, and named when none is."""
  ctx = site / ".agents" / "context.md"
  configure(tmp_path, monkeypatch, "[inject]\nbudget = 2000\nmap_over = 0\n")   # 0 keeps the body
  lines = "".join(f"RULE-{i} something true about this directory\n" for i in range(80))
  ctx.write_text(f"---\nname: context\nkind: context\n---\n\n{lines}")
  body, mention, _ = tree.payload(site / "review.py")
  assert "truncated at the budget" in body and "more characters in the file" in body
  assert not any("over budget" in m for m in mention)
  assert "RULE-0 " in body and "RULE-79 " not in body
  assert body.split("\n\n[truncated")[0].split("\n")[-1].endswith("directory")   # never mid-line

  configure(tmp_path, monkeypatch, "[inject]\nbudget = 100\n")
  ctx.write_text("---\nname: context\ndescription: huge\n---\n\n" + big(3000))
  body, mention, _ = tree.payload(site / "review.py")
  assert body == "" and any("over budget" in m and "huge" in m for m in mention)


def test_a_note_is_mapped_only_when_long_and_sectioned(site, tmp_path, monkeypatch):
  """Past `map_over` a sectioned note sends its head and map; short, unsectioned, or `map_over = 0` go whole."""
  ctx = site / ".agents" / "context.md"
  configure(tmp_path, monkeypatch, "[inject]\nmap_over = 2048\n")   # not this machine's
  assert "REVIEW-RULE" in tree.payload(site / "review.py")[0]   # short: whole

  ctx.write_text("---\nname: context\nkind: context\n---\n\n# r\n\nPREAMBLE here.\n\n"
                 + "".join(f"## S{i}\n\nBODY{i} {big(900)}\n\n" for i in range(5)))
  body, _, _ = tree.payload(site / "review.py")
  assert "PREAMBLE here." in body and "BODY0" not in body      # the head, not the sections
  assert "bytes in full" in body and "at those lines" in body and len(body) < 900

  configure(tmp_path, monkeypatch, "[inject]\nmap_over = 0\n")
  off = tree.payload(site / "review.py")[0]
  assert "BODY0" in off and "bytes in full" not in off         # 0 turns the map off entirely

  configure(tmp_path, monkeypatch, "[inject]\nmap_over = 100\n")
  ctx.write_text("---\nname: context\nkind: context\n---\n\n" + "plain prose. " * 50)
  body, _, _ = tree.payload(site / "review.py")
  assert "bytes in full" not in body and "plain prose." in body
