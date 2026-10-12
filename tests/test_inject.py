"""Which notes an edit is charged for: split parts go to the files they name, a long note costs its map or a cut, each goes out once.

Author: Marco Cassar (@Ocramaru)
"""

import uuid
from pathlib import Path

import pytest
from conftest import git

from agentkit import doctor, inject, notes, profile, tree

HEAD = "---\nname: context\nkind: context\n---\n\n"
SECTIONS = """# r

The preamble, which stays in the index.

## Reviews

REVIEWS-RULE the ledger is append-only

## Hooks

HOOKS-RULE hooks stay thin bash

## Shared

SHARED-RULE dependencies point one way
"""


def rules(text: str) -> set[str]:
  return {word for word in text.split() if word.endswith("-RULE")}


def send(path: Path, session: str) -> str:
  """What an edit to `path` is sent in `session`, marked as sent."""
  text, keys, _ = inject.payload(path, session)
  inject.mark(session, keys)
  return text


def configure(tmp_path: Path, monkeypatch, config: str) -> None:
  """A profile holding only this config.toml, layered over the shipped one."""
  (tmp_path / "profile").mkdir(exist_ok=True)
  (tmp_path / "profile" / "config.toml").write_text(config)
  monkeypatch.setenv("AGENTS_PROFILE", str(tmp_path / "profile"))
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")   # never this machine's


@pytest.fixture
def site(tmp_path):
  """A repo whose root context.md has three sections, and files for a part to name."""
  git(tmp_path)
  (tmp_path / ".agents").mkdir()
  (tmp_path / ".agents" / "context.md").write_text(HEAD + SECTIONS)
  for name in ("review.py", "hook.sh"): (tmp_path / name).write_text("x\n")
  return tmp_path


def test_each_part_standard_and_section_goes_out_once_per_session(site):
  """A part naming `applies` is sent for those files and the rest are named; nothing counts as sent until it is marked."""
  reviews, hooks, _ = notes.split(site / ".agents" / "context.md")
  body, mention, _ = tree.payload(site / "review.py")
  assert "The preamble" in body and rules(body) == set()      # the index, carrying the map
  assert [entry.split("/")[-1].split(" ")[0] for entry in mention] == ["01-reviews.md", "02-hooks.md", "03-shared.md"]
  for part, globs in ((reviews, "review.py, reviews.py"), (hooks, "*.sh")): part.write_text(part.read_text().replace("kind: context", f"kind: context\napplies: {globs}", 1))

  session = f"once-{uuid.uuid4().hex}"   # stamps outlive a run in /tmp, and tmp dir names repeat
  first, keys, _ = inject.payload(site / "review.py", session)
  assert rules(first) == {"REVIEWS-RULE"} and "--- python" in first and "--- python" in inject.payload(site / "review.py", session)[0]   # not marked, so offered again
  inject.mark(session, keys)
  assert inject.payload(site / "review.py", session)[0] == ""   # nothing new at all, not just no rules
  assert rules(send(site / "hook.sh", session)) == {"HOOKS-RULE"}   # only the part not already sent

  for name in ("learned.md", "todo.md"): (site / ".agents" / name).write_text("# x\n")
  learned = send(site / ".agents" / "learned.md", session)
  assert "--- agent-notes" in learned and "move finished items" not in learned
  todo = send(site / ".agents" / "todo.md", session)
  assert "move finished items to `todo.archive.md`" in todo and "Four files, each answering" not in todo   # a section scoped to one file, its standard already out
  assert send(site / ".agents" / "todo.md", session) == ""


def test_a_config_only_agents_does_not_demote_the_nearest_notes(site, tmp_path, monkeypatch):
  """`nearest` is the closest directory with notes; an `.agents` holding only agents.toml is not one."""
  configure(tmp_path, monkeypatch, '[inject]\nnearest = "full"\nancestors = "context"\n')
  (site / ".agents" / "learned.md").write_text(HEAD.replace("context", "learned") + "NEAR-FINDING\n")
  (agents_dir := site / "package" / ".agents").mkdir(parents=True)
  (agents_dir / "agents.toml").write_text('[applies]\nvoice = ["x.json"]\n')
  (module := agents_dir.parent / "mod.py").write_text("x\n")
  assert len(tree.chain(module)) == 2 and "NEAR-FINDING" in tree.payload(module)[0]   # the config-only directory is in the chain, not nearest


def test_a_long_note_costs_its_map_or_a_cut_and_is_never_a_failing_check(site, tmp_path, monkeypatch):
  """Past `map_over` a sectioned note sends its head and map; over `budget` it is cut at a line or named; doctor only reports it."""
  context_file = site / ".agents" / "context.md"
  configure(tmp_path, monkeypatch, "[inject]\nmap_over = 2048\n")
  assert "SHARED-RULE" in tree.payload(site / "review.py")[0]   # short: whole

  context_file.write_text(HEAD + "# r\n\nPREAMBLE here.\n\n" + "".join(f"## S{index}\n\nBODY{index} {'x' * 900}\n\n" for index in range(5)))
  body = tree.payload(site / "review.py")[0]
  assert "PREAMBLE here." in body and "BODY0" not in body and "bytes in full" in body   # the head, not the sections
  (ok, what, _), = doctor.context_size(context_file.parent, site)
  assert ok and "sends its map," in what

  configure(tmp_path, monkeypatch, "[inject]\nbudget = 2000\nmap_over = 100\n")   # no sections, so whole despite map_over
  context_file.write_text(HEAD + "".join(f"RULE-{index} something true about this directory\n" for index in range(80)))
  body, mention, _ = tree.payload(site / "review.py")
  assert "truncated at the budget" in body and "RULE-79 " not in body and not any("over budget" in entry for entry in mention)
  assert body.split("\n\n[truncated")[0].endswith("directory")   # never mid-line

  configure(tmp_path, monkeypatch, "[inject]\nbudget = 100\n")
  context_file.write_text("---\nname: context\ndescription: huge\n---\n\n" + "x" * 3000)
  body, mention, _ = tree.payload(site / "review.py")
  assert body == "" and any("over budget" in entry and "huge" in entry for entry in mention)
