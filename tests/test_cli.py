"""The CLI run as a subprocess from the positions someone stands in; the failed-review display runs in-process.

Author: Marco Cassar (@Ocramaru)
"""

import contextlib, io, json, uuid

import pytest
from conftest import agent, git, note

from agentkit import agents, cli, review


@pytest.fixture
def project(tmp_path):
  """A repo with notes at the root and in a package, one of them split."""
  note(git(tmp_path), "# root\n\n## A\n\nx\n\n## B\n\ny")
  note(tmp_path / "src" / "pkg", "# pkg\n\nassumptions")
  (tmp_path / "src" / "pkg" / "mod.py").write_text("x = 1\n")
  # no frontmatter and a long heading: the shape a real note had
  (tmp_path / "src" / "pkg" / ".agents" / "learned.md").write_text("# What we learned\n\npreamble\n\n## Measurement traps, each of which cost a run\n\na\n\n## Open\n\nb\n")
  agent(["split", "src/pkg/.agents/learned.md"], cwd=tmp_path)
  return tmp_path


@pytest.mark.parametrize("where", ["", "src/pkg", ".agents", "src/pkg/.agents/learned"])
def test_remap_settles_and_manifest_parses_from_every_kind_of_directory(project, where):
  """Remap finds the notes and settles in one pass, and manifest is valid JSON, wherever it runs."""
  assert {"current", "remapped"} & set(agent(["remap"], cwd=project / where).stdout.split())
  assert "remapped" not in agent(["remap"], cwd=project / where).stdout
  assert json.loads(agent(["manifest"], cwd=project / where).stdout)["schema"] == "agents-hub/1"


def test_notes_commands_resolve_from_where_you_stand_and_say_what_they_found(project):
  """Context, inject, standards, manifest, split and init take a path relative to the working directory and report made from found."""
  package, session = project / "src" / "pkg", uuid.uuid4().hex
  data = json.loads(agent(["manifest", "--notes", str(project)], cwd=project).stdout)
  assert len(data["notes"]) == 2 and not any(entry["hub"] for entry in data["notes"])
  assert json.loads(agent(["manifest", "--notes", ""], cwd=project).stdout)["kind"] == "notes"   # an empty root is a root

  for directory, target in ((project, "src/pkg/mod.py"), (package, "mod.py")):
    assert "assumptions" in agent(["context", target], cwd=directory).stdout
    assert "assumptions" in agent(["inject", target, "--session", uuid.uuid4().hex], cwd=directory).stdout
  standards = agent(["standards", "mod.py"], cwd=package).stdout
  assert "python" in standards and "commits" in standards
  (project / ".agents" / "standards").mkdir()
  (project / ".agents" / "standards" / "bracketed.md").write_text("---\nname: bracketed\napplies: *.zz\ndescription: see [context] first\n---\n\nx\n")
  assert "see [context] first" in agent(["standards", "thing.zz"], cwd=project).stdout   # a description is not markup

  bare = git(project / "bare")
  (bare / "data.json").write_text("{}")
  assert agent(["inject", "data.json", "--session", session], cwd=bare, expect=3).stdout == ""   # exit 3: nothing governs it
  assert agent(["inject", "src/pkg/mod.py", "--session", session], cwd=project).stdout.strip()
  assert agent(["inject", "src/pkg/mod.py", "--session", session], cwd=project, expect=1).stdout == ""   # exit 1: already sent
  unstamped = [agent(["inject", "src/pkg/mod.py"], cwd=project).stdout for _ in range(2)]
  assert unstamped[0] == unstamped[1] != ""   # without --session nothing is stamped
  assert "--- python" in agent(["inject", str(package / "mod.py"), "--edit"], cwd=project, stdin="not json").stdout   # a malformed hook payload still gets the standards
  assert "--- python" in agent(["inject", str(package / "mod.py"), "--edit"], cwd=project, stdin="é", env={"PYTHONIOENCODING": "ascii"}).stdout   # and so does one that is not text

  index = (package / ".agents" / "learned.md").read_text()
  assert not index.startswith("---") and "preamble" in index
  assert [part.name for part in sorted((package / ".agents" / "learned").glob("*.md"))] == ["01-measurement-traps-each-of-which.md", "02-open.md"]
  context = agent(["context", "src/pkg/mod.py"], cwd=project).stdout
  assert "01-measurement-traps-each-of-which.md" in context and "Measurement traps, each of which cost a run" in context

  fresh = git(project / "fresh")
  first = agent(["init"], cwd=fresh).stdout
  assert first.startswith("created") and "added    README.md" in first and "added    context.md" in first
  (fresh / ".agents" / "README.md").unlink()
  again = agent(["init"], cwd=fresh).stdout
  assert again.startswith("found") and "added    README.md" in again and "context.md" not in again


def test_bad_input_is_a_message_not_a_traceback_and_a_local_agentkit_never_shadows_the_real_one(project, tmp_path_factory):
  """Input the CLI cannot act on is reported without a traceback, in a repo or outside one, and an `agentkit/` in the cwd is never imported in its place."""
  outside = tmp_path_factory.mktemp("not-a-repo")
  (outside / "agentkit").mkdir()
  for name, text in (("__init__.py", ""), ("__main__.py", "print('DECOY')\n")): (outside / "agentkit" / name).write_text(text)
  help_text = agent(["--help"], cwd=outside).stdout
  assert "DECOY" not in help_text and "doctor" in help_text and "friction" in help_text   # issue is findable by its use
  assert agent(["remap"], cwd=outside, expect=1).stderr.strip()
  assert "Traceback" not in agent(["context", "nope.py"], cwd=outside, expect=1).stderr
  assert "git diff failed" in agent(["sub", "run", "doc-check", "--changed"], cwd=outside, expect=1).stderr

  assert "no such file: nonesuch.py" in agent(["sub", "run", "doc-check", "src/pkg/mod.py", "nonesuch.py"], cwd=project, expect=2).stderr
  for command in (["sub", "run", "no-such-agent"], ["sub", "review", "not-an-agent-or-file", "--dry-run"]):
    stderr = agent(command, cwd=project, expect=1).stderr
    assert "Traceback" not in stderr and "no agent or kind called" in stderr and "file-review" in stderr
  assert "needs a --reason" in agent(["sub", "close", "src/pkg/mod.py:1", "--as", "wrong"], cwd=project, expect=2).stderr

  readme = project / "README.md"
  readme.write_text("# R\n\n## A\n\nx\n\n## B\n\ny\n")
  assert "is not a note" in agent(["remap", str(readme)], cwd=project, expect=1).stderr
  assert "no such path" in agent(["remap", "typo.md"], cwd=project, expect=1).stderr   # not the notes above it
  assert "map:" not in readme.read_text()

  (project / "claude").mkdir()
  (project / "claude" / "settings.json").write_text('{"hooks": {},}')
  doctor = agent(["doctor"], cwd=project, expect=None, env={"CLAUDE_CONFIG_DIR": str(project / "claude")})
  assert "Traceback" not in doctor.stderr and "not valid JSON" in doctor.stdout

  assert "the note to split" in agent(["split"], cwd=project, expect=2).stderr   # no arguments: the whole help
  assert "positional arguments" not in agent(["sub", "close", "x", "--as", "nope"], cwd=project, expect=2).stderr   # a bad value: usage only


def test_a_flag_reaches_its_command_wherever_it_sits_and_a_review_is_found_by_file_or_kind(project):
  """A path after a flag still reaches review, an undefined flag is not swallowed, --tail is one name, and `sub` lists every kind."""
  for arguments, wanted, unwanted in [
    (["doc-check", "nope.py"], "no such path: nope.py", "nothing matched"),
    (["doc-check", "--backend", "ollama", "nope.py"], "no such path: nope.py", "unrecognized"),
    (["doc-check", "--bogus", "nope.py"], "unrecognized arguments: --bogus", "no such path")]:
    stderr = agent(["sub", "review", *arguments], cwd=project, expect=2).stderr
    assert wanted in stderr and unwanted not in stderr, arguments
  for arguments in (["hooks", "--tail", "3"], ["sub", "reviews", "--tail", "3"]):
    assert "unrecognized" not in agent(arguments, cwd=project, expect=None).stderr

  by_file = agent(["sub", "review", "src/pkg/mod.py", "--dry-run"], cwd=project).stdout
  assert "file-review" in by_file and "mod.py" in by_file
  by_kind = agent(["sub", "review", "logic", "src/pkg/mod.py", "--dry-run"], cwd=project).stdout
  assert "logic review · file-review" in by_kind and "doc-check" not in by_kind
  for arguments in (["sub"], ["sub", "--list"], ["sub", "agents"]):
    rows = [line.split("\t") for line in agent(arguments, cwd=project).stdout.strip().splitlines()]
    assert rows and {row[0] for row in rows} == set(agents.kinds(agents.definitions())), arguments   # whatever is installed, profile or not
    assert all(len(row) == 5 and "[" not in row[2] for row in rows)   # piped output carries no markup


def test_a_failed_review_says_why_and_is_not_offered_a_reply(project, monkeypatch):
  """A failed review prints its error by the file, and only a review with findings is offered a recheck."""
  def fake_run(name, backend, paths, root, definition, libraries, on_start=None, on_done=None, **_):
    if name == "file-review": result = {"file": "a.py", "agent": name, "task": "t-failed", "state": "failed", "kind": "note", "body": "TimeoutExpired: took longer than 300s", "findings": []}
    else: result = {"file": "a.py", "agent": name, "task": "t-found", "state": "completed", "kind": "findings", "body": "One stale comment.", "findings": [{"line": 1, "issue": "stale", "fix": "update", "file": "a.py"}]}
    on_start("a.py")
    on_done(result)
    return [result]
  monkeypatch.setattr(review, "run", fake_run)
  monkeypatch.chdir(project)
  (project / "a.py").write_text("x = 1\n")

  stdout = io.StringIO()
  stderr = io.StringIO()
  with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout): cli.main(["sub", "review", "auto", "a.py", "--keep"])
  assert "Traceback" not in stderr.getvalue()
  shown = stdout.getvalue()
  assert "a.py" in shown and "failed" in shown and "error: TimeoutExpired" in shown   # why, by the file
  assert "One stale comment." in shown   # the verdict, too
  assert shown.count("agent sub review --recheck a.py") == 1 and "agent sub reply" not in shown   # found, not failed


def test_the_commit_hook_installs_beside_any_hook_and_quotes_its_arguments(project):
  """Install moves a foreign hook aside without clobbering an older backup, uninstall removes only ours, and arguments are shell-quoted."""
  hook = project / ".git" / "hooks" / "post-commit"
  hook.parent.mkdir(parents=True, exist_ok=True)
  hook.write_text("echo mine\n")
  hook.with_name("post-commit.bak").write_text("echo older\n")

  assert "not ours" in agent(["hook", "uninstall"], cwd=project, expect=1).stderr
  assert hook.read_text() == "echo mine\n"
  agent(["hook", "status"], cwd=project, expect=1)
  assert "moved the hook already there aside" in agent(["hook", "install"], cwd=project).stdout
  assert sorted(saved.read_text() for saved in hook.parent.glob("post-commit.bak*")) == ["echo mine\n", "echo older\n"]   # never eaten
  agent(["hook", "status"], cwd=project)
  assert "removed" in agent(["hook", "uninstall"], cwd=project).stdout
  assert not hook.exists()

  agent(["hook", "install", "--agent", "a b; echo hi"], cwd=project)
  assert "'a b; echo hi'" in hook.read_text()
