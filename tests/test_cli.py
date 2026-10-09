"""Every command, invoked as a subprocess, from every position someone might stand in.

The unit tests call functions directly from one working directory, which is exactly the blind
spot that shipped `agent remap` broken from inside a `.agents` and `agent remap .agents` as a
silent no-op. A command is only correct if it is correct from where it will actually be run.

Run with `env -u PYTHONPATH uv run pytest tests/`.

Author: Marco Cassar (@Ocramaru)
"""

import contextlib
import io
import json

import pytest
from conftest import agent, git

from agentkit import agents, cli, review


@pytest.fixture
def project(tmp_path):
  """A repo shaped like a real one: notes at the root, notes in a package, one of them split."""
  git(tmp_path)
  root = tmp_path / ".agents"
  root.mkdir()
  (root / "context.md").write_text("---\nname: context\nkind: context\n---\n\n# root\n\n## A\n\nx\n\n## B\n\ny\n")
  (root / "todo.md").write_text("---\nname: todo\nkind: todo\n---\n\n# TODO\n\n## Next\n\n- [ ] a\n")

  pkg = tmp_path / "src" / "pkg"
  pkg.mkdir(parents=True)
  (pkg / "mod.py").write_text("x = 1\n")
  sub = pkg / ".agents"
  sub.mkdir()
  (sub / "context.md").write_text("---\nname: context\nkind: context\n---\n\n# pkg\n\nassumptions\n")
  # a note with no frontmatter and a long heading, which is what a real one looked like
  (sub / "learned.md").write_text(
    "# What we learned\n\npreamble\n\n## Measurement traps, each of which cost a run\n\na\n\n## Open\n\nb\n")
  agent(["split", str(sub / "learned.md")], cwd=tmp_path)
  return tmp_path


WHERE = {
  "repo root": lambda p: p,
  "package dir": lambda p: p / "src" / "pkg",
  "inside .agents": lambda p: p / ".agents",
  "inside a split note": lambda p: p / "src" / "pkg" / ".agents" / "learned",
}


def test_remap_and_manifest_work_from_every_kind_of_directory(project):
  """Remap finds the notes and settles in one pass, and manifest is valid JSON, wherever it is run."""
  for name, at in WHERE.items():
    out = agent(["remap"], cwd=at(project)).stdout
    assert "current" in out or "remapped" in out, f"remap found nothing from {name}"
    assert "remapped" not in agent(["remap"], cwd=at(project)).stdout, name
    assert json.loads(agent(["manifest"], cwd=at(project)).stdout)["schema"] == "agents-hub/1", name
  data = json.loads(agent(["manifest", "--notes", str(project)], cwd=project).stdout)
  assert len(data["notes"]) == 2 and not any(n["hub"] for n in data["notes"])


def test_a_relative_path_resolves_from_where_you_stand(project):
  """context, inject and standards take a path relative to the working directory."""
  for cwd, target in ((project, "src/pkg/mod.py"), (project / "src" / "pkg", "mod.py")):
    assert "assumptions" in agent(["context", target], cwd=cwd).stdout
    assert "assumptions" in agent(["inject", target, "--session", f"s-{cwd.name}"], cwd=cwd).stdout
  out = agent(["standards", "mod.py"], cwd=project / "src" / "pkg").stdout
  assert "python" in out and "commits" in out


def test_inject_tells_already_sent_from_never_governed(project, tmp_path_factory):
  """Exit 1 is already sent, 3 is nothing governs it; without --session nothing is stamped."""
  bare = git(tmp_path_factory.mktemp("bare"))
  (bare / "data.json").write_text("{}")
  assert agent(["inject", "data.json", "--session", "gov"], cwd=bare, expect=3).stdout == ""

  assert agent(["inject", "src/pkg/mod.py", "--session", "gov"], cwd=project).stdout.strip()
  assert agent(["inject", "src/pkg/mod.py", "--session", "gov"], cwd=project, expect=1).stdout == ""
  by_hand = [agent(["inject", "src/pkg/mod.py"], cwd=project).stdout for _ in range(2)]
  assert by_hand[0] == by_hand[1] != ""

  out = agent(["inject", str(project / "src" / "pkg" / "mod.py"), "--edit"], cwd=project, stdin="not json").stdout
  assert "--- python" in out                        # a malformed hook payload still gets the standards


def test_split_kept_the_note_it_was_given_and_advertises_its_parts(project):
  """Split invents no frontmatter, loses no preamble, numbers parts in order, and context names them."""
  index = (project / "src" / "pkg" / ".agents" / "learned.md").read_text()
  assert not index.startswith("---") and "preamble" in index
  parts = sorted((project / "src" / "pkg" / ".agents" / "learned").glob("*.md"))
  assert [p.name for p in parts] == ["01-measurement-traps-each-of-which.md", "02-open.md"]

  out = agent(["context", "src/pkg/mod.py"], cwd=project).stdout
  assert "01-measurement-traps-each-of-which.md" in out
  assert "Measurement traps, each of which cost a run" in out


def test_outside_a_repo_agent_fails_cleanly_and_runs_its_own_agentkit(tmp_path):
  """With no repo it says so without a traceback, and an `agentkit/` in the cwd never shadows its own."""
  decoy = tmp_path / "agentkit"
  decoy.mkdir()
  (decoy / "__init__.py").write_text("")
  (decoy / "__main__.py").write_text("print('DECOY')\n")
  out = agent(["--help"], cwd=tmp_path).stdout
  assert "DECOY" not in out and "doctor" in out and "friction" in out   # issue is findable by its use
  assert agent(["remap"], cwd=tmp_path, expect=1).stderr.strip()
  assert "Traceback" not in agent(["context", "nope.py"], cwd=tmp_path, expect=1).stderr


def test_bad_input_is_reported_not_raised(project, tmp_path):
  """An unknown name, a missing reason, a non-note or an unparseable settings file each get a message."""
  for args in (["sub", "run", "no-such-agent"], ["sub", "review", "not-an-agent-or-file", "--dry-run"]):
    err = agent(args, cwd=project, expect=1).stderr
    assert "Traceback" not in err and "no agent or kind called" in err and "file-review" in err
  assert "Traceback" not in agent(["sub", "backends", "--help"], cwd=project).stdout
  assert "needs a --reason" in agent(["sub", "close", "src/pkg/mod.py:1", "--as", "wrong"], cwd=project, expect=2).stderr

  readme = project / "README.md"
  readme.write_text("# R\n\n## A\n\nx\n\n## B\n\ny\n")
  assert "is not a note" in agent(["remap", str(readme)], cwd=project, expect=1).stderr
  assert "no such path" in agent(["remap", "typo.md"], cwd=project, expect=1).stderr   # not the notes above it
  assert "map:" not in readme.read_text()

  cfg = tmp_path / "claude"
  cfg.mkdir()
  (cfg / "settings.json").write_text('{"hooks": {},}')
  out = agent(["doctor"], cwd=project, expect=None, env={"CLAUDE_CONFIG_DIR": str(cfg)})
  assert "Traceback" not in out.stderr and "not valid JSON" in out.stdout


def test_a_command_missing_what_it_needs_shows_its_help_and_init_says_what_it_found(project, tmp_path):
  """Without its arguments a command prints its whole help; a bad value gets usage only. init tells made from found."""
  err = agent(["split"], cwd=project, expect=2).stderr
  assert "positional arguments" in err and "the note to split" in err
  assert "positional arguments" not in agent(["sub", "close", "x", "--as", "nope"], cwd=project, expect=2).stderr

  d = git(tmp_path / "fresh")
  first = agent(["init"], cwd=d).stdout
  assert first.startswith("created") and "added    README.md" in first and "added    context.md" in first
  (d / ".agents" / "README.md").unlink()
  again = agent(["init"], cwd=d).stdout
  assert again.startswith("found") and "added    README.md" in again and "context.md" not in again
  assert agent(["standards", "nothing.xyz"], cwd=d, expect=1).stderr.startswith("no standard governs")


def test_a_flag_reaches_its_command_wherever_it_sits(project):
  """A path after a flag still reaches review, an undefined flag is not swallowed, and --tail is one name."""
  for args, want, unwanted in [
    (["doc-check", "nope.py"], "no such path: nope.py", "nothing matched"),
    (["doc-check", "--backend", "ollama", "nope.py"], "no such path: nope.py", "unrecognized"),
    (["doc-check", "--bogus", "nope.py"], "unrecognized arguments: --bogus", "no such path")]:
    err = agent(["sub", "review", *args], cwd=project, expect=2).stderr
    assert want in err and unwanted not in err, args
  for args in (["hooks", "--tail", "3"], ["sub", "reviews", "--tail", "3"]):
    assert "unrecognized" not in agent(args, cwd=project, expect=None).stderr


def test_a_review_is_found_by_file_by_kind_or_by_listing(project):
  """A bare file routes to its reviewer, a kind narrows to it, and `sub` lists every kind."""
  out = agent(["sub", "review", "src/pkg/mod.py", "--dry-run"], cwd=project).stdout
  assert "file-review" in out and "mod.py" in out
  out = agent(["sub", "review", "logic", "src/pkg/mod.py", "--dry-run"], cwd=project).stdout
  assert "logic review · file-review" in out and "doc-check" not in out

  for args in (["sub"], ["sub", "--list"], ["sub", "agents"]):
    rows = [line.split("\t") for line in agent(args, cwd=project).stdout.strip().splitlines()]
    assert {r[0] for r in rows} == set(agents.kinds(agents.definitions())), args   # whatever is installed, profile or not
    assert all(len(r) == 5 and "[" not in r[2] for r in rows)   # piped output carries no markup


def test_a_failed_review_says_why_and_is_not_offered_a_reply(project, monkeypatch):
  """A failed review prints its error by the file, and only a review with findings is offered a recheck."""
  def fake_run(name, backend, paths, root, definition, libraries, tier="text", jobs=4, on_start=None, on_done=None, run=None, **_):
    if name == "file-review":
      r = {"file": "a.py", "agent": name, "task": "t-failed", "state": "failed", "kind": "note",
           "body": "TimeoutExpired: took longer than 300s", "findings": []}
    else:
      r = {"file": "a.py", "agent": name, "task": "t-found", "state": "completed", "kind": "findings",
           "body": "One stale comment.", "findings": [{"line": 1, "issue": "stale", "fix": "update", "file": "a.py"}]}
    on_start("a.py")
    on_done(r)
    return [r]
  monkeypatch.setattr(review, "run", fake_run)
  monkeypatch.chdir(project)
  (project / "a.py").write_text("x = 1\n")
  out, err = io.StringIO(), io.StringIO()
  with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
    cli.main(["sub", "review", "auto", "a.py", "--keep"])
  shown = out.getvalue()
  assert "a.py" in shown and "failed" in shown and "error: TimeoutExpired" in shown   # why, by the file
  assert "One stale comment." in shown                                               # the verdict, too
  assert shown.count("agent sub review --recheck a.py") == 1 and "agent sub reply" not in shown   # found, not failed


def test_the_commit_hook_installs_beside_any_hook_and_quotes_its_arguments(project):
  """Install moves a foreign hook aside, uninstall removes only ours, and arguments are shell-quoted."""
  hook = project / ".git" / "hooks" / "post-commit"
  hook.parent.mkdir(parents=True, exist_ok=True)
  hook.write_text("echo mine\n")
  assert "not ours" in agent(["hook", "uninstall"], cwd=project, expect=1).stderr
  assert hook.read_text() == "echo mine\n"
  agent(["hook", "status"], cwd=project, expect=1)
  assert "moved the hook already there aside" in agent(["hook", "install"], cwd=project).stdout
  assert hook.with_name("post-commit.bak").read_text() == "echo mine\n"   # never eaten
  agent(["hook", "status"], cwd=project)
  assert "removed" in agent(["hook", "uninstall"], cwd=project).stdout
  assert not hook.exists()

  agent(["hook", "install", "--agent", "a b; echo hi"], cwd=project)
  assert "'a b; echo hi'" in hook.read_text()
