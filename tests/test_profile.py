"""A profile: your own standards, kept apart from the public .agents, which reads them.

A profile replaces a starter of the same name and adds anything else; a repo still layers on top
of whichever won. Nothing here touches the real install: `local.toml`, the default profile path,
the paths of .agents itself and git's global config are all pointed at temporary ones.

Author: Marco Cassar (@Ocramaru)
"""

import argparse
import subprocess
import tomllib
from pathlib import Path

import pytest

from agentkit import agents, backends, cli, install, profile
from agentkit.standards import Library


def std(d: Path, name: str, body: str, applies: str = "*.py") -> Path:
  d.mkdir(parents=True, exist_ok=True)
  f = d / f"{name}.md"
  f.write_text(f"---\nname: {name}\ndescription: {name}\napplies: {applies}\n---\n\n{body}\n")
  return f


@pytest.fixture
def isolated(tmp_path, monkeypatch):
  """Every path the profile code writes to, moved somewhere it can do no harm."""
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")
  monkeypatch.setattr(profile, "DEFAULT", tmp_path / "hub" / "profile")
  monkeypatch.delenv("AGENTS_PROFILE", raising=False)
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")    # no hooksPath, so no review on these commits
  for k, v in {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.io",
               "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.io"}.items():
    monkeypatch.setenv(k, v)
  return tmp_path


def run(*args, cwd=None) -> str:
  return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True, text=True).stdout


def published(tmp: Path, name: str) -> tuple[Path, Path]:
  """A bare remote and a clone of it with one commit pushed: what a profile on GitHub looks like."""
  bare, clone = tmp / f"{name}.git", tmp / name
  run("init", "-q", "--bare", "-b", "main", str(bare))
  run("clone", "-q", str(bare), str(clone))
  (clone / "README.md").write_text("profile\n")
  run("add", "-A", cwd=clone)
  run("commit", "-qm", "first", cwd=clone)
  run("push", "-q", "-u", "origin", "main", cwd=clone)
  return bare, clone


def how_i_work(d: Path) -> Path:
  d.mkdir()
  (d / "AGENTS.md").write_text("# how I work\n")
  return d


# -- where it is ----------------------------------------------------------------------------------

def test_the_profile_is_found_in_order_and_saved_in_place(isolated, monkeypatch):
  """Environment, then local.toml, then the default; empty means none, and saving rewrites only the path."""
  assert profile.path() is None                              # nothing anywhere
  profile.LOCAL.write_text("[profile\npath = ")
  assert profile.path() is None                              # a broken local file is none, not a crash

  profile.DEFAULT.mkdir(parents=True)
  assert profile.path() == profile.DEFAULT                   # the default, once it exists

  profile.LOCAL.write_text('# mine\n[profile]\npath = "/old"\nnote = "keep"\n\n[mine]\nkept = true\n')
  saved = isolated / 'odd "quoted" \\ dir'                   # a quote or backslash must stay valid TOML
  saved.mkdir()
  profile.save(saved)
  assert profile.path() == saved.resolve()                   # what this machine chose wins
  t = tomllib.loads(profile.LOCAL.read_text())
  assert t["profile"] == {"path": str(saved.resolve()), "note": "keep"} and t["mine"] == {"kept": True}
  assert profile.LOCAL.read_text().startswith("# mine\n")

  monkeypatch.setenv("AGENTS_PROFILE", str(isolated / "env"))
  assert profile.path() == isolated / "env"                  # and the environment over that
  monkeypatch.setenv("AGENTS_PROFILE", "")
  assert profile.path() is None                              # empty: none at all


# -- what it changes ------------------------------------------------------------------------------

def test_your_standard_replaces_the_starter_and_a_repo_still_adds_to_it(isolated, monkeypatch):
  """A profile standard replaces the starter of its name, a repo adds to it, and a Library given its own root ignores the profile."""
  bundled, mine, repo = isolated / "bundled", isolated / "mine", isolated / "repo"
  std(bundled, "python", "STARTER-PYTHON")
  std(bundled, "markdown", "STARTER-MARKDOWN", "*.md")
  std(mine, "python", "MY-PYTHON")
  std(mine, "voice", "MY-VOICE", "*.md")
  std(repo, "python", "REPO-PYTHON")

  lib = Library(bundled, [repo], profile=mine)
  py = [(layer.origin, layer.doc.body.strip()) for layer in lib.layers["python"]]
  assert py == [("profile", "MY-PYTHON"), ("repo", "REPO-PYTHON")]          # the starter is gone
  assert [l.origin for l in lib.layers["markdown"]] == ["machine-wide"]   # untouched starters stay
  assert [l.origin for l in lib.layers["voice"]] == ["profile"]           # and yours are added

  std(mine / "standards", "voice", "MY-VOICE", "*.md")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  assert "voice" not in Library(bundled).layers
  assert "voice" in Library().layers                          # the set in .agents does include it


def test_your_reviewers_backends_and_config_override_the_hubs(isolated, monkeypatch):
  """Profile reviewers and backends replace the ones in .agents by name; config sits between .agents and the repo, excludes accumulating."""
  bundled, mine, repo = isolated / "agents", isolated / "mine", isolated / "repo"
  bundled.mkdir()
  (bundled / "file-review.md").write_text("---\nname: file-review\nkind: logic\nmodel: code\n---\nBUNDLED\n")
  (mine / "agents").mkdir(parents=True)
  (mine / "agents" / "file-review.md").write_text("---\nname: file-review\nkind: logic\nmodel: code-large\n---\nMINE\n")
  (mine / "agents" / "my-check.md").write_text("---\nname: my-check\nkind: prose\n---\nMINE TOO\n")
  monkeypatch.setattr(agents, "AGENTS", bundled)
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  assert sorted(agents.definitions(bundled)) == ["file-review", "my-check"]
  assert "MINE" in agents.definition("file-review", agents.definitions(bundled)).body
  assert agents.kinds(agents.definitions(bundled)) == {"logic": ["file-review"], "prose": ["my-check"]}

  hub_config = isolated / "config.toml"   # one settings file at each level, backends included
  hub_config.write_text('[review]\nexclude = ["**/vendor/**"]\njobs = 4\n[inject]\nmap_over = 6144\n'
                        '[backends]\ndefault = "claude"\n[backends.claude]\nkind = "cli"\nargv = ["claude"]\n'
                        'models = { text = "hub-model" }\n[backends.ollama]\nkind = "http"\nurl = "x"\n')
  (mine / "config.toml").write_text('[review]\nexclude = ["**/data/**"]\njobs = 2\n[inject]\nmap_over = 9000\n'
                                    '[backends]\ndefault = "ollama"\n[backends.claude]\nkind = "cli"\n'
                                    'argv = ["claude"]\nmodels = { text = "my-model" }\n')
  monkeypatch.setattr(profile, "CONFIG", hub_config)
  known, default = backends.load_backends()
  assert default == "ollama" and set(known) == {"claude", "ollama"}
  assert known["claude"].spec["models"]["text"] == "my-model"

  (repo / ".agents").mkdir(parents=True)
  (repo / ".agents" / "agents.toml").write_text('[review]\nexclude = ["docs/*"]\n')
  cfg = profile.section("review", repo, add=("exclude",))
  assert cfg["exclude"] == ["**/vendor/**", "**/data/**", "docs/*"] and cfg["jobs"] == 2
  assert profile.section("inject")["map_over"] == 9000


# -- getting it onto a machine --------------------------------------------------------------------

def test_adopting_uses_a_directory_in_place_and_clones_a_url_once(isolated):
  """A local directory is used where it is; a remote is cloned to the default place and remembered, never over a different one."""
  mine = isolated / "dotfiles" / "agents"
  mine.mkdir(parents=True)
  assert profile.adopt(str(mine))[0] == 0
  assert profile.path() == mine.resolve() and not profile.DEFAULT.exists()
  assert profile.adopt(str(isolated / "nowhere"))[0] == 1

  bare, _ = published(isolated, "theirs")
  code, said = profile.adopt(str(bare))   # a path ending .git reads as a remote, as a URL would
  assert code == 0 and "clone" in said
  assert (profile.DEFAULT / "README.md").read_text() == "profile\n"
  assert profile.path() == profile.DEFAULT.resolve()       # saved, so nothing has to be told again
  code, said = profile.adopt(str(bare))                    # a second install is a no-op
  assert code == 0 and said.startswith("ok")

  other, _ = published(isolated, "other")
  code, said = profile.adopt(str(other))
  assert code == 1 and "already holds" in said


@pytest.mark.parametrize("start", ["", "my notes\n", "my notes", "notes\n\n@{hub}/AGENTS.md"])
def test_claude_md_points_at_your_profile_after_the_hub(isolated, monkeypatch, start):
  """Pointers are appended once, each on a line of its own, the one in .agents before yours, never replacing the file."""
  mine = how_i_work(isolated / "mine")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  target = isolated / "CLAUDE.md"
  target.write_text(start.format(hub=install.HUB))

  assert "your profile" in install.point_at(target)[0]
  text = target.read_text()
  assert text.startswith(start.format(hub=install.HUB))      # never replaced
  lines = text.splitlines()
  assert lines.index(f"@{install.HUB}/AGENTS.md") < lines.index(f"@{mine}/AGENTS.md")
  assert install.point_at(target)[0].startswith("ok") and target.read_text() == text


def test_moving_your_profile_moves_every_agents_pointer(isolated, monkeypatch):
  """Repointing swaps the old profile's AGENTS.md for the new one and leaves the rest of the file alone."""
  monkeypatch.setenv("HOME", str(isolated / "home"))
  first, second = how_i_work(isolated / "first"), how_i_work(isolated / "second")
  claude = isolated / "home" / ".claude" / "CLAUDE.md"
  claude.parent.mkdir(parents=True)
  claude.write_text(f"my notes\n\n@{install.HUB}/AGENTS.md\n@{first / 'AGENTS.md'}\n")

  profile.save(second)
  assert install.repoint(first / "AGENTS.md") == ["point .claude/CLAUDE.md at " + install.home(second.resolve() / "AGENTS.md")]
  text = claude.read_text()
  assert f"@{second.resolve() / 'AGENTS.md'}" in text and f"@{first / 'AGENTS.md'}" not in text
  assert text.startswith("my notes\n") and f"@{install.HUB}/AGENTS.md" in text      # the rest untouched


def test_init_makes_a_profile_you_can_push(isolated, monkeypatch):
  """Init reports only what it made: nothing over an existing profile, and no .git when git init failed."""
  where = isolated / "new"
  made = profile.init(where)
  assert (where / "standards").is_dir() and (where / "AGENTS.md").is_file() and ".git" in made
  assert "agent install --profile" in (where / "README.md").read_text()
  assert profile.init(where) == []

  real = profile.subprocess.run
  monkeypatch.setattr(profile.subprocess, "run",
                      lambda argv, **kw: subprocess.CompletedProcess(argv, 1) if argv[:2] == ["git", "init"] else real(argv, **kw))
  assert ".git" not in profile.init(isolated / "p")


# -- keeping machines in step ---------------------------------------------------------------------

def test_drift_names_what_another_machine_would_miss(isolated):
  _, clone = published(isolated, "mine")
  assert profile.drift(clone) == []

  (clone / "voice.md").write_text("new\n")
  assert profile.drift(clone) == ["1 uncommitted change"]

  run("add", "-A", cwd=clone)
  run("commit", "-qm", "voice", cwd=clone)
  assert profile.drift(clone) == ["1 commit not pushed"]

  lone = isolated / "lone"
  run("init", "-q", str(lone))
  assert profile.drift(lone) == ["no upstream to push to"]


def test_update_pulls_both_and_refuses_to_merge(isolated, monkeypatch, capsys):
  """Update fast-forwards .agents and the profile, and fails rather than merge."""
  hub_bare, hub = published(isolated, "hub")
  mine_bare, mine = published(isolated, "mine")
  monkeypatch.setattr(profile, "HUB", hub)
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))

  for bare, name in ((hub_bare, "hub-elsewhere"), (mine_bare, "mine-elsewhere")):
    other = isolated / name                                  # another machine pushes to each
    run("clone", "-q", str(bare), str(other))
    (other / "new.md").write_text("from another machine\n")
    run("add", "-A", cwd=other)
    run("commit", "-qm", "mac", cwd=other)
    run("push", "-q", cwd=other)

  assert cli.setup.cmd_update(argparse.Namespace()) == 0
  assert (hub / "new.md").is_file() and (mine / "new.md").is_file()

  (mine / "new.md").write_text("diverged here\n")            # now one that cannot fast-forward
  run("commit", "-qam", "here", cwd=mine)
  other = isolated / "mine-elsewhere"
  (other / "new.md").write_text("and there\n")
  run("commit", "-qam", "there", cwd=other)
  run("push", "-q", cwd=other)
  assert cli.setup.cmd_update(argparse.Namespace()) == 1
  assert "FAIL" in capsys.readouterr().out
