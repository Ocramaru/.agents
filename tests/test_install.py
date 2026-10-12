"""The installer and the global git hooks, run against a throwaway HOME and a throwaway git config.

Author: Marco Cassar (@Ocramaru)
"""

import json, subprocess
from pathlib import Path

import pytest
from conftest import git, note

from agentkit import hooks, install


@pytest.fixture
def home(tmp_path, monkeypatch):
  (tmp_path / "home" / ".claude").mkdir(parents=True)
  monkeypatch.setenv("HOME", str(tmp_path / "home"))
  monkeypatch.setenv("AGENTS_HOOK_LOG", str(tmp_path / "home" / ".agents" / ".hooks.log"))   # where this HOME's hooks log
  monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
  return tmp_path / "home"


def commit(repo: Path, blocked: bool = False) -> list[str]:
  """Commit one more line through our hooks directory, and return what the hooks have written to `marks` so far."""
  with (repo / "f.txt").open("a") as handle: handle.write("another line\n")
  subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
  result = subprocess.run(["git", "-c", f"core.hooksPath={install.GITHOOKS}", "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "c"], cwd=repo, capture_output=True, check=False, text=True)
  assert (result.returncode != 0) == blocked, result.stderr
  return (repo.parent / "marks").read_text().split() if (repo.parent / "marks").exists() else []


def own_hook(repo: Path, name: str, body: str) -> None:
  (repo / ".git" / "hooks" / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
  (repo / ".git" / "hooks" / name).chmod(0o755)


def test_install_wires_claude_once_and_leaves_the_rest_alone(home):
  """Install refuses before writing when ~/.agents is someone else's, keeps other settings and every backup, leaves an unreadable settings file as written, and a second run changes nothing."""
  (home / ".agents").mkdir()
  code, lines = install.run([])
  assert code == 1 and "something else" in lines[0]
  assert not (home / ".local" / "bin" / "agent").exists()   # nothing was written
  (home / ".agents").rmdir()

  settings = home / ".claude" / "settings.json"
  settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
  settings.with_name("settings.json.bak").write_text("older")
  code, lines = install.run([])
  assert code == 0, lines
  assert json.loads(settings.read_text())["permissions"] == {"allow": ["Bash(ls)"]}   # untouched
  assert "PreToolUse" in json.loads(settings.read_text())["hooks"]
  assert sorted(saved.read_text() for saved in settings.parent.glob("settings.json.bak*")) == ["older", '{"permissions": {"allow": ["Bash(ls)"]}}']
  assert (home / ".agents").resolve() == install.HUB   # linked, since it was missing
  assert (home / ".local" / "bin" / "agent").resolve() == install.HUB / "bin" / "agent"
  assert (home / ".claude" / "CLAUDE.md").read_text().count("AGENTS.md") == 1

  code, lines = install.run([])
  changes = [line for line in lines if line.startswith(" ") and line.strip().partition(" ")[0] not in ("ok", "note")]
  assert code == 0 and changes == [], changes

  for text in ("{not json", "[1, 2]"):
    settings.write_text(text)
    assert install.hooks(settings)[0].startswith("skip  hooks block") and settings.read_text() == text


def test_the_global_hook_turns_on_and_off_but_never_replaces_someone_elses(home):
  """Install and uninstall set and unset core.hooksPath idempotently, and neither touches a path that is not ours."""
  assert install.global_install()[0] == 0
  assert Path(install.global_hooks_path()).resolve() == install.GITHOOKS.resolve()
  assert install.global_install()[1].startswith("ok")   # idempotent
  assert install.global_uninstall()[0] == 0 and install.global_hooks_path() == ""

  subprocess.run(["git", "config", "--global", "core.hooksPath", "/somewhere/else"], check=True)
  code, message = install.global_install()
  assert code == 1 and "Not replacing" in message
  assert install.global_hooks_path() == "/somewhere/else"


def test_a_commit_runs_the_repos_own_hook_first_and_is_reviewed_only_where_a_note_says_so(home, tmp_path):
  """The repo's own hook runs first and a failing pre-commit blocks; no review without a note, and ours never twice."""
  (home / ".agents" / "hooks").mkdir(parents=True)
  (home / ".agents" / "hooks" / "post-commit.sh").write_text(f"#!/usr/bin/env bash\necho reviewed >> {tmp_path}/marks\n")   # where the real review would start, so no model is called
  (home / ".agents" / "hooks" / "post-commit.sh").chmod(0o755)
  (home / ".agents" / "hooks" / "log.sh").symlink_to(install.HUB / "hooks" / "log.sh")   # the real logger, into this HOME
  repo = git(tmp_path / "repo")

  assert commit(repo) == []
  (repo / ".agents" / ".reviews").mkdir(parents=True)   # what one review leaves behind, and not a note
  assert commit(repo) == []

  note(repo, "# r")
  assert commit(repo) == ["reviewed"]
  logged = [row[1:4] for row in hooks.entries(log=home / ".agents" / ".hooks.log", verbose=True)]
  assert logged == [["post-commit", "git", "skip"], ["post-commit", "git", "skip"], ["post-commit", "git", "review"]]

  own_hook(repo, "post-commit", f"echo own >> {tmp_path}/marks")
  assert commit(repo) == ["reviewed", "own", "reviewed"]
  own_hook(repo, "post-commit", f"# installed by `agent hook install`\necho duplicate >> {tmp_path}/marks")
  assert commit(repo) == ["reviewed", "own", "reviewed", "reviewed"]

  own_hook(repo, "pre-commit", f"echo blocked >> {tmp_path}/marks\nexit 1")
  assert commit(repo, blocked=True) == ["reviewed", "own", "reviewed", "reviewed", "blocked"]   # theirs ran; ours never got a commit to see
