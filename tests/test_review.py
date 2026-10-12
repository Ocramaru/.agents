"""Tests for backends, a review conversation, which files a review reads, and which reviewer and standards it gets.

Author: Marco Cassar (@Ocramaru)
"""

import json
import subprocess
from types import SimpleNamespace

import pytest
from conftest import Stub, findings, git, note, put, standard

from agentkit import agents as ag, backends, cli, profile, review, reviews, session
from agentkit.backends import Backend, Reply, _fill
from agentkit.frontmatter import parse
from agentkit.session import Message, Session
from agentkit.standards import Library


def test_a_backend_fills_its_argv_once_and_finds_its_reply_in_whatever_it_printed(monkeypatch):
  """A payload survives substitution verbatim, the reply is found around noise, stdin is closed and a role resolves exactly."""
  prompt = 'review a.replace("{session}", x) and {model}'
  filled = _fill(["c", "-p", "{prompt}", "-m", "{model}", "-r", "{session}"], {"model": "haiku", "prompt": prompt, "session": "abc"})
  assert filled[2] == prompt and filled[4] == "haiku" and filled[6] == "abc"
  assert _fill(["{other}"], {"model": "m"}) == ["{other}"]   # not ours to fill in

  events = [{"type": "thread.started", "thread_id": "t-1"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}]
  assert Backend("codex", {"kind": "cli", "format": "jsonl", "resume_argv": ["x"], "session_key": "thread_id", "reply_key": "item.text"})._unwrap("\n".join(json.dumps(event) for event in events), None) == Reply("OK", "t-1")
  assert Backend("claude", {"kind": "cli", "format": "json", "session_key": "session_id", "reply_key": "result"})._unwrap('warning: something\n{"session_id": "s-1", "result": "done"}', None) == Reply("done", "s-1")

  seen = []
  monkeypatch.setattr(backends.subprocess, "run", lambda argv, **kwargs: seen.append((argv, kwargs)) or subprocess.CompletedProcess(argv, 0, '{"result": "ok"}', ""))
  backend = Backend("claude", {"kind": "cli", "format": "json", "reply_key": "result", "argv": ["claude", "-p", "{prompt}"], "effort_argv": ["--effort", "{effort}"], "models": {"text": "m"}})
  backend.run("hi")
  backend.run("hi", effort="low")
  assert all(kwargs.get("stdin") is subprocess.DEVNULL for _, kwargs in seen)
  assert "--effort" not in seen[0][0] and seen[1][0][-2:] == ["--effort", "low"]

  assert Backend("ollama", {"kind": "http", "url": "u"}).parallel == 1   # one process holds one model
  assert Backend("x", {"kind": "http", "url": "u", "parallel": 3}).parallel == 3
  with pytest.raises(ValueError, match="no model for role 'code'; it has text, code-large"): Backend("o", {"kind": "http", "url": "u", "models": {"text": "t", "code-large": "cl"}}).model_for("code")   # exact, never a guess


def test_a_reply_is_read_wherever_its_object_sits_and_a_turn_keeps_its_tier_and_its_cap():
  """Unparseable is failed, findings come out of either shape, the tier is never guessed and a dead backend costs no turn."""
  for prose in ["I had a look and it seems fine", '{"kind": "findings", "state": "compl']: assert session._parse(prose, "doc-check").state == "failed"

  for reply, found in [
    ('```json\n{"kind": "note", "state": "completed", "body": "ok"}\n```\nI weighed `{x}` too.', None),
    ('Looked at `{a: 1}` first.\n{"kind": "findings", "state": "completed", "data": {"findings": []}}', []),
    ('{"kind": "findings", "state": "completed", "data": {"findings": [{"line": 99-106, "issue": "x"}]}}', [{"line": "99-106", "issue": "x"}]),
    ('{"state": "completed", "body": "x", "data": [{"line": 3, "issue": "x"}]}', [{"line": 3, "issue": "x"}]),
  ]:
    message = session._parse(reply, "simplify")
    assert message.state == "completed" and message.data.get("findings") == found, reply

  real = {"line": 1, "issue": "real"}
  for data, kept in [({"findings": [real]}, [real]), (None, []), ({"findings": "prose"}, []), (["not a finding", real, {"line": 149, "issue": "  ", "fix": ""}], [real])]: assert review.findings(data) == kept, data

  backend, conversation = Stub(), Session("t")
  conversation.send("doc-check", backend, "look", tier="code-large")
  conversation.answer("doc-check", backend, "fixed it", tier="code-large")
  assert [tier for tier, _ in backend.asked] == ["code-large", "code-large"]
  with pytest.raises(TypeError): conversation.answer("doc-check", backend, "and again")   # no default, so the tier cannot go missing

  conversation = Session("t")
  conversation.post(Message("caller", "note", "working", "review this"))
  conversation.post(Message("rev", "findings", "completed", "one finding"))
  reply = conversation.send("rev", Stub(ConnectionError("closed")), "fixed it, recheck")
  assert reply.state == "failed" and "ConnectionError" in reply.body
  assert [message.state for message in conversation.messages] == ["working", "completed"]

  conversation, backend = Session("t", max_turns=3), Stub()
  conversation.send("doc-check", backend, "first")
  assert conversation.send("doc-check", backend, "second").state == "failed"
  assert [message.body for message in conversation.messages if message.sender == "caller"] == ["first"]
  assert len(backend.shown) == 1


def test_a_conversation_continues_from_the_ledger_and_only_a_verdict_replaces_its_findings(ledger, monkeypatch):
  """A reply carries the file's current text, and an answer or a failed recheck leaves findings open."""
  source, = put(ledger, "mod.py", text="x = 1  # BEFORE\n")
  backend = Stub(findings({"line": 1, "issue": "no author line", "fix": "add it"}), {"kind": "answer", "state": "completed", "body": "I would test add(2, 3) first."}, {"kind": "note", "state": "failed", "body": "timed out"})
  monkeypatch.setattr(backends, "get", lambda *args, **kwargs: backend)
  monkeypatch.chdir(ledger)
  assert cli.main(["sub", "run", "file-review", "mod.py", "--task", "talk"]) == 0
  assert (kept := reviews.latest("talk", ledger))["file"] == "mod.py" and kept["run"] and len(kept["messages"]) == 2

  still = lambda: [finding["issue"] for finding in reviews.open_findings(ledger)]
  reply = lambda task, text: cli.main(["sub", "reply", task, text, "--root", str(ledger)])
  assert still() == ["no author line"]
  source.write_text("x = 2  # AFTER\n")
  reply("talk", "what would you test first?")
  assert len(reviews.latest("talk", ledger)["messages"]) == 4   # the same conversation, continued
  assert "AFTER" in backend.shown[-1] and "BEFORE" not in backend.shown[-1].split("what would you test first?", 1)[1]
  assert still() == ["no author line"]   # an answer is not a verdict
  reply("talk", "fixed, recheck")
  assert still() == ["no author line"]   # nor is a recheck that failed
  reply("talk", "fixed, recheck")
  assert still() == []   # a clean verdict is

  assert cli.main(["sub", "run", "file-review", "mod.py", "--task", "gone"]) == 0   # a fresh turn cap
  source.unlink()
  reply("gone", "removed it")
  assert "has since been deleted" in backend.shown[-1]


def test_the_models_are_handed_back_even_when_a_review_raises(tmp_path, monkeypatch):
  """The fan-out releases each model it loaded, unless the caller asked to keep it."""
  released, plan = [], [("file-review", [tmp_path / "x.py"])]
  holds = SimpleNamespace(name="holds", parallel=1, timeout=1, model_for=lambda tier: f"m-{tier}", release=lambda tier: released.append(tier) or True)
  monkeypatch.setattr(review, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
  with pytest.raises(RuntimeError): cli.sub._fan_out(plan, holds, tmp_path, 1, None, ag.definitions(), {}, {})
  assert released == ["code-large"]

  monkeypatch.setattr(review, "run", lambda *args, **kwargs: [])
  cli.sub._fan_out(plan, holds, tmp_path, 1, None, ag.definitions(), {}, {}, keep=True)
  assert released == ["code-large"]   # --keep leaves the models loaded


def test_a_review_reads_the_files_git_lists_filtered_by_path_and_by_what_the_standards_govern(tmp_path, monkeypatch, capsys):
  """`exclude` matches the relative path, a spaced path stays whole, a named file is an explicit ask, and nothing under a skipped directory is reviewed."""
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
  root = git(tmp_path / "build" / "repo")
  put(root, "café.py", "keep.py", "my notes.py", "sub/keep.py", "sub/migrations/0001.py", "dist/gen.py", "pkg/__pycache__/stray.py", "untracked.py")
  put(root, "big.py", text="x" * 300_000)
  subprocess.run(["git", "add", "-f", "-A", ":!untracked.py"], cwd=root, check=True)
  subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "c"], cwd=root, check=True)

  found = lambda exclude=(), max_bytes=200_000: [path.relative_to(root).as_posix() for path in review.discover(root, list(exclude), max_bytes)]
  assert found() == ["café.py", "keep.py", "my notes.py", "sub/keep.py", "sub/migrations/0001.py"]   # not dist, __pycache__, untracked, big
  assert found(["keep.py"]) == ["café.py", "my notes.py", "sub/keep.py", "sub/migrations/0001.py"]
  assert found(["sub/*"]) == ["café.py", "keep.py", "my notes.py"]   # fnmatch's * crosses /
  assert found(max_bytes=1) == []

  monkeypatch.chdir(root)
  assert cli.main(["sub", "review", "simplify", "--commit", "HEAD", "--dry-run"]) == 0
  captured = capsys.readouterr()
  assert "sub/keep.py" in captured.out and "my notes.py" in captured.out
  assert "__pycache__" not in captured.out and "skipping 2 files under __pycache__, dist\n" in captured.err

  chosen = lambda names, **kwargs: [path.name for path in review.plan(["file-review"], ag.definitions(), [tmp_path / name for name in names], [], {}, **kwargs)[0][1]]
  assert chosen(["a.py", "notes.md", "logo.png", "b.pyi"], globs=["*.py", "*.pyi"]) == ["a.py", "b.pyi"]
  assert len(chosen(["a.py", "notes.md", "logo.png", "b.pyi"])) == 4   # no patterns means the caller already chose
  assert chosen(["a.py", "logo.png"], explicit=True) == ["a.py", "logo.png"]
  assert chosen(["a.py", "logo.png"], explicit=False) == ["a.py"]


def test_an_agent_has_one_kind_and_a_model_role_every_backend_declares_and_a_file_goes_to_the_variant_made_for_it(ledger, tmp_path, monkeypatch):
  """Every agent belongs to one kind and names a declared model role, and asking for a kind sends each file to its variant."""
  found = ag.definitions()
  kinds = ag.kinds(found)
  assert sorted(name for group in kinds.values() for name in group) == sorted(found)   # every agent, once
  with pytest.raises(SystemExit, match="file-review.*agent sub agents"): ag.definition("nonesuch", found)   # names the agents, and where the kinds are

  put(ledger, ".agents/learned.md", ".agents/learned/traps.md", ".agents/context.md", text="---\nname: x\nkind: learned\n---\n\nx\n")
  put(ledger, "README.md", "mod.py")
  subprocess.run(["git", "add", "-A"], cwd=ledger, check=True)   # discovery reads what git tracks
  relative = lambda plans: {name: sorted(path.relative_to(ledger).as_posix() for path in selected) for name, selected in plans}
  assert relative(review.plan(kinds["refine"], found, [], review.discover(ledger, [], 200_000), {})) == {"refine": [".agents/context.md", "README.md"], "refine.learned": [".agents/learned.md", ".agents/learned/traps.md"]}
  assert review.variant("refine", "default", kinds) == "refine"
  assert review.variant("refine", "learned", kinds) == "refine.learned"
  with pytest.raises(ValueError, match="default, learned"): review.variant("refine", "todo", kinds)
  with pytest.raises(ValueError, match="no 'x' variant$"): review.variant("logic", "x", kinds)   # file-review is of the kind, not a variant

  folder = tmp_path / "agents"
  put(folder, "named.md", text="---\nname: named\nmodel: code-large\n---\n")
  put(folder, "unnamed.md", text="---\nname: unnamed\n---\n")
  put(folder, "config.toml", text='[review]\nmodel = "code"\n')
  monkeypatch.setattr(profile, "CONFIG", folder / "config.toml")
  assert {name: definition.get("model") for name, definition in ag.definitions(folder).items()} == {"named": "code-large", "unnamed": "code"}   # the default is configuration, not code

  monkeypatch.undo()
  every = {definition.get("model") for definition in found.values()}
  for backend in backends.load_backends()[0].values(): assert every <= set(backend.spec["models"]), (backend.name, every - set(backend.spec["models"]))


def test_an_agent_sends_only_the_standards_that_govern_the_file_resolved_as_inject_does(tmp_path, monkeypatch):
  """A reviewer gets the standards for this file, including those a repo's [applies] and a profile add."""
  standard(tmp_path / "standards", "python", applies="*.py", body="PYTHON RULES")
  standard(tmp_path / "standards", "markdown", applies="*.md", body="MARKDOWN RULES")
  library, document = Library(tmp_path / "standards"), parse("---\nname: a\nstandards: python, markdown\n---\n\nbody")
  said = ag.instructions(document, library, "notes.md")
  assert "MARKDOWN RULES" in said and "PYTHON RULES" not in said
  said = ag.instructions(document, library, "mod.py")
  assert "PYTHON RULES" in said and "MARKDOWN RULES" not in said
  assert "PYTHON RULES" in ag.instructions(document, library, "logo.png")   # nothing matched: send them all

  standard(tmp_path / "mine" / "standards", "runs", applies="train_*.py", body="RUN-RULE nothing launches unreviewed")
  put(tmp_path / "mine", "agents/file-review.md", text="---\nname: file-review\nkind: logic\nstandards: python, runs\n---\nReview it.\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(tmp_path / "mine"))
  (note(git(tmp_path / "repo"), "x") / "agents.toml").write_text('[applies]\nruns = ["eval.py"]\n')
  source, = put(tmp_path / "repo", "eval.py")
  document = ag.definition("file-review", ag.definitions())
  assert "RUN-RULE" not in ag.instructions(document, Library(), source)
  assert "RUN-RULE" in ag.instructions(document, review.library(source, {}), source)
