"""A profile holds your own standards, reviewers and config apart from the public .agents, which reads them.

`local.toml`, the default profile path and git's global config are all pointed at temporary ones.

Author: Marco Cassar (@Ocramaru)
"""

import argparse
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import agent

from agentkit import agents, backends, cli, doctor, install, profile
from agentkit.standards import Library


@pytest.fixture
def isolated(tmp_path, monkeypatch):
  """Every path the profile code writes to, moved somewhere it can do no harm."""
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")
  monkeypatch.setattr(profile, "DEFAULT", tmp_path / "hub" / "profile")
  monkeypatch.delenv("AGENTS_PROFILE", raising=False)
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
  (tmp_path / "gitconfig").write_text("[user]\n  name = T\n  email = t@t.io\n[pull]\n  rebase = false\n")   # an identity, merging pulls, and no hooksPath so no review runs
  return tmp_path


def commit(repository: Path, message: str) -> None:
  """An empty commit: history is all these tests need."""
  profile.git(repository, "commit", "--allow-empty", "-qm", message)


def published(parent: Path, name: str) -> tuple[Path, Path]:
  """A bare remote and a clone of it with one commit pushed: what a profile on GitHub looks like."""
  bare, clone = parent / f"{name}.git", parent / name
  profile.git(parent, "init", "-q", "--bare", "-b", "main", str(bare))
  profile.git(parent, "clone", "-q", str(bare), str(clone))
  commit(clone, "first")
  profile.git(clone, "push", "-q", "-u", "origin", "main")
  return bare, clone


def test_the_profile_is_found_from_the_environment_then_local_toml_then_the_default(isolated, monkeypatch):
  """The environment wins over local.toml, which wins over the default; empty means none, and a broken local.toml is none."""
  profile.LOCAL.write_text("[profile\npath = ")
  assert profile.path() is None
  for wrong in ('profile = "/saved"\n', "[profile]\npath = 3\n"):   # parses, but is not a [profile] table with a path
    profile.LOCAL.write_text(wrong)
    assert profile.chosen() is None and profile.path() is None

  profile.DEFAULT.mkdir(parents=True)
  assert profile.path() == profile.DEFAULT

  profile.LOCAL.write_text('[profile]\npath = "/saved"\n')
  assert profile.path() == Path("/saved")

  for value, expected in ((str(isolated / "env"), isolated / "env"), ("", None)):
    monkeypatch.setenv("AGENTS_PROFILE", value)
    assert profile.path() == expected


@pytest.mark.parametrize("before", ['# mine\n[profile]\npath = "/old"\nnote = "keep"\n\n[mine]\nkept = true\n', '[profile]  # mine\n  path = "/old"\nnote = "keep"\n', '[mine]\nkept = true\n', ""])
def test_saving_rewrites_only_the_path(isolated, before):
  """Save changes the `path` line and keeps the file's other tables, keys and comments, whatever characters the path holds."""
  if before: profile.LOCAL.write_text(before)
  saved = isolated / 'odd "quoted" \\ dir'
  saved.mkdir()
  profile.save(saved)

  expected = {**(old := tomllib.loads(before)), "profile": {**old.get("profile", {}), "path": str(saved.resolve())}}
  text = profile.LOCAL.read_text()
  assert tomllib.loads(text) == expected
  assert text.startswith(before.split("path")[0].rstrip(" "))


def test_a_profile_replaces_the_hubs_standards_reviewers_and_backends_by_name_and_layers_its_config(isolated, monkeypatch):
  """A profile's standard, reviewer and backend replace the hub's of the same name, its own are added, and its config sits between the hub's and the repo's."""
  hub, mine, repo = isolated / "hub", isolated / "mine", isolated / "repo"
  for directory, name, body in ((hub, "python", "STARTER"), (mine, "python", "MINE"), (repo, "python", "REPO"), (hub / "agents", "file-review", "HUB"), (mine / "agents", "file-review", "MINE"), (mine / "agents", "my-check", "MINE TOO")):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(f"---\nname: {name}\ndescription: {name}\napplies: *.py\nkind: logic\n---\n\n{body}\n")
  assert [(layer.origin, layer.doc.body.strip()) for layer in Library(hub, [repo], profile=mine).layers["python"]] == [("profile", "MINE"), ("repo", "REPO")]

  monkeypatch.setattr(agents, "AGENTS", hub / "agents")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  definitions = agents.definitions(hub / "agents")
  assert sorted(definitions) == ["file-review", "my-check"]
  assert agents.definition("file-review", definitions).body.strip() == "MINE"

  (hub / "config.toml").write_text('[review]\nexclude = ["**/vendor/**"]\njobs = 4\n[backends]\ndefault = "claude"\n[backends.claude]\nkind = "cli"\nargv = ["claude"]\nmodels = { text = "hub-model" }\n[backends.ollama]\nkind = "http"\nurl = "x"\n')
  (mine / "config.toml").write_text('[review]\nexclude = "**/data/**"\njobs = 2\n[backends]\ndefault = "ollama"\n[backends.claude]\nkind = "cli"\nargv = ["claude"]\nmodels = { text = "my-model" }\n')
  monkeypatch.setattr(profile, "CONFIG", hub / "config.toml")
  known, default = backends.load_backends()
  assert default == "ollama" and set(known) == {"claude", "ollama"}
  assert known["claude"].spec["models"]["text"] == "my-model"

  config = profile.section("review", add=("exclude",))
  assert config["exclude"] == ["**/vendor/**", "**/data/**"] and config["jobs"] == 2   # a lone string accumulates as a list of one


def test_the_pointer_to_your_profile_follows_the_hubs_and_moves_with_the_profile(isolated, monkeypatch):
  """A pointer to the profile's AGENTS.md is appended once after the hub's, and repointing swaps it for the new profile's."""
  monkeypatch.setenv("HOME", str(isolated / "home"))
  first, second = isolated / "first", isolated / "second"
  for directory in (first, second):
    directory.mkdir()
    (directory / "AGENTS.md").write_text("# how I work\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(first))
  claude = isolated / "home" / ".claude" / "CLAUDE.md"
  claude.parent.mkdir(parents=True)

  for start in ("my notes", f"my notes\n\n@{install.HOME}/AGENTS.md"):
    claude.write_text(start)
    assert "your profile" in install.point_at(claude)[0]
    text = claude.read_text()
    assert text.startswith(start) and text.endswith(f"@{install.HOME}/AGENTS.md\n@{first}/AGENTS.md\n")
    assert install.point_at(claude)[0].startswith("ok") and claude.read_text() == text

  monkeypatch.setenv("AGENTS_PROFILE", str(second))
  assert install.repoint(first / "AGENTS.md") == ["point .claude/CLAUDE.md at " + install.home(second / "AGENTS.md")]
  assert claude.read_text() == text.replace(f"@{first}/", f"@{second}/")


def test_dropping_the_profile_drops_its_pointers_whole_line(isolated, monkeypatch):
  """With no profile left, repointing removes each line that is only the old pointer, whatever whitespace surrounds it, and nothing else."""
  monkeypatch.setenv("HOME", str(isolated / "home"))
  monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
  monkeypatch.setenv("AGENTS_PROFILE", "")
  (claude := isolated / "home" / ".claude" / "CLAUDE.md").parent.mkdir(parents=True)
  claude.write_text(f"my notes\n@{install.HOME}/AGENTS.md\n  @{isolated}/old/AGENTS.md \nafter\n")
  assert install.repoint(isolated / "old" / "AGENTS.md") == ["point .claude/CLAUDE.md at no profile"]
  assert claude.read_text() == f"my notes\n@{install.HOME}/AGENTS.md\nafter\n"


def test_a_profile_is_adopted_checked_for_drift_updated_and_made(isolated, monkeypatch, capsys):
  """A directory is used in place, a remote is cloned once and never over a different one, drift names what is unpushed, update fails rather than merge, and init reports only what it made."""
  mine = isolated / "dotfiles"
  mine.mkdir()
  assert profile.adopt(str(mine))[0] == 0 and profile.path() == mine.resolve() and not profile.DEFAULT.exists()
  assert profile.adopt(str(isolated / "nowhere"))[0] == 1

  bare, clone = published(isolated, "theirs")   # a path ending .git reads as a remote, as a URL would
  code, said = profile.adopt(str(bare))
  assert code == 0 and "clone" in said and (profile.DEFAULT / ".git").is_dir()
  assert profile.path() == profile.DEFAULT.resolve()
  assert profile.adopt(str(bare))[1].startswith("ok")
  assert "already holds" in profile.adopt(str(published(isolated, "other")[0]))[1]

  commit(clone, "second")
  (clone / "voice.md").write_text("new\n")
  assert profile.drift(clone) == ["1 uncommitted change", "1 commit not pushed"]
  profile.git(clone, "update-ref", "-d", "refs/remotes/origin/main")   # an upstream set but not fetched is not no upstream
  assert profile.drift(clone) == ["1 uncommitted change", "its upstream origin/main is gone, or was never fetched"]

  monkeypatch.setattr(profile, "SHIPPED", published(isolated, "agents")[1])
  profile.git(clone, "push", "-q")
  assert cli.setup.cmd_update(argparse.Namespace()) == 0
  assert profile.git(profile.DEFAULT, "log", "-1", "--format=%s").stdout == "second\n"
  said = capsys.readouterr().out
  assert ".agents: already current" in said and "profile: pulled 1 commit  (" in said

  commit(profile.DEFAULT, "here")
  commit(clone, "there")
  profile.git(clone, "push", "-q")
  assert cli.setup.cmd_update(argparse.Namespace()) == 1
  assert "FAIL" in capsys.readouterr().out

  assert ".git" in profile.init(isolated / "new")
  assert (isolated / "new" / "standards").is_dir() and profile.init(isolated / "new") == []
  assert profile.drift(isolated / "new")[-1] == "no upstream to push to"

  monkeypatch.setattr(profile.subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1))
  assert ".git" not in profile.init(isolated / "failed")


def test_doctor_fails_a_public_profile_remote_and_profile_names_a_missing_one(isolated, monkeypatch):
  """doctor asks gh whether a profile's GitHub remote is private and fails it when public; `agent profile` says when there is no remote at all."""
  mine, fake = isolated / "mine", isolated / "fake"
  profile.git(isolated, "init", "-q", "-b", "main", str(mine))
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.chdir(isolated)
  said = agent(["profile"], cwd=isolated).stdout
  assert "no remote, so no other machine gets it" in said and "no upstream" not in said

  fake.mkdir()
  (fake / "gh").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$GH_LOG"\n[[ "$1 $2" == "repo view" ]] && { echo "$GH_PRIVATE"; exit 0; }\nexit 1\n')
  (fake / "gh").chmod(0o755)
  monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
  monkeypatch.setenv("GH_LOG", str(isolated / "gh.log"))
  profile.git(mine, "remote", "add", "origin", "git@github.com:someone/.agents.profile.git")
  assert "no remote" not in agent(["profile"], cwd=isolated).stdout
  for private in ("true", "false"):
    monkeypatch.setenv("GH_PRIVATE", private)
    assert [passed for passed, label, _ in doctor.checks() if label == "profile remote someone/.agents.profile is private"] == [private == "true"]
  assert "repo view someone/.agents.profile --json isPrivate" in (isolated / "gh.log").read_text()


def test_a_key_is_written_into_its_table_even_when_the_header_ends_the_file(tmp_path):
  """A [table] header on the last line with no newline is found and filled, never added a second time, which TOML refuses."""
  config = tmp_path / "config.toml"
  config.write_text("[review]\njobs = 2\n\n[backends]")
  profile.write(config, "backends", "default", "claude")
  assert tomllib.loads(config.read_text()) == {"review": {"jobs": 2}, "backends": {"default": "claude"}}
