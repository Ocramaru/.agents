"""A profile holds your own standards, reviewers and config apart from the public .agents, which reads them.

`local.toml`, the default profile path and git's global config are all pointed at temporary ones.

Author: Marco Cassar (@Ocramaru)
"""

import argparse
import subprocess
import tomllib
from pathlib import Path

import pytest

from agentkit import agents, backends, cli, install, profile
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
  (mine / "config.toml").write_text('[review]\nexclude = ["**/data/**"]\njobs = 2\n[backends]\ndefault = "ollama"\n[backends.claude]\nkind = "cli"\nargv = ["claude"]\nmodels = { text = "my-model" }\n')
  monkeypatch.setattr(profile, "CONFIG", hub / "config.toml")
  known, default = backends.load_backends()
  assert default == "ollama" and set(known) == {"claude", "ollama"}
  assert known["claude"].spec["models"]["text"] == "my-model"

  config = profile.section("review", add=("exclude",))
  assert config["exclude"] == ["**/vendor/**", "**/data/**"] and config["jobs"] == 2


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

  for start in ("my notes", f"my notes\n\n@{install.HUB}/AGENTS.md"):
    claude.write_text(start)
    assert "your profile" in install.point_at(claude)[0]
    text = claude.read_text()
    assert text.startswith(start) and text.endswith(f"@{install.HUB}/AGENTS.md\n@{first}/AGENTS.md\n")
    assert install.point_at(claude)[0].startswith("ok") and claude.read_text() == text

  monkeypatch.setenv("AGENTS_PROFILE", str(second))
  assert install.repoint(first / "AGENTS.md") == ["point .claude/CLAUDE.md at " + install.home(second / "AGENTS.md")]
  assert claude.read_text() == text.replace(f"@{first}/", f"@{second}/")


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

  monkeypatch.setattr(profile, "HUB", published(isolated, "hub")[1])
  profile.git(clone, "push", "-q")
  assert cli.setup.cmd_update(argparse.Namespace()) == 0
  assert profile.git(profile.DEFAULT, "log", "-1", "--format=%s").stdout == "second\n"

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
