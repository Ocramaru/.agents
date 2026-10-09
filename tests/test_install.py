"""The installer and the global git hooks, run against a throwaway HOME and a throwaway git config.

Nothing here touches the real ~/.claude or ~/.gitconfig: HOME is a tmp dir and GIT_CONFIG_GLOBAL
points git at a file of its own.

Author: Marco Cassar (@Ocramaru)
"""

import json
import subprocess
from pathlib import Path

import pytest
from conftest import agent

from agentkit import hooks, install

DISPATCH = install.GITHOOKS


@pytest.fixture
def home(tmp_path, monkeypatch):
  h = tmp_path / "home"
  (h / ".claude").mkdir(parents=True)
  monkeypatch.setenv("HOME", str(h))
  monkeypatch.setenv("AGENTS_HOOK_LOG", str(h / ".agents" / ".hooks.log"))   # where this HOME's hooks log
  monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
  return h


def test_install_wires_claude_once_and_leaves_the_rest_alone(home):
  """Install refuses before writing when ~/.agents is someone else's, keeps other settings, and a second run changes nothing."""
  (home / ".agents").mkdir()
  code, lines = install.run([])
  assert code == 1 and "something else" in lines[0]
  assert not (home / ".local" / "bin" / "agent").exists()             # nothing was written
  (home / ".agents").rmdir()

  (home / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
  code, lines = install.run([])
  assert code == 0, lines
  settings = json.loads((home / ".claude" / "settings.json").read_text())
  assert settings["permissions"] == {"allow": ["Bash(ls)"]}          # untouched
  assert "PreToolUse" in settings["hooks"]
  assert (home / ".agents").resolve() == install.HUB                   # linked, since it was missing
  assert (home / ".local" / "bin" / "agent").resolve() == install.HUB / "bin" / "agent"
  assert (home / ".claude" / "CLAUDE.md").read_text().count("AGENTS.md") == 1

  code, lines = install.run([])
  did = [l for l in lines if l.startswith(" ") and l.split()[0] not in ("ok", "note")]
  assert code == 0 and did == [], did


def test_a_backup_is_never_clobbered(repo):
  """Each backup takes the next free number, and `agent hook install` goes through it."""
  d = repo / "backups"
  d.mkdir()
  f = d / "x"
  for body in ("first", "second"):
    f.write_text(body)
    f.rename(install.backup(f))
  assert sorted(p.read_text() for p in d.iterdir()) == ["first", "second"]

  hooks = repo / ".git" / "hooks"
  (hooks / "post-commit").write_text("#!/bin/sh\necho first\n")
  (hooks / "post-commit.bak").write_text("#!/bin/sh\necho older\n")
  agent(["hook", "install"], cwd=repo, env={"GIT_CONFIG_GLOBAL": str(repo / "gitconfig")})
  saved = sorted(p.read_text() for p in hooks.glob("post-commit.bak*"))
  assert saved == ["#!/bin/sh\necho first\n", "#!/bin/sh\necho older\n"]


def test_the_global_hook_turns_on_and_off_but_never_replaces_someone_elses(home):
  assert install.global_install()[0] == 0
  assert Path(install.global_hooks_path()).resolve() == DISPATCH.resolve()
  assert install.global_install()[1].startswith("ok")                 # idempotent
  assert install.global_uninstall()[0] == 0 and install.global_hooks_path() == ""

  subprocess.run(["git", "config", "--global", "core.hooksPath", "/somewhere/else"], check=True)
  code, msg = install.global_install()
  assert code == 1 and "Not replacing" in msg
  assert install.global_hooks_path() == "/somewhere/else"


def commit(repo: Path) -> subprocess.CompletedProcess:
  with (repo / "f.txt").open("a") as f: f.write("another line\n")   # never an empty commit
  subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
  return subprocess.run(["git", "-c", f"core.hooksPath={DISPATCH}", "-c", "user.name=T",
                         "-c", "user.email=t@t.io", "commit", "-qm", "c"],
                        cwd=repo, capture_output=True, check=False, text=True)


@pytest.fixture
def hooked(tmp_path, home):
  """A repo, and a stub where the real review would start, so no model is ever called."""
  (home / ".agents").mkdir(exist_ok=True)
  stub = home / ".agents" / "hooks" / "post-commit.sh"
  stub.parent.mkdir(parents=True)
  stub.write_text(f"#!/usr/bin/env bash\necho reviewed >> {tmp_path}/marks\n")
  stub.chmod(0o755)
  (stub.parent / "log.sh").symlink_to(install.HUB / "hooks" / "log.sh")   # the real logger, into this HOME
  r = tmp_path / "repo"
  r.mkdir()
  subprocess.run(["git", "init", "-q"], cwd=r, check=True)
  return r


def marks(repo: Path) -> list[str]:
  f = repo.parent / "marks"
  return f.read_text().split() if f.exists() else []


def own_hook(repo: Path, name: str, body: str) -> None:
  h = repo / ".git" / "hooks" / name
  h.write_text(f"#!/usr/bin/env bash\n{body}\n")
  h.chmod(0o755)


def opt_in(repo: Path) -> None:
  """What opts a repo into commit-time review: a note, not merely a `.agents` directory."""
  (repo / ".agents").mkdir(exist_ok=True)
  (repo / ".agents" / "context.md").write_text("---\nname: context\nkind: context\n---\n\n# r\n")


def test_a_commit_is_reviewed_only_where_a_note_says_so_after_the_repos_own_hook(hooked, home):
  """No review without a note (a bare `.reviews` ledger is not one); the repo's own hook runs first, ours never twice."""
  assert commit(hooked).returncode == 0
  (hooked / ".agents" / ".reviews").mkdir(parents=True)      # exactly what one review leaves behind
  assert commit(hooked).returncode == 0
  assert marks(hooked) == []

  opt_in(hooked)
  commit(hooked)
  assert marks(hooked) == ["reviewed"]
  assert [(r[1], r[2], r[3]) for r in hooks.entries(log=home / ".agents" / ".hooks.log", verbose=True)] == [("post-commit", "git", "skip"),
                                                       ("post-commit", "git", "skip"),
                                                       ("post-commit", "git", "review")]

  own_hook(hooked, "post-commit", f"echo own >> {hooked.parent}/marks")
  commit(hooked)
  assert marks(hooked) == ["reviewed", "own", "reviewed"]

  own_hook(hooked, "post-commit", f"# installed by `agent hook install`\necho duplicate >> {hooked.parent}/marks")
  commit(hooked)
  assert marks(hooked) == ["reviewed", "own", "reviewed", "reviewed"]


def test_a_repos_failing_pre_commit_still_blocks_the_commit(hooked):
  """Their pre-commit ran, the commit did not land, and nothing was reviewed in an opted-in repo."""
  opt_in(hooked)
  own_hook(hooked, "pre-commit", f"echo blocked >> {hooked.parent}/marks\nexit 1")
  assert commit(hooked).returncode != 0
  assert marks(hooked) == ["blocked"]                    # theirs ran; ours never got a commit to see
  assert subprocess.run(["git", "rev-list", "--count", "--all"], cwd=hooked, capture_output=True,
                        check=True, text=True).stdout.strip() == "0"
