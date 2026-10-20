"""The installer and the global git hooks, run against a throwaway HOME and a throwaway git config.

Author: Marco Cassar (@Ocramaru)
"""

import json, os, shutil, subprocess, sys, tomllib, uuid, zipfile
from pathlib import Path

import pytest
from conftest import REPO, git, note, put

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
  assert (home / ".agents").resolve() == install.HOME   # linked, since it was missing
  assert (home / ".local" / "bin" / "agent").resolve() == install.SHIPPED / "bin" / "agent"
  assert (home / ".claude" / "CLAUDE.md").read_text().count("AGENTS.md") == 1

  code, lines = install.run([])
  changes = [line for line in lines if line.startswith(" ") and line.strip().partition(" ")[0] not in ("ok", "note")]
  assert code == 0 and changes == [], changes

  for text in ("{not json", "[1, 2]"):
    settings.write_text(text)
    assert install.hooks(settings)[0].startswith("skip  hooks block") and settings.read_text() == text


def test_an_installed_package_reads_its_own_copy_and_keeps_state_in_home(tmp_path):
  """A package carrying `shipped/` reads standards, reviewers and config from it and keeps state in ~/.agents; a checkout is both."""
  site = tmp_path / "site"
  shutil.copytree(install.SHIPPED / "agentkit", site / "agentkit", ignore=shutil.ignore_patterns("__pycache__"))
  (site / "agentkit" / "shipped").mkdir()
  shown = subprocess.run([sys.executable, "-P", "-c", "from agentkit import agents, profile, standards; print(profile.SHIPPED, profile.HOME, profile.CONFIG, profile.LOCAL, profile.DEFAULT, standards.GLOBAL, agents.AGENTS)"], cwd=tmp_path, capture_output=True, check=True, text=True, env={**os.environ, "PYTHONPATH": str(site), "HOME": str(tmp_path / "home")}).stdout.split()
  shipped, home = (site / "agentkit" / "shipped").resolve(), tmp_path / "home" / ".agents"
  assert shown == [str(path) for path in (shipped, home, shipped / "config.toml", home / "local.toml", home / "profile", shipped / "standards", shipped / "agents")]
  assert install.SHIPPED == install.HOME == REPO   # a checkout is its own state


def test_the_wheel_carries_the_package_and_every_shipped_file_and_nothing_of_this_machine(wheel):
  """The wheel holds agentkit, the hub's tracked files under agentkit/shipped with the hooks executable, and the `agent` entry point."""
  tracked = subprocess.run(["git", "ls-files", "agentkit", "AGENTS.md", "agents", "commands", "config.toml", "githooks", "hooks", "settings.hooks.json", "standards", "templates"], cwd=REPO, capture_output=True, check=True, text=True).stdout.split()
  with zipfile.ZipFile(wheel) as archive:
    modes = {info.filename: info.external_attr >> 16 for info in archive.infolist() if not info.filename.startswith("agentkit-")}
    entry_points = archive.read(next(name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt"))).decode()
  assert sorted(modes) == sorted(name if name.startswith("agentkit/") else f"agentkit/shipped/{name}" for name in tracked)
  assert all(mode & 0o111 for name, mode in modes.items() if name.startswith(("agentkit/shipped/hooks/", "agentkit/shipped/githooks/")))
  assert "agent = agentkit.__main__:main" in entry_points


def test_an_install_runs_from_outside_any_checkout_given_only_an_empty_home(fresh, installed):
  """The installed `agent` names its version and repository from its metadata, checks the machine and resolves standards from its own copy, with no clone anywhere."""
  assert fresh(["--version"]).stdout == f"agentkit {tomllib.loads((REPO / 'pyproject.toml').read_text())['project']['version']}\n"   # a wheel from a file records no commit
  assert subprocess.run([installed / "python", "-P", "-c", "from agentkit import issue; print(issue.slug())"], capture_output=True, check=True, cwd=installed, text=True).stdout == "Ocramaru/.agents\n"   # -P and away from the checkout, or it imports the checkout
  doctor = fresh(["doctor"], expect=None)
  assert "Traceback" not in doctor.stderr and doctor.stdout.strip().splitlines()[-1].split()[1].startswith("ok")
  assert {"python", "commits"} <= {line.split("\t")[0] for line in fresh(["standards", "x.py"]).stdout.splitlines()}
  assert json.loads(fresh(["manifest"]).stdout)["standards"]["python"]["path"].startswith(str(installed.parent))


def test_an_install_copies_what_agents_name_by_path_into_home_and_its_hooks_reach_it(fresh, machine, tmp_path):
  """Install copies hooks, githooks, commands and AGENTS.md into ~/.agents, a hook fired from there reaches the installed `agent`, a rerun changes nothing, and doctor fails a copy that drifted."""
  home = Path(machine["HOME"])
  (home / ".claude").mkdir(parents=True)
  fresh(["install"])
  settings = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]
  scripts = [Path(hook["command"].replace("$HOME", str(home))) for event in settings.values() for group in event for hook in group["hooks"]]
  assert scripts and all(os.access(script, os.X_OK) for script in scripts)
  assert (home / ".claude" / "commands" / "agents.md").resolve() == (home / ".agents" / "commands" / "agents.md").resolve()
  assert f"@{home}/.agents/AGENTS.md" in (home / ".claude" / "CLAUDE.md").read_text() and not (home / ".agents" / "bin").exists()

  (tmp_path / "elsewhere" / "x.py").write_text("x = 1\n")
  payload = {"session_id": f"install-{uuid.uuid4().hex}", "tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "elsewhere" / "x.py")}}
  fired = subprocess.run(["bash", str(home / ".agents" / "hooks" / "inject.sh")], input=json.dumps(payload), capture_output=True, check=True, text=True, env=machine)
  assert json.loads(fired.stdout)["systemMessage"].startswith(".agents loaded")

  assert not {line.split()[0] for line in fresh(["install"]).stdout.splitlines() if line.strip()} & {"copy", "link", "saved", "wrote", "point"}
  assert "ok    hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=None).stdout
  (home / ".agents" / "hooks" / "inject.sh").write_text("stale\n")
  assert "FAIL  hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=1).stdout
  assert "copy  1 file into" in fresh(["install"]).stdout


def test_an_installs_stale_copies_are_files_nested_ones_included(tmp_path, monkeypatch):
  """stale() names every shipped file beneath the fixed paths whose copy is missing or differs, and never a directory, which a copy would fail on."""
  shipped, home = tmp_path / "shipped", tmp_path / "home"
  put(shipped, "AGENTS.md", "hooks/a.sh", "githooks/_dispatch", "commands/nested/b.md")
  put(home, "hooks/a.sh")
  monkeypatch.setattr(install, "INSTALLED", True)
  monkeypatch.setattr(install, "SHIPPED", shipped)
  monkeypatch.setattr(install, "HOME", home)
  assert [str(source.relative_to(shipped)) for source in install.stale()] == ["AGENTS.md", "commands/nested/b.md", "githooks/_dispatch"]


def test_update_upgrades_an_install_through_uv_and_lands_the_new_hooks(machine, tmp_path):
  """An install from a directory is current until its source moves; then `agent update` upgrades it and the new version's hooks reach ~/.agents."""
  source, home, number = tmp_path / "source", Path(machine["HOME"]), tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
  for name in subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True, check=True, text=True).stdout.splitlines():
    (source / name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / name, source / name)
  subprocess.run(["uv", "tool", "install", "--quiet", str(source)], capture_output=True, check=True, env=machine)
  agent = lambda *args: subprocess.run([str(tmp_path / "bin" / "agent"), *args], capture_output=True, check=True, cwd=tmp_path, env=machine, text=True).stdout
  (home / ".claude").mkdir(parents=True)
  agent("install")
  assert f"already current at {number}" in agent("update")

  (source / "pyproject.toml").write_text((source / "pyproject.toml").read_text().replace(f'version = "{number}"', f'version = "{number}.1"'))
  (source / "hooks" / "forget.sh").write_text((source / "hooks" / "forget.sh").read_text() + "# newer\n")
  updated = agent("update")
  assert f"upgraded {number} -> {number}.1" in updated and "copy  1 file into" in updated
  assert (home / ".agents" / "hooks" / "forget.sh").read_text().endswith("# newer\n")

  (source / "pyproject.toml").write_text((source / "pyproject.toml").read_text().replace(f'version = "{number}.1"', f'version = "{number}.2"'))
  (home / ".agents" / "agentkit").mkdir()   # what makes the new version's install refuse: ~/.agents looks like a clone
  failed = subprocess.run([str(tmp_path / "bin" / "agent"), "update"], capture_output=True, check=False, cwd=tmp_path, env=machine, stdin=subprocess.DEVNULL, text=True)
  assert failed.returncode == 1 and f"FAIL   .agents: upgraded {number}.1 -> {number}.2, but its install did not finish" in failed.stdout


def test_an_install_through_uvx_keeps_agentkit_as_a_tool_and_installs_from_it(wheel, machine, tmp_path):
  """`uvx --from <wheel> agent install` leaves `agent` installed as a uv tool, and the install that ran is that tool's, so its hooks call it."""
  home = Path(machine["HOME"])
  (home / ".claude").mkdir(parents=True)
  ran = subprocess.run(["uvx", "--from", str(wheel), "agent", "install"], capture_output=True, check=True, cwd=tmp_path, env=machine, text=True).stdout
  assert ran.startswith("keep  agentkit as a uv tool") and (tmp_path / "bin" / "agent").is_file()
  assert f"  ok    {tmp_path / 'bin' / 'agent'}" in ran and (home / ".agents" / "hooks" / "inject.sh").is_file()   # the `agent` on PATH is the one that installed


def test_install_sh_installs_the_tool_then_wires_the_machine_and_reruns_cleanly(wheel, machine, tmp_path):
  """install.sh installs agentkit as a uv tool from AGENTS_SOURCE and runs that tool's `agent install`, and a second run changes nothing."""
  (Path(machine["HOME"]) / ".claude").mkdir(parents=True)
  run = lambda: subprocess.run(["bash", str(REPO / "install.sh")], capture_output=True, check=True, cwd=tmp_path, env=machine | {"AGENTS_SOURCE": str(wheel)}, start_new_session=True, stdin=subprocess.DEVNULL, text=True).stdout   # no terminal to hand over
  assert "wrote hooks block in settings.json" in run() and (tmp_path / "bin" / "agent").is_file()
  assert not {line.split()[0] for line in run().splitlines() if line.strip()} & {"copy", "link", "saved", "wrote", "point"}


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
  (home / ".agents" / "hooks" / "log.sh").symlink_to(install.SHIPPED / "hooks" / "log.sh")   # the real logger, into this HOME
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
