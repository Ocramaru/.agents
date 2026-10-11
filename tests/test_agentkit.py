"""Covers the parts that have already broken once, or fail silently when they break.

One test per behaviour, walking the steps that broke. Fixtures and tree builders are in conftest.py;
the CLI is exercised as a subprocess in test_cli.py.

Run with `env -u PYTHONPATH uv run pytest tests/`. Pytest is a dev dependency only, and nothing in
agentkit imports anything outside the standard library.

Author: Marco Cassar (@Ocramaru)
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from conftest import git, note, standard  # pytest puts tests/ on the path, and the builders live there

from agentkit import agents as ag
from agentkit import (backends, cli, command, doctor, hooks, inject, mapblock, notes, profile, review,
                      reviews, session, tree)
from agentkit.backends import Backend, Reply, _fill
from agentkit.cli import out, show
from agentkit.frontmatter import parse
from agentkit.session import Message, Session
from agentkit.standards import Library

CLEAN = {"kind": "findings", "state": "completed", "body": "looked", "data": {"findings": []}}


class Stub:
  """A backend giving the replies it was handed, then clean ones; it remembers what it was asked."""
  name, resumable, parallel, spec = "stub", False, 4, {}

  def __init__(self, *replies): self.replies, self.shown, self.asked = list(replies), [], []

  def model_for(self, role): return role

  def run(self, prompt, tier="text", session=None, effort=None):
    self.shown.append(prompt)
    self.asked.append((tier, effort))
    time.sleep(0.4 if "SLOW" in prompt else 0.0)
    r = self.replies.pop(0) if self.replies else CLEAN
    if isinstance(r, Exception): raise r
    return Reply(json.dumps(r))


def findings(*items) -> dict:
  return {"kind": "findings", "state": "completed", "body": "found", "data": {"findings": list(items)}}


def put(root: Path, *rels: str, text: str = "x = 1\n") -> list[Path]:
  """Files at `rels` under `root`, parents made, each holding `text`."""
  for rel in rels:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)
  return [root / rel for rel in rels]


def commit(d: Path):
  subprocess.run(["git", "add", "-f", "-A"], cwd=d, check=True)
  subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "c"], cwd=d, check=True)


# -- backends ---------------------------------------------------------------------------------
def test_a_backend_fills_its_argv_once_and_finds_its_reply_in_whatever_it_printed(monkeypatch):
  """A payload survives substitution verbatim, the reply is found around noise, and stdin is closed."""
  prompt = 'review a.replace("{session}", x) and {model}'
  out = _fill(["c", "-p", "{prompt}", "-m", "{model}", "-r", "{session}"],
              {"model": "haiku", "prompt": prompt, "session": "abc"})
  assert out[2] == prompt and out[4] == "haiku" and out[6] == "abc"
  assert _fill(["{other}"], {"model": "m"}) == ["{other}"]   # not ours to fill in
  codex = Backend("codex", {"kind": "cli", "format": "jsonl", "resume_argv": ["x"],
                            "session_key": "thread_id", "reply_key": "item.text"})
  stream = "\n".join(json.dumps(e) for e in [
    {"type": "thread.started", "thread_id": "t-1"}, {"type": "turn.started"},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}, {"type": "turn.completed"}])
  reply = codex._unwrap(stream, None)
  assert reply.text == "OK" and reply.session == "t-1"
  claude = Backend("claude", {"kind": "cli", "format": "json", "session_key": "session_id", "reply_key": "result"})
  reply = claude._unwrap('warning: something\n{"session_id": "s-1", "result": "done"}', None)
  assert reply.text == "done" and reply.session == "s-1"
  seen = []
  monkeypatch.setattr(backends.subprocess, "run",
                      lambda argv, **kw: seen.append((argv, kw)) or subprocess.CompletedProcess(argv, 0, '{"result": "ok"}', ""))
  b = Backend("claude", {"kind": "cli", "format": "json", "reply_key": "result", "argv": ["claude", "-p", "{prompt}"],
                         "effort_argv": ["--effort", "{effort}"], "models": {"text": "m"}})
  b.run("hi")
  b.run("hi", effort="low")
  assert all(kw.get("stdin") is subprocess.DEVNULL for _, kw in seen)
  assert "--effort" not in seen[0][0] and seen[1][0][-2:] == ["--effort", "low"]
  assert Backend("ollama", {"kind": "http", "url": "u"}).parallel == 1   # concurrent calls took it down
  assert Backend("x", {"kind": "http", "url": "u", "parallel": 3}).parallel == 3


def test_a_role_names_a_model_the_backend_declares(tmp_path, monkeypatch):
  """A role resolves exactly or not at all, and every reviewer's role is declared on every backend."""
  roled = Backend("o", {"kind": "http", "url": "u", "models": {"text": "t", "code-large": "cl"}})
  assert roled.model_for("code-large") == "cl" and roled.model_for("text") == "t"
  with pytest.raises(ValueError, match="no model for role 'code'; it has text, code-large"):   # exact, never a guess
    roled.model_for("code")
  folder = tmp_path / "reviewers"
  folder.mkdir()
  (folder / "named.md").write_text("---\nname: named\nmodel: code-large\n---\n")
  (folder / "unnamed.md").write_text("---\nname: unnamed\n---\n")
  assert {name: d.get("model") for name, d in ag.definitions(folder).items()} == {"named": "code-large", "unnamed": "text"}
  config = tmp_path / "config.toml"
  config.write_text('[review]\nmodel = "code"\n')
  monkeypatch.setattr(profile, "CONFIG", config)
  assert ag.definitions(folder)["unnamed"].get("model") == "code"          # the default is configuration, not code
  monkeypatch.undo()        # says nothing: a role, not a size
  every = {d.get("model") for d in ag.definitions().values()}
  for backend in backends.load_backends()[0].values():   # every reviewer runs on every configured backend
    assert every <= set(backend.spec["models"]), (backend.name, every - set(backend.spec["models"]))


# -- standards ----------------------------------------------------------------------------------
def test_standards_layer_nearest_last_and_follow_related_namespace_and_extends(tmp_path):
  """A repo layer adds to the machine-wide one, and related, namespace and extends chains are walked whole."""
  standard(tmp_path / "global", "python", applies="*.py", body="global rules")
  standard(tmp_path / "repo", "python", applies="*.py", body="repo rules")
  layers = Library(tmp_path / "global", [tmp_path / "repo"]).for_file("a.py")
  assert [l.origin for l in layers] == ["machine-wide", "repo"]
  assert "global rules" in layers[0].doc.body and "repo rules" in layers[1].doc.body
  g, under, alone, d = tmp_path / "g", tmp_path / "under", tmp_path / "alone", tmp_path / "std"
  standard(g, "a", applies="*.py", related="b")
  standard(g, "b", related="c")
  standard(g, "c")
  assert [layer.doc.name for layer in Library(g).for_file("x.py")] == ["a", "b", "c"]
  standard(under, "ml", body="general ml")
  standard(under, "ml.runs", applies="train_*.py", body="run process")
  standard(alone, "ml.runs", applies="train_*.py")
  assert [layer.doc.name for layer in Library(under).for_file("train_x.py")] == ["ml", "ml.runs"]
  assert [layer.doc.name for layer in Library(alone).for_file("train_x.py")] == ["ml.runs"]
  nested = tmp_path / "nested"
  for name in ("a", "a.b", "agent"): standard(nested, name)
  standard(nested, "a.b.c", applies="*.py")
  standard(nested, "agent-notes", applies="*.md")
  assert [layer.doc.name for layer in Library(nested).for_file("x.py")] == ["a", "a.b", "a.b.c"]   # every enclosing name, outermost first
  assert [layer.doc.name for layer in Library(nested).for_file("x.md")] == ["agent-notes"]          # a hyphen is not a namespace
  standard(d, "c", applies="", body="C")
  (d / "b.md").write_text("---\nname: b\nextends: c\n---\n\nB\n")
  (d / "a.md").write_text("---\nname: a\napplies: *.py\nextends: b\n---\n\nA\n")
  assert [layer.doc.name for layer in Library(d).for_file("x.py")] == ["c", "b", "a"]
  doc = parse("---\nname: x\nno closing fence\n")    # a hand edit, which must not lose the body
  assert doc.meta == {} and "no closing fence" in doc.body
  assert parse("---\nrelated:\n---\n\nb").list("related") == []


def test_a_section_naming_a_file_governs_that_file_alone(tmp_path):
  """A filename heading scopes its rules; a prose heading does not, and a split part counts as its note."""
  body = ("A note is a note.\n\n## context.md\n\nCONTEXT-RULE\n\n## learned.md\n\nLEARNED-RULE\n\n"
          "## Findings go in learned.md\n\nPROSE-RULE\n\n## All four\n\nSHARED-RULE\n")
  (tmp_path / "s.md").write_text(f"---\nname: s\napplies: *.md\n---\n\n{body}")
  l = Library(tmp_path).layers["s"][0]
  for name, want, other in (("context.md", "CONTEXT-RULE", "LEARNED-RULE"), ("learned.md", "LEARNED-RULE", "CONTEXT-RULE")):
    got = l.for_name(name)
    assert want in got and other not in got and "SHARED-RULE" in got and "PROSE-RULE" in got
  (tmp_path / "s.md").write_text("---\nname: s\napplies: *.md\n---\n\nx\n\n## Never run a formatter\n\nF\n\n## Tests\n\nT\n")
  whole = Library(tmp_path).layers["s"][0]
  assert whole.for_name("mod.py") == whole.doc.body
  a = tmp_path / ".agents"
  (a / "learned").mkdir(parents=True)
  assert notes.match_name(a / "learned" / "01-traps.md") == "learned.md"
  assert notes.match_name(a / "context.md") == "context.md" and notes.match_name(tmp_path / "mod.py") == "mod.py"
  assert notes.is_note(a / "context.md") and notes.is_note(a / "context" / "01-x.md")
  assert not notes.is_note(a / "standards" / "context.md")      # right name, wrong place
  assert not notes.is_note(a / "deep" / "learned" / "01-x.md")   # a split part, one level too deep
  assert not notes.is_note(a / "README.md")


def test_a_repos_agents_toml_reaches_inject_and_review_alike(tmp_path, monkeypatch):
  """[applies] in either TOML shape names a repo's own files, and [review] adds excludes but overrides numbers."""
  assert inject.flatten_applies({"voice": "projects.json"}) == {"voice": ["projects.json"]}
  assert inject.flatten_applies({"ml": {"runs": ["t.py"]}}) == {"ml.runs": ["t.py"]}
  standard(tmp_path / "g", "ml.runs", applies="train_*.py")
  assert Library(tmp_path / "g").matching("fit.py") == []
  assert Library(tmp_path / "g", extra_applies={"ml.runs": ["fit.py"]}).matching("fit.py") == ["ml.runs"]
  (mine := tmp_path / "profile").mkdir()
  (mine / "config.toml").write_text('[review]\nexclude = ["**/__pycache__/*"]\njobs = 2\nlimit = 99\n')
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")
  root = git(tmp_path / "site")
  (root / ".agents").mkdir()
  (root / ".agents" / "agents.toml").write_text(
    '[applies]\nmarkdown = ["go.py", "projects.json"]\n\n[review]\nexclude = ["docs/*"]\njobs = 8\n')
  f, prose = put(root, "go.py", "projects.json")
  assert "markdown" in [layer.doc.name for layer in inject.library_for(f).for_file(f.name)]   # a starter, so it exists
  assert tree.payload(f)[0] == ""                    # counted for config, and it brings no notes
  cfg = profile.section("review", root, add=("exclude",))
  assert cfg["exclude"][-2:] == ["**/__pycache__/*", "docs/*"]     # accumulated, the shipped ones first
  assert cfg["jobs"] == 8 and cfg["limit"] == 99 and "applies" not in cfg
  routed = dict(review.plan(["doc-check", "file-review"], ag.definitions(), [prose], [], {}, explicit=False))
  assert routed.get("doc-check") == [prose] and "file-review" not in routed


# -- the note chain -------------------------------------------------------------------------
def test_the_chain_is_outermost_first_stops_at_the_root_and_injects_only_context(tmp_path):
  """Only a .agents holding notes joins the chain, nothing above the repo root does, and only context loads."""
  note(tmp_path / "outside")
  root = git(tmp_path / "outside" / "inner")
  (root / "standards").mkdir()
  (root / "agents").mkdir()
  a, deep = note(root, "ROOT-CTX"), root / "src" / "pkg"
  note(deep, "pkg")
  assert tree.is_hub(a) is True
  assert tree.chain(deep / "f.py") == [a, deep / ".agents"]
  (root / "empty" / ".agents" / "skills").mkdir(parents=True)
  assert tree.find_note_dirs(root) == [a, deep / ".agents"]
  assert tree.chain(root / "empty" / "f.py") == [a]
  assert tree.note_dirs_for(root / "empty" / "deep") == [a]                 # nothing in or under it: the nearest above
  assert tree.note_dirs_for(root / "empty" / ".agents" / "skills") == [a]   # a `.agents` without notes is not one it is in
  (a / "learned.md").write_text("---\nname: learned\nkind: learned\n---\n\n# L\n\n## Traps\n\nx\n")
  body, mention, _ = tree.payload(root / "f.py")
  assert "ROOT-CTX" in body and "Traps" not in body          # only context is injected
  assert any("learned.md" in m for m in mention)             # and the rest is advertised
  (a / "agents.toml").write_text('inject = "none"\n')
  assert tree.payload(root / "f.py")[0] == ""                # and a directory can opt out entirely


def test_a_walk_never_enters_a_directory_it_would_skip(tmp_path, monkeypatch):
  """Finding notes and discovering files without git both prune before descending, not after."""
  root = git(tmp_path / "repo")
  note(root)
  note(root / "node_modules" / "pkg")
  plain = tmp_path / "plain"
  skipped = (".venv", "node_modules", "pkg.egg-info", ".ipynb_checkpoints", "cdk.out")
  put(plain, "src/mod.py", ".venv/lib/noise.py", *(f"{s}/noise.py" for s in skipped[1:]))
  entered, real = [], os.walk
  def walk(top, *a, **k):
    for here, dirs, files in real(top, *a, **k):
      entered.append(Path(here))
      yield here, dirs, files
  monkeypatch.setattr(os, "walk", walk)
  assert tree.find_note_dirs(root) == [root / ".agents"]
  assert entered and not [h for h in entered if "node_modules" in h.relative_to(tmp_path).parts]
  entered.clear()
  assert [p.name for p in review.discover(plain, [], 200_000)] == ["mod.py"]
  assert entered and not [h for h in entered if set(skipped) & set(h.relative_to(plain).parts)]


def test_init_writes_a_context_and_a_readme_and_never_overwrites_one(tmp_path):
  """Init records nothing about where it sits, and a README is never a note."""
  root = git(tmp_path)
  (root / ".agents").mkdir()
  (root / ".agents" / "README.md").write_text("mine\n")
  assert not notes.note_files(root / ".agents")             # a README alone opts nothing in
  tree.init(root)
  assert (root / ".agents" / "README.md").read_text() == "mine\n"
  pkg = root / "pkg"
  tree.init(pkg)
  assert (pkg / ".agents" / "README.md").read_text() == (profile.TEMPLATES / "agents" / "README.md").read_text()   # the template, as it ships
  assert [p.name for p in notes.note_files(pkg / ".agents")] == ["context.md"]
  assert not (pkg / ".agents" / "agents.toml").exists()   # a written path would not survive a clone


def learned(d: Path, body: str = "## Settled\n\na\n\n## Traps\n\nb\n") -> Path:
  d.mkdir(parents=True, exist_ok=True)
  f = d / "learned.md"
  f.write_text(f"---\nname: learned\nkind: learned\n---\n\n# What we learned\n\nNewest first.\n\n{body}")
  return f


def lands(lines: list[str], row: str) -> bool:
  """Whether the line a map row points at is the heading it names."""
  name, num = [c.strip() for c in row.strip("|").split("|")]
  return num.isdigit() and lines[int(num) - 1].strip().endswith(name)


def test_the_map_numbers_the_lines_it_sits_in_and_settles_in_one_pass(tmp_path):
  """Writing the block shifts every line it records, so the numbers must land after it is written."""
  out = mapblock.apply("---\nname: n\n---\n\n# T\n\n## A\n\nx\n\n## B\n\ny\n")
  lines = out.splitlines()
  assert lines[0] == "---" and lines[4] == "# T" and lines[6] == mapblock.START   # below frontmatter and title
  rows = [l for l in lines if l.startswith("| ") and " | " in l][1:]
  assert rows and all(lands(lines, r) for r in rows)
  assert mapblock.apply(out) == out
  grown = mapblock.apply(out + "\n## C\n\nz\n")      # a new section resizes the block
  assert mapblock.apply(grown) == grown
  assert lands(grown.splitlines(), next(l for l in grown.splitlines() if l.startswith("| C |")))
  assert mapblock.START not in mapblock.apply("# T\n\n## Only\n\nx\n")      # one section, no table
  f = learned(tmp_path)
  notes.remap(f)
  assert mapblock.apply(f.read_text()) == f.read_text()
  f.write_text(f.read_text() + "\n## Open\n\nc\n```\n## Not a heading\n```\n")
  assert mapblock.apply(f.read_text()) != f.read_text()
  assert [n for n, _ in mapblock.headings(f.read_text().splitlines())] == ["Settled", "Traps", "Open"]


def test_split_writes_numbered_parts_and_leaves_the_note_as_an_index(tmp_path):
  """Parts keep the note's order, short names, their own map, and no invented frontmatter."""
  f = learned(tmp_path, "## A\n\n### one\n\nx\n\n### two\n\ny\n\n```md\n## not a section\n```\n\n## B\n\nz\n")
  f.write_text(f.read_text().replace("Newest first.",
    "<!-- map: old -->\n\n| section | line |\n|---|---|\n\n<!-- /map -->\n\nNewest first."))
  assert [p.name for p in notes.split(f)] == ["01-a.md", "02-b.md"]
  first = (tmp_path / "learned" / "01-a.md").read_text()
  assert "## not a section" in first and mapblock.START in first     # two subsections, so a map
  assert mapblock.START not in (tmp_path / "learned" / "02-b.md").read_text()
  text = f.read_text()
  assert "Newest first." in text and "(learned/02-b.md)" in text
  assert "## B" not in text and "<!-- map:" not in text
  long = learned(tmp_path / "long", "## Measurement traps, each of which cost a run\n\na\n\n## Open\n\nb\n")
  assert notes.split(long)[0].name == "01-measurement-traps-each-of-which.md"
  bare, = put(tmp_path, "bare/learned.md", text="# What we learned\n\npreamble\n\n## A\n\nx\n\n## B\n\ny\n")
  notes.split(bare)
  assert not bare.read_text().startswith("---")


def test_split_leaves_alone_a_note_with_nothing_to_split_and_refuses_one_already_split(repo):
  ctx = repo / ".agents" / "context.md"
  ctx.write_text("---\nname: context\n---\n\n# r\n\n<!-- map: generated -->\n\n| section | line |\n"
                 "|---|---|\n\n<!-- /map -->\n\nno sections here\n")
  before = ctx.read_bytes()
  assert notes.split(ctx) == [] and ctx.read_bytes() == before
  ctx.write_text("---\nname: context\n---\n\n# r\n\n## A\n\na\n\n## B\n\nb\n")
  notes.split(ctx)
  ctx.write_text(ctx.read_text() + "\n## C\n\nc\n")
  with pytest.raises(ValueError, match="already split"):
    notes.split(ctx)
  assert sorted(p.name for p in (repo / ".agents" / "context").iterdir()) == ["01-a.md", "02-b.md"]


# -- a conversation -----------------------------------------------------------------------------
def test_a_reply_is_read_wherever_its_object_sits_and_prose_is_a_failure():
  """Unparseable is failed, not a clean pass; findings come out of either shape, with blank ones dropped."""
  assert session._parse("I had a look and it seems fine", "doc-check").state == "failed"
  assert session._parse('{"kind": "findings", "state": "compl', "doc-check").state == "failed"
  ok = session._parse('{"kind": "note", "state": "completed", "body": "nothing wrong"}', "doc-check")
  assert ok.state == "completed" and ok.body == "nothing wrong"
  for reply, found in [
    ('```json\n{"kind": "note", "state": "completed", "body": "ok"}\n```\nI weighed `{x}` too.', None),
    ('Looked at `{a: 1}` first.\n{"kind": "findings", "state": "completed", "data": {"findings": []}}', []),
    ('{"kind": "findings", "state": "completed", "data": {"findings": [{"line": 99-106, "issue": "x"}]}}',
     [{"line": "99-106", "issue": "x"}]),
    ('{"state": "completed", "body": "x", "data": [{"line": 3, "issue": "x"}]}', [{"line": 3, "issue": "x"}]),
  ]:
    m = session._parse(reply, "simplify")
    assert m.state == "completed" and m.data.get("findings") == found, reply

  real = {"line": 1, "issue": "real"}
  for data, kept in [({"findings": [real]}, [real]), ([real], [real]), (None, []), ({"findings": "prose"}, []),
                     (["not a finding", real, {"line": 149, "issue": "  ", "fix": ""}], [real])]:
    assert review.findings(data) == kept, data


def test_a_session_turn_keeps_its_tier_and_its_cap_and_a_dead_backend_costs_nothing():
  """The tier is never guessed, the last allowed message is sent, and a failed call leaves the transcript alone."""
  b, s = Stub(), Session("t")
  s.send("doc-check", b, "look", tier="code-large")
  s.answer("doc-check", b, "fixed it", tier="code-large")
  assert [t for t, _ in b.asked] == ["code-large", "code-large"]
  with pytest.raises(TypeError):     # no default, so the tier cannot go missing
    s.answer("doc-check", b, "and again")

  s = Session("t")
  s.post(Message("caller", "note", "working", "review this"))
  s.post(Message("rev", "findings", "completed", "one finding"))
  msg = s.send("rev", Stub(ConnectionError("closed")), "fixed it, recheck")
  assert msg.state == "failed" and "ConnectionError" in msg.body
  assert [m.state for m in s.messages] == ["working", "completed"]
  s, b = Session("t", max_turns=3), Stub()
  s.send("doc-check", b, "first")
  assert s.send("doc-check", b, "second").state == "failed"
  assert [m.body for m in s.messages if m.sender == "caller"] == ["first"] and len(b.shown) == 1


def test_a_conversation_continues_from_the_ledger_and_only_a_verdict_replaces_its_findings(ledger, monkeypatch, capsys):
  """A reply carries the file as it is now, and an answer or a failed recheck leaves findings open."""
  f, = put(ledger, "mod.py", text="x = 1  # BEFORE\n")
  b = Stub(findings({"line": 1, "issue": "no author line", "fix": "add it"}),
           {"kind": "answer", "state": "completed", "body": "I would test add(2, 3) first."},
           {"kind": "note", "state": "failed", "body": "timed out"})
  monkeypatch.setattr(backends, "get", lambda *a, **k: b)
  monkeypatch.chdir(ledger)
  assert cli.main(["sub", "run", "file-review", "mod.py", "--task", "talk"]) == 0
  kept = reviews.latest("talk", ledger)
  assert kept["file"] == "mod.py" and kept["run"] and len(kept["messages"]) == 2
  still = lambda: [x["issue"] for x in reviews.open_findings(ledger)]
  reply = lambda task, text: cli.main(["sub", "reply", task, text, "--root", str(ledger)])
  assert still() == ["no author line"]
  f.write_text("x = 2  # AFTER\n")
  reply("talk", "what would you test first?")
  assert len(reviews.latest("talk", ledger)["messages"]) == 4           # the same conversation, continued
  assert "AFTER" in b.shown[-1] and "BEFORE" not in b.shown[-1].split("what would you test first?", 1)[1]
  assert still() == ["no author line"]          # an answer is not a verdict
  reply("talk", "fixed, recheck")
  assert still() == ["no author line"]          # nor is a recheck that failed
  reply("talk", "fixed, recheck")
  assert still() == []                          # a clean verdict is
  assert cli.main(["sub", "run", "file-review", "mod.py", "--task", "gone"]) == 0   # a fresh turn cap
  f.unlink()
  reply("gone", "removed it")
  assert "has since been deleted" in b.shown[-1]
  assert not (Path.home() / ".agents" / "sessions" / "talk.json").exists()


# -- review ------------------------------------------------------------------------------------
def run_review(name, backend, paths, root, **kwargs): return review.run(name, backend, paths, root, ag.definition(name, ag.definitions()), {}, **kwargs)


def test_the_models_are_handed_back_even_when_a_review_raises(tmp_path, monkeypatch):
  released = []

  class Holds:
    name, parallel, timeout = "holds", 1, 1
    def model_for(self, tier): return f"m-{tier}"
    def release(self, tier): return released.append(tier) or True

  plan = [("file-review", [tmp_path / "x.py"])]
  monkeypatch.setattr(review, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
  with pytest.raises(RuntimeError):
    cli.sub._fan_out(plan, Holds(), tmp_path, 1, None, ag.definitions(), {}, {})
  assert released == ["code-large"]
  released.clear()
  monkeypatch.setattr(review, "run", lambda *a, **k: [])
  cli.sub._fan_out(plan, Holds(), tmp_path, 1, None, ag.definitions(), {}, {}, keep=True)
  assert released == []                       # --keep still means keep


def test_discover_asks_git_what_exists_and_filters_by_path_not_name(tmp_path):
  """`exclude` matches the relative path; the skip check ignores where the repo sits."""
  root = git(tmp_path / "build" / "repo")
  put(root, "café.py", "keep.py", "sub/keep.py", "sub/migrations/0001.py", "dist/gen.py", "untracked.py")
  put(root, "big.py", text="x" * 300_000)
  subprocess.run(["git", "add", "-A", ":!untracked.py"], cwd=root, check=True)
  found = lambda exclude=(), max_bytes=200_000: [p.relative_to(root).as_posix() for p in review.discover(root, list(exclude), max_bytes)]
  assert found() == ["café.py", "keep.py", "sub/keep.py", "sub/migrations/0001.py"]   # not dist, untracked, big
  assert found(exclude=["sub/migrations/*"]) == ["café.py", "keep.py", "sub/keep.py"]
  assert found(exclude=["keep.py"]) == ["café.py", "sub/keep.py", "sub/migrations/0001.py"]
  assert found(exclude=["sub/*"]) == ["café.py", "keep.py"]        # fnmatch's * crosses /
  assert found(max_bytes=1) == []


def test_a_commit_reviews_what_it_touched_filtered_to_what_the_standards_govern(tmp_path, monkeypatch, capsys):
  """A spaced path stays whole, a named file is an explicit ask, and nothing under __pycache__ is reviewed."""
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
  repo = git(tmp_path / "repo")
  put(repo, "my notes.py", "pkg/mod.py", "pkg/__pycache__/stray.py")
  commit(repo)
  monkeypatch.chdir(repo)
  assert cli.main(["sub", "review", "simplify", "--commit", "HEAD", "--dry-run"]) == 0
  out = capsys.readouterr()
  assert "pkg/mod.py" in out.out and "my notes.py" in out.out and "__pycache__" not in out.out and "skipping 1 file under __pycache__" in out.err
  paths = [tmp_path / n for n in ("a.py", "notes.md", "logo.png", "b.pyi")]
  assert [p.name for p in review.plan(["file-review"], ag.definitions(), paths, [], {}, globs=["*.py", "*.pyi"])[0][1]] == ["a.py", "b.pyi"]
  assert len(review.plan(["file-review"], ag.definitions(), paths, [], {})[0][1]) == 4   # no patterns means the caller already chose
  files = [tmp_path / n for n in ("a.py", "logo.png")]
  assert [p.name for p in review.plan(["file-review"], ag.definitions(), files, [], {}, explicit=True)[0][1]] == ["a.py", "logo.png"]
  assert [p.name for p in review.plan(["file-review"], ag.definitions(), files, [], {}, explicit=False)[0][1]] == ["a.py"]


def test_a_file_goes_to_the_most_specific_reviewer_of_its_kind(ledger):
  """Every agent belongs to one kind, and asking for a kind sends each file to the variant made for it."""
  found = ag.definitions()
  assert sorted(n for group in ag.kinds(found).values() for n in group) == sorted(found)   # every agent, once
  with pytest.raises(SystemExit, match="file-review.*agent sub agents"):   # names the agents, and where the kinds are
    ag.definition("nonesuch", found)

  put(ledger, ".agents/learned.md", ".agents/learned/traps.md", ".agents/context.md", text="---\nname: x\nkind: learned\n---\n\nx\n")
  put(ledger, "README.md", "mod.py")
  subprocess.run(["git", "add", "-A"], cwd=ledger, check=True)   # discovery reads what git tracks
  names = ag.kinds(found)["refine"]
  rel = lambda plans: {n: sorted(p.relative_to(ledger).as_posix() for p in sel) for n, sel in plans}
  named = [ledger / "README.md", ledger / ".agents/learned/traps.md", ledger / "mod.py"]
  assert rel(review.plan(names, found, named, [], {})) == {"refine": ["README.md"], "refine.learned": [".agents/learned/traps.md"]}
  assert rel(review.plan(names, found, [], review.discover(ledger, [], 200_000), {})) == {"refine": [".agents/context.md", "README.md"],
                                                        "refine.learned": [".agents/learned.md", ".agents/learned/traps.md"]}
  kinds = ag.kinds(found)
  assert review.variant("refine", "default", kinds) == "refine" and review.variant("refine", "learned", kinds) == "refine.learned"
  with pytest.raises(ValueError, match="default, learned"): review.variant("refine", "todo", kinds)
  with pytest.raises(ValueError, match="no 'x' variant$"): review.variant("logic", "x", kinds)   # file-review is of the kind, not a variant


def test_an_agent_sends_only_the_standards_that_govern_the_file_resolved_as_inject_does(tmp_path, monkeypatch):
  """A reviewer gets the standards for this file, including those a repo's [applies] and a profile add."""
  d = tmp_path / "standards"
  standard(d, "python", applies="*.py", body="PYTHON RULES")
  standard(d, "markdown", applies="*.md", body="MARKDOWN RULES")
  lib = Library(d)
  doc = parse("---\nname: a\nstandards: python, markdown\n---\n\nbody")
  every = ag.instructions(doc, lib)
  assert "PYTHON RULES" in every and "MARKDOWN RULES" in every
  said = ag.instructions(doc, lib, "notes.md")
  assert "MARKDOWN RULES" in said and "PYTHON RULES" not in said
  said = ag.instructions(doc, lib, "mod.py")
  assert "PYTHON RULES" in said and "MARKDOWN RULES" not in said
  assert "PYTHON RULES" in ag.instructions(doc, lib, "logo.png")   # nothing matched: send them all
  mine = tmp_path / "mine"
  standard(mine / "standards", "runs", applies="train_*.py", body="RUN-RULE nothing launches unreviewed")
  put(mine, "agents/file-review.md", text="---\nname: file-review\nkind: logic\nstandards: python, runs\n---\nReview it.\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  repo = git(tmp_path / "repo")
  (note(repo, "x") / "agents.toml").write_text('[applies]\nruns = ["eval.py"]\n')
  f, = put(repo, "eval.py")
  doc = ag.definition("file-review", ag.definitions())
  assert "RUN-RULE" not in ag.instructions(doc, Library(), f)
  assert "RUN-RULE" in ag.instructions(doc, inject.library_for(f), f)


# -- the review ledger ----------------------------------------------------------------------------
def record(root, task, file, found, body="verdict"):
  s = Session(task)
  s.post(Message("caller", "note", "working", "review this"))
  m = Message("file-review", "findings", "completed", body)
  s.post(m)
  return reviews.record(s, "file-review", "ollama", root, file, m, found, "large")


def test_the_write_queue_keeps_every_record_or_raises(ledger, monkeypatch):
  """Every queued record lands in order, and a store that cannot open raises rather than losing the queue."""
  with reviews.writer(ledger) as put_row:
    for i in range(6):
      put_row(record(ledger, f"t{i}", f"f{i}.py", [{"line": i, "issue": f"bad {i}"}]))
  rows = reviews.conversations(ledger)
  assert len(rows) == 6 and [r["id"] for r in rows] == sorted(r["id"] for r in rows)   # uuid7 orders itself
  assert (ledger / ".agents" / ".gitignore").read_text().splitlines() == [".reviews/", ".local/"]
  monkeypatch.setattr(reviews, "connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no duckdb")))
  with pytest.raises(RuntimeError, match="no duckdb"), reviews.writer(ledger) as put_row:
    put_row({"id": "x"})


def test_open_findings_are_the_newest_verdict_on_a_file_that_still_has_content(ledger):
  """A newer verdict supersedes, an emptied or deleted file has none, and old rows and old ledgers still read."""
  duckdb = pytest.importorskip("duckdb")
  f, a = put(ledger, "mod.py", "a.py")
  reviews.write(record(ledger, "t", "mod.py", [{"line": 1, "issue": "backwards"}]), ledger)
  con = duckdb.connect(str(reviews.path(ledger)))
  con.execute("drop table closures")                 # a ledger from before closures existed
  con.close()
  assert reviews.dismissals(ledger) == {}
  assert [x["issue"] for x in inject.open_findings(f)] == ["backwards"]
  reviews.write(record(ledger, "t", "mod.py", [], "clean now"), ledger)
  assert reviews.open_findings(ledger) == [] and inject.open_findings(f) == []
  assert reviews.conversation(reviews.latest("t", ledger)).messages        # and still resumable
  rec = record(ledger, "t-a", "a.py", [{"line": "133, 136 vs 137", "issue": "real"}, {"line": 9, "issue": "   "}])
  rec["findings"][0]["file"] = str(a)                # as a model once echoed it
  rec["findings"][1]["file"] = "a.py"
  reviews.write(rec, ledger)
  assert [(r["file"], r["issue"]) for r in reviews.open_findings(ledger)] == [("a.py", "real")]
  assert reviews.first_line("133, 136 vs 137-139") == 133
  a.unlink()
  assert reviews.open_findings(ledger) == [] and reviews.to_recheck(ledger) == {}
  b = Stub(findings({"line": 1, "issue": "x is unused", "fix": "drop it"}))
  run_review("file-review", b, [f], ledger, tier="code")
  assert reviews.open_findings(ledger)
  f.write_text("")
  run_review("file-review", b, [f], ledger, tier="code")
  assert reviews.open_findings(ledger) == []


def test_a_finding_closes_by_line_range_or_id_and_only_wrong_is_passed_back(ledger):
  """`wrong` tells the next reviewer and `fixed` stays on the recheck list until a verdict lands after it."""
  put(ledger, "a.py", "mod.py", "o.py", "c.py")
  reviews.write(record(ledger, "t-a", "a.py", [{"line": 9, "issue": "backwards"}, {"line": 12, "issue": "stale comment"}]), ledger)
  closed = reviews.close(ledger, "a.py", 9, "wrong", "lower is better here, the comparison is right")
  assert [c["issue"] for c in closed] == ["backwards"]
  assert [x["issue"] for x in reviews.open_findings(ledger)] == ["stale comment"]
  quiet = reviews.dismissals(ledger)["a.py"]
  assert quiet[0]["reason"].startswith("lower is better")
  b = Stub()
  review.file("file-review", b, ledger / "a.py", ag.definition("file-review", ag.definitions()), "text", ledger, quiet, libraries={})
  said = b.shown[-1]
  assert "backwards" in said and "closed as wrong" in said
  reviews.close(ledger, "a.py", 0, "fixed")
  assert reviews.open_findings(ledger) == []
  assert list(reviews.dismissals(ledger)) == ["a.py"]   # only the one closed as wrong
  reviews.write(record(ledger, "t-mod", "mod.py", [
    {"line": "12-14", "issue": "first"}, {"line": 30, "issue": "second"}, {"line": "40-41", "issue": "third"},
    {"line": 168, "issue": "fourth"}, {"line": 200, "issue": "fifth"}]), ledger)
  issues = lambda target, line=0: [x["issue"] for x in reviews.close(ledger, target, line, "fixed")]
  assert issues("mod.py", 12) == ["first"]
  assert issues("mod.py", 30) == ["second"]
  assert issues("mod.py", 40) == ["third"]
  assert issues("mod.py", 163) == []                    # where an edit moved it: no match
  fourth = next(x for x in reviews.open_findings(ledger) if x["issue"] == "fourth")
  assert issues(reviews.short_id(fourth["id"])) == ["fourth"]
  assert issues("mod.py") == ["fifth"]
  for name in ("o.py", "c.py"): reviews.write(record(ledger, f"t-{name}", name, [{"line": 1, "issue": "x"}]), ledger)
  reviews.close(ledger, "c.py", 0, "wrong", "it is right")
  assert cli.main(["sub", "close", "o.py:1-2", "--as", "fixed", "--root", str(ledger)]) == 0   # the command reads a line the way reviewers write one
  assert reviews.to_recheck(ledger) == {"file-review": ["a.py", "mod.py", "o.py"]}
  reviews.write(record(ledger, "t-a", "a.py", [], "clean"), ledger)
  reviews.write(record(ledger, "t-mod", "mod.py", [], "clean"), ledger)
  assert reviews.to_recheck(ledger) == {"file-review": ["o.py"]}   # the claims have been checked


# -- what the person is told ----------------------------------------------------------------------
def test_what_the_person_is_told_arrives_whole(ledger, capsys):
  """The hook log reads back by session and parses into columns; model text survives the table and the pipe."""
  log = ledger / "h.log"
  log.write_text("t1\tinject\tabc12345\tsent 10 bytes\n"
                 "t2\tforget\tabc12345\tcleared 2 stamps\n"
                 "t3\tinject\tzz999999\tsent 20 bytes\n")
  assert len(hooks.entries(log=log)) == 3
  assert [r[1] for r in hooks.entries(session="abc12345", log=log)] == ["inject", "forget"]
  assert hooks.entries(session="abc123", log=log)                    # a prefix is enough
  assert [r[0] for r in hooks.entries(hook="forget", log=log)] == ["t2"]
  assert hooks.entries(log=ledger / "nope.log") == []
  log.write_text("2026-09-21T17:34:37-05:00\tinject\tabc12345\tsent   7445 bytes  /x/y.py\nnot a log line at all\n")
  hooks.log("post-commit", "git", "done   project: 2 findings in 3 reviews", log=log)
  rows = hooks.entries(log=log)
  assert rows[0] == ["2026-09-21T17:34:37-05:00", "inject", "abc12345", "sent", "7445 bytes  /x/y.py"]
  assert rows[1][-1] == "not a log line at all"      # nothing is dropped for being unparseable
  assert rows[2][1:4] == ["post-commit", "git", "done"] and "2 findings" in rows[2][4]
  text = "Uses `[learned.md](learned.md)` instead of wikilink `[[learned]]`"
  assert out.plain(out.escape(text)) == text          # rich read `[[context]]` as markup
  assert [out.took(s) for s in (42, 59.6, 185)] == ["42s", "1m00s", "3m05s"]
  assert out.plain("[dim]code-large[/dim]") == "code-large"
  put(ledger, "mod.py")
  long = "First sentence. " + "word " * 60
  reviews.write(record(ledger, "t", "mod.py", [{"line": 1, "issue": long}]), ledger)
  show.findings(reviews.open_findings(ledger))
  row = capsys.readouterr().out.strip().split("\t")
  assert row[3] == " ".join(long.split()) and row[4] == reviews.short_id(reviews.open_findings(ledger)[0]["id"])


def test_a_command_name_cannot_be_registered_twice(monkeypatch):
  monkeypatch.setattr(command, "COMMANDS", list(command.COMMANDS))
  command.command("only-once")(lambda a: 0)
  with pytest.raises(ValueError, match="already registered"):
    command.command("only-once")(lambda a: 0)


def test_doctor_names_an_unknown_setting_and_judges_format_on_save_by_its_value(tmp_path, monkeypatch):
  """A typo or a missing standard is named, and format-on-save is flagged only when it is really on."""
  repo, plain = git(tmp_path / "repo"), tmp_path / "plain"
  (note(repo) / "agents.toml").write_text('inject = "ful"\n\n[applies]\nnosuch = ["mod.py"]\n')
  monkeypatch.chdir(repo)
  bad = [what for ok, what, _ in doctor.checks() if not ok]
  assert f"{repo.name}/agents.toml inject = 'ful'" in bad and f"{repo.name}/agents.toml applies -> nosuch" in bad
  for where, setting, on in ((repo, '"editor.formatOnSave": true', True), (repo, '"editor.formatOnSave": false', False),
                             (plain, '// "editor.formatOnSave": true,\n  "a": 1', False)):   # plain is outside any repo
    put(where, ".vscode/settings.json", text=f'{{\n  // mine\n  {setting}\n}}')
    monkeypatch.chdir(where)
    assert [ok for ok, what, _ in doctor.checks() if "format-on-save" in what] == [not on], setting



def test_doctor_fails_on_a_hook_error_only_since_agents_last_changed(monkeypatch):
  """A hook that crashed lets the edit through, so the log is the only place it shows; one from before the last commit came from code that no longer runs."""
  monkeypatch.setattr(hooks, "entries", lambda: [["2000-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "stale"], ["2100-01-01T09:00:00+0000", "inject", "abc12345", "sent", "2 standards"]])
  assert [ok for ok, what, _ in doctor.checks() if "hook errors" in what] == [True]
  monkeypatch.setattr(hooks, "entries", lambda: [["2100-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "jq: parse error"]])
  (ok, _, fix), = [check for check in doctor.checks() if "hook errors" in check[1]]
  assert not ok and fix.startswith("1 logged, the latest from inject: jq: parse error")

# -- a review run, as it is watched ---------------------------------------------------------------
def test_a_run_reports_each_file_as_it_finishes_under_its_own_name(ledger, monkeypatch):
  """An empty file is never sent, a slow one holds back nothing, and a finding or a failure keeps the file's name."""
  b = Stub()
  out = run_review("file-review", b, put(ledger, "__init__.py", text="") + put(ledger, "blank.py", text="\n   \n"),
                   ledger, tier="code")
  assert b.shown == []
  assert {(r["file"], r["state"], r["body"]) for r in out} == {
    ("__init__.py", "completed", review.EMPTY), ("blank.py", "completed", review.EMPTY)}

  slow, quick = put(ledger, "slow.py", text="# SLOW\nx = 1\n") + put(ledger, "quick.py")
  started, landed = [], []
  run_review("file-review", Stub(), [slow, quick], ledger, tier="code",
             on_start=started.append, on_done=lambda r: landed.append(r["file"]))
  assert sorted(started) == ["quick.py", "slow.py"] and landed == ["quick.py", "slow.py"]
  b = Stub(findings({"file": "/somewhere/else.py", "line": 2, "issue": "backwards"}))
  result, rec = review.file("file-review", b, quick, ag.definition("file-review", ag.definitions()), "text", ledger, libraries={})
  assert [x["file"] for x in result["findings"]] == [x["file"] for x in rec["findings"]] == ["quick.py"]
  outside = ledger.parent / "elsewhere" / "b.py"
  assert review.label(outside, ledger) == str(outside)   # outside the root keeps a usable name
  monkeypatch.setattr(review, "file", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
  r, = run_review("file-review", Stub(), [quick], ledger, tier="code")
  assert r["file"] == "quick.py" and r["state"] == "failed" and "boom" in r["body"]


def test_a_run_is_tagged_so_it_can_be_found_filtered_and_reused(ledger):
  """A run is found by id, path or kind; only an edited file is asked again, unless the effort differs or --fresh."""
  assert {n: d.get("effort") for n, d in sorted(ag.definitions().items())} == {n: "medium" for n in sorted(ag.definitions())}
  b, (net, load, readme) = Stub(), put(ledger, "src/models/net.py", "src/data/load.py", "README.md")
  run_review("file-review", b, [net], ledger, tier="code", run="1003-0101-aaaa")
  run_review("file-review", b, [load, readme], ledger, tier="code", run="1003-0102-bbbb")
  assert len(b.shown) == 3 and {e for _, e in b.asked} == {"medium"}   # the definition's effort
  assert reviews.last_run(ledger) == "1003-0102-bbbb"
  rows = reviews.conversations(ledger)
  found = lambda **k: sorted(r["file"] for r in reviews.filtered(rows, ledger, **k))
  assert found(run="1003-0101") == ["src/models/net.py"]                    # a prefix of the id
  assert found(run="1003-0102") == ["README.md", "src/data/load.py"]
  assert found(path="src/") == ["src/data/load.py", "src/models/net.py"]    # a folder, nested
  assert found(path="src/models") == ["src/models/net.py"]                  # an existing folder, no slash
  assert found(path="*.md") == ["README.md"]                                # a file type
  assert found(agent="logic") == found(agent="file-review")                 # a kind or its agent
  assert found(failed=True) == []
  load.write_text("y = 3\n")
  out = {r["file"]: r for r in run_review("file-review", b, [net, load], ledger, tier="code", run="1003-0103-cccc")}
  assert len(b.shown) == 4                                        # only the edited file was asked
  assert out["src/models/net.py"]["reused"] == "1003-0101-aaaa" and not out["src/data/load.py"].get("reused")
  run_review("file-review", b, [net, load], ledger, tier="code", effort="low")
  assert len(b.shown) == 6 and b.asked[-1][1] == "low"          # the command's effort overrides
  run_review("file-review", b, [net, load], ledger, tier="code", effort="low", fresh=True)
  assert len(b.shown) == 8


def test_a_review_names_what_it_skipped_and_a_listing_defaults_to_where_you_stand(ledger, monkeypatch, capsys):
  """Shell scripts route to both reviewers; files no standard covers are named; --open from a folder shows that folder."""
  tool = ledger / "tool"
  (tool / "dotfiles").mkdir(parents=True)
  for name, text in (("install.sh", "#!/usr/bin/env bash\n"), ("README.md", "# t\n"), ("dotfiles/tmux.conf", "set -g mouse off\n")):
    (tool / name).write_text(text)
  subprocess.run(["git", "add", "-A"], cwd=ledger, check=True)   # discovery reads what git tracks
  monkeypatch.chdir(tool)
  cli.main(["sub", "review", ".", "--dry-run"])
  printed = capsys.readouterr()
  assert "file-review" in printed.out and "tool/install.sh" in printed.out
  assert "not reviewed, no standard covers them: 1 file (.conf 1) in tool/dotfiles/ 1" in printed.err
  assert "agent sub review logic dotfiles/tmux.conf" in printed.err          # a path that works from here

  (ledger / "top.py").write_text("x = 1\n")
  reviews.write(record(ledger, "t-top", "top.py", [{"line": 1, "issue": "elsewhere"}]), ledger)
  reviews.write(record(ledger, "t-here", "tool/install.sh", [{"line": 1, "issue": "here"}]), ledger)
  open_here = lambda *extra: (cli.main(["sub", "reviews", "--open", *extra]), capsys.readouterr())[1]
  scoped = open_here()
  assert "here" in scoped.out and "elsewhere" not in scoped.out and "under tool/" in scoped.err
  assert "elsewhere" in open_here("--all").out
