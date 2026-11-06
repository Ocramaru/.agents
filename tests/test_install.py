"""The installer and the global git hooks, run against a throwaway HOME and a throwaway git config."""

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tomllib
import uuid
import zipfile
from pathlib import Path

import pytest
from conftest import REPO, agent, fake, git, note, put, typed

from agentkit import doctor, hooks, hub, install, status, words

WHEEL = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]   # what the wheel carries: its packages, and what the hub reads beside them under force-include


@pytest.fixture
def home(tmp_path, monkeypatch):
  (tmp_path / "home" / ".claude").mkdir(parents=True)
  monkeypatch.setenv("HOME", str(tmp_path / "home"))
  monkeypatch.setenv("AGENTS_HOOK_LOG", str(tmp_path / "home" / ".agents" / ".hooks.log"))
  monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
  return tmp_path / "home"


FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "api user") echo tester ;;
  "repo create") git init -q --bare "$GH_REMOTE" && git -C "$6" remote add origin "$GH_REMOTE" && git -C "$6" push -q -u origin main ;;
  *) exit 1 ;;
esac
"""


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
  assert (home / ".agents").resolve() == hub.HOME   # linked, since it was missing
  assert (home / ".local" / "bin" / "agent").resolve() == hub.BUNDLED / "bin" / "agent"
  assert (home / ".claude" / "CLAUDE.md").read_text().count("AGENTS.md") == 1
  assert {line.strip().partition(" ")[0] for line in lines} & set(words.CHANGED) == {"link", "saved", "wrote", "point"}   # the words install says a change with

  code, lines = install.run([])
  changes = [line for line in lines if line.strip().partition(" ")[0] in words.CHANGED]
  assert code == 0 and changes == [], changes
  assert f"  ok    .agents -> {hub.HOME}" in lines   # a second run says the link it found

  for text in ("{not json", "[1, 2]"):
    settings.write_text(text)
    assert install.claude_hooks(settings)[0].startswith("skip  hooks block") and settings.read_text() == text


def test_inject_read_puts_read_in_inject_s_matcher_alone_and_status_expects_what_install_wrote(home, tmp_path, monkeypatch):
  """Off, the block is settings.hooks.json as it ships, SessionStart included; `[inject] read = true` adds Read to inject's matcher and no other, and status reads that block as in place."""
  monkeypatch.setattr(hub, "LOCAL", tmp_path / "local.toml")   # never this machine's
  matchers = lambda block: {hook["command"].rsplit("/", 1)[-1]: entry.get("matcher") for entries in block.values() for entry in entries for hook in entry["hooks"]}
  shipped = json.loads((REPO / "settings.hooks.json").read_text())
  assert install.claude_block() == shipped and "session-start.sh" in matchers(shipped)

  put(tmp_path, "profile/config.toml", text="[inject]\nread = true\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(tmp_path / "profile"))
  assert matchers(install.claude_block()) == matchers(shipped) | {"inject.sh": "Edit|Write|NotebookEdit|Read"}
  install.claude_hooks(home / ".claude" / "settings.json")
  assert status.claude_hooks() == [("claude hooks", f"in place ({status.short(home / '.claude' / 'settings.json')})", "")]


def test_install_brings_the_hubs_own_hooks_to_the_bundle_and_leaves_every_other_hook_as_it_was(home):
  """The hub's hooks are known by the script they run: an older one is replaced, one the bundle dropped goes, the user's stay in every event, a backup is kept, and the result reads as current."""
  settings, mine = home / ".claude" / "settings.json", {"type": "command", "command": "~/bin/my-hook.sh"}
  settings.write_text(json.dumps({"model": "x", "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [mine, {"type": "command", "command": "$HOME/.agents/hooks/no-reformat.sh --older"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": f"{home}/.agents/hooks/retired.sh"}]}],   # however home is spelled, it is the hub's
    "Notification": [{"hooks": [mine]}]}}))
  assert install.claude_hooks(settings)[-1] == "wrote hooks block in settings.json" and len(list(settings.parent.glob("settings.json.bak*"))) == 1

  written = json.loads(settings.read_text())
  assert written["model"] == "x" and "retired.sh" not in settings.read_text()
  assert written["hooks"]["Notification"] == [{"hooks": [mine]}] and written["hooks"]["PreToolUse"][0] == {"matcher": "Bash", "hooks": [mine]}
  assert install.partition(written["hooks"]) == (install.claude_block(), {"PreToolUse": [{"matcher": "Bash", "hooks": [mine]}], "Notification": [{"hooks": [mine]}]})
  assert install.claude_hooks(settings) == ["ok    hooks block in settings.json"] and status.claude_hooks()[0][1].startswith("in place")   # the user's own hooks are not drift


@pytest.mark.parametrize("command,hubs", [
  ('"$HOME/.agents/hooks/inject.sh"', True),            # quoted, as a path with a space would be
  ("bash $HOME/.agents/hooks/inject.sh", True),
  ("sh ~/.agents/hooks/gate.sh --flag", True),
  ("env ${HOME}/.agents/hooks/inject.sh", True),
  ("'HOME_PATH/.agents/hooks/inject.sh'", True),
  ("$HOME/bin/inject.sh", False),
  ("bash -c '$HOME/.agents/hooks/inject.sh'", False),     # a script inside another command is not the command
  ('"$HOME/.agents/hooks/inject.sh', False),             # unparseable: the user's
])
def test_the_hubs_hook_is_known_however_its_command_is_spelled(home, command, hubs):
  """A command is read as the shell reads it, through a leading bash, sh or env and with home as ~, $HOME or ${HOME}; whatever shlex cannot read is the user's."""
  block = {"Stop": [{"hooks": [hook := {"type": "command", "command": command.replace("HOME_PATH", str(home))}]}]}
  assert install.partition(block) == ((block, {}) if hubs else ({}, block)), hook["command"]


def test_an_installed_package_reads_its_own_copy_and_keeps_state_in_home(tmp_path):
  """A package carrying `bundled/` reads standards, reviewers and config from it and keeps state in ~/.agents; a checkout is both."""
  site = tmp_path / "site"
  shutil.copytree(hub.BUNDLED / "agentkit", site / "agentkit", ignore=shutil.ignore_patterns("__pycache__"))
  (site / "agentkit" / "bundled").mkdir()
  shown = subprocess.run([sys.executable, "-P", "-c", "from agentkit import hub, profile; print(hub.BUNDLED, hub.HOME, hub.CONFIG, hub.LOCAL, profile.DEFAULT, hub.STANDARDS, hub.REVIEWERS)"], cwd=tmp_path, capture_output=True, check=True, text=True, env={**os.environ, "PYTHONPATH": str(site), "HOME": str(tmp_path / "home")}).stdout.split()
  bundled, home = (site / "agentkit" / "bundled").resolve(), tmp_path / "home" / ".agents"
  assert shown == [str(path) for path in (bundled, home, bundled / "config.toml", home / "local.toml", home / "profile", bundled / "standards", bundled / "agents")]
  assert hub.BUNDLED == hub.HOME == REPO   # a checkout is its own state


def test_the_wheel_bundles_exactly_the_paths_hub_and_install_name_under_bundled(tmp_path):
  """Every path hub.py names under hub.BUNDLED, and every one in install.FIXED, is in pyproject.toml's force-include at the same place under agentkit/bundled, and nothing else is; read from an installed layout, where only those sit under it."""
  site = tmp_path / "site"
  shutil.copytree(hub.BUNDLED / "agentkit", site / "agentkit", ignore=shutil.ignore_patterns("__pycache__"))
  (site / "agentkit" / "bundled").mkdir()
  named = subprocess.run([sys.executable, "-P", "-c", "from pathlib import Path; from agentkit import hub, install; print(*{str(path.relative_to(hub.BUNDLED)) for path in vars(hub).values() if isinstance(path, Path) and path.is_relative_to(hub.BUNDLED) and path != hub.BUNDLED} | set(install.FIXED))"], cwd=tmp_path, capture_output=True, check=True, text=True, env={**os.environ, "PYTHONPATH": str(site), "HOME": str(tmp_path / "home")}).stdout.split()
  assert sorted(named) == sorted(WHEEL["force-include"])
  assert all(inside == f"agentkit/bundled/{name}" for name, inside in WHEEL["force-include"].items())


def test_the_wheel_carries_the_package_and_every_bundled_file_and_nothing_of_this_machine(wheel):
  """The wheel holds agentkit, the hub's tracked files under agentkit/bundled with the hooks executable, and the `agent` entry point."""
  tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", *WHEEL["packages"], *WHEEL["force-include"]], cwd=REPO, capture_output=True, check=True, text=True).stdout.split()
  with zipfile.ZipFile(wheel) as archive:
    modes = {info.filename: info.external_attr >> 16 for info in archive.infolist() if not info.filename.startswith("agentkit-")}
    entry_points = archive.read(next(name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt"))).decode()
  assert sorted(modes) == sorted(name if name.startswith("agentkit/") else f"agentkit/bundled/{name}" for name in tracked)
  assert all(mode & 0o111 for name, mode in modes.items() if name.startswith(("agentkit/bundled/hooks/", "agentkit/bundled/githooks/")))
  assert "agent = agentkit.__main__:main" in entry_points


def test_an_install_runs_from_outside_any_checkout_given_only_an_empty_home(fresh, installed):
  """The installed `agent` names its version and repository from its metadata, checks the machine and resolves standards from its own copy, with no clone anywhere."""
  assert fresh(["--version"]).stdout == f"agentkit {tomllib.loads((REPO / 'pyproject.toml').read_text())['project']['version']}\n"   # a wheel from a file records no commit
  assert subprocess.run([installed / "python", "-P", "-c", "from agentkit import issue; print(issue.slug())"], capture_output=True, check=True, cwd=installed, text=True).stdout == "Ocramaru/.agents\n"   # -P and away from the checkout, or it imports the checkout
  doctor = fresh(["doctor"], expect=None)
  assert "Traceback" not in doctor.stderr and doctor.stdout.strip().splitlines()[-1].split()[1].startswith("ok")
  assert {"python", "commits"} <= {line.split("\t")[0] for line in fresh(["standards", "x.py"]).stdout.splitlines()}
  assert json.loads(fresh(["manifest"]).stdout)["standards"]["python"]["path"].startswith(str(installed.parent))


def test_an_install_copies_what_agents_name_by_path_into_home_and_its_hooks_reach_it(fresh, installed, machine, tmp_path):
  """Install copies hooks, githooks, commands and AGENTS.md into ~/.agents, a hook fired from there reaches the installed `agent` with or without it on PATH, and a rerun changes nothing.
  Doctor fails a copy that drifted, a link, or one the bundle dropped; install then sets the first two aside to a `.bak` and removes the last."""
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
  assert (home / ".agents" / ".cli").read_text() == f"{installed / 'agent'}\n"   # recorded, so a PATH without uv's bin, as a git GUI has, reaches it too
  bare = machine | {"PATH": os.pathsep.join(str(Path(found).parent) for found in (shutil.which("bash"), shutil.which("jq")))}
  fired = subprocess.run(["bash", str(home / ".agents" / "hooks" / "inject.sh")], input=json.dumps(payload | {"session_id": f"install-{uuid.uuid4().hex}"}), capture_output=True, check=True, text=True, env=bare)
  assert json.loads(fired.stdout)["systemMessage"].startswith(".agents loaded")

  assert {line.split()[0] for line in fresh(["install"]).stdout.splitlines() if line.strip()}.isdisjoint(words.CHANGED)
  assert "ok    hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=None).stdout
  hooks_copy = home / ".agents" / "hooks"
  (hooks_copy / "inject.sh").write_text("edited\n")   # changed where it was copied
  (tmp_path / "theirs.sh").write_text("theirs\n")
  (hooks_copy / "forget.sh").unlink()
  (hooks_copy / "forget.sh").symlink_to(tmp_path / "theirs.sh")
  (hooks_copy / "retired.sh").write_text("retired\n")   # a copy an older bundle had, by the record
  with (home / ".agents" / ".copied").open("a") as record: record.write(f"{hashlib.sha256(b'retired\n').hexdigest()}  hooks/retired.sh\n")
  assert "FAIL  hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=1).stdout

  said = fresh(["install"]).stdout
  assert "copy  2 files into" in said and "drop  .agents/hooks/retired.sh" in said and not (hooks_copy / "retired.sh").exists()
  assert (hooks_copy / "inject.sh.bak").read_text() == "edited\n" and (hooks_copy / "forget.sh.bak").is_symlink() and (tmp_path / "theirs.sh").read_text() == "theirs\n"   # set aside, never written through
  assert not (hooks_copy / "forget.sh").is_symlink() and "ok    hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=None).stdout

  githooks, theirs = home / ".agents" / "githooks", tmp_path / "their-githooks"
  shutil.copytree(githooks, theirs)
  shutil.rmtree(githooks)
  githooks.symlink_to(theirs)   # someone else's folder in its place, one file in it changed
  (theirs / "_dispatch").write_text("theirs\n")
  held = sorted(path.name for path in theirs.iterdir())
  assert "FAIL  hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=1).stdout
  assert "saved .agents/githooks.bak, a link out of .agents" in fresh(["install"]).stdout
  assert sorted(path.name for path in theirs.iterdir()) == held and (theirs / "_dispatch").read_text() == "theirs\n"   # nothing written through the link
  assert (home / ".agents" / "githooks.bak").is_symlink() and not githooks.is_symlink() and sorted(path.name for path in githooks.iterdir()) == held
  assert "ok    hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=None).stdout


def test_an_installs_stale_copies_are_files_nested_ones_included(tmp_path, monkeypatch):
  """stale() names every bundled file beneath the fixed paths whose copy is missing or differs, and never a directory, which a copy would fail on."""
  bundled, home = tmp_path / "bundled", tmp_path / "home"
  put(bundled, "AGENTS.md", "hooks/a.sh", "githooks/_dispatch", "commands/nested/b.md")
  put(home, "hooks/a.sh")
  monkeypatch.setattr(hub, "INSTALLED", True)
  monkeypatch.setattr(hub, "BUNDLED", bundled)
  monkeypatch.setattr(hub, "HOME", home)
  assert [str(source.relative_to(bundled)) for source in install.stale()] == ["AGENTS.md", "commands/nested/b.md", "githooks/_dispatch"]


def test_a_directory_where_a_copy_goes_is_set_aside_like_a_link(home, tmp_path, monkeypatch):
  """A directory at a bundled file's place, or at one the bundle dropped, is someone else's: set aside whole, never read as a file or copied into."""
  bundled, state = tmp_path / "bundled", home / ".agents"
  put(bundled, "hooks/a.sh", text="new\n")
  put(state, "hooks/a.sh/theirs.txt", "hooks/retired.sh/theirs.txt")
  monkeypatch.setattr(hub, "INSTALLED", True)
  monkeypatch.setattr(hub, "BUNDLED", bundled)
  monkeypatch.setattr(hub, "HOME", state)
  for name, path in (("COPIED", state / ".copied"), ("RECORD", state / ".cli"), ("GITHOOKS", state / "githooks"), ("CLI", tmp_path / "agent")): monkeypatch.setattr(install, name, path)
  (state / ".copied").write_text("0  hooks/a.sh\n0  hooks/retired.sh\n")   # both named by the last install, so each would be read to compare

  code, lines = install.run([])
  assert code == 0, lines
  assert (state / "hooks" / "a.sh").read_text() == "new\n" and (state / "hooks" / "a.sh.bak" / "theirs.txt").is_file()
  assert (state / "hooks" / "retired.sh.bak" / "theirs.txt").is_file() and not (state / "hooks" / "retired.sh").exists()
  assert sum(line.strip().startswith("saved") for line in lines) == 2


def test_update_upgrades_an_install_through_uv_and_lands_the_new_hooks(machine, tmp_path):
  """An install from a directory is current until its source moves; then `agent update` upgrades it and the new version's hooks reach ~/.agents."""
  source, home, number = tmp_path / "source", Path(machine["HOME"]), tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
  for name in subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True, check=True, text=True).stdout.splitlines():
    (source / name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / name, source / name)
  subprocess.run(["uv", "tool", "install", "--quiet", str(source)], capture_output=True, check=True, env=machine)
  agent = lambda *args: subprocess.run([str(tmp_path / "bin" / "agent"), *args], capture_output=True, check=True, cwd=tmp_path, env=machine, stdin=subprocess.DEVNULL, text=True).stdout
  (home / ".claude").mkdir(parents=True)
  agent("install")
  assert f"already current at {number}" in (said := agent("update")) and "no default backend is set, so headless reviews (post-commit, doc-check) cannot run: `agent install --backend <" in said

  (source / "pyproject.toml").write_text((source / "pyproject.toml").read_text().replace(f'version = "{number}"', f'version = "{number}.1"'))
  (source / "hooks" / "forget.sh").write_text((source / "hooks" / "forget.sh").read_text() + "# newer\n")
  updated = agent("update")
  assert f"upgraded {number} -> {number}.1" in updated and "copy  1 file into" in updated
  assert (home / ".agents" / "hooks" / "forget.sh").read_text().endswith("# newer\n")

  (source / "pyproject.toml").write_text((source / "pyproject.toml").read_text().replace(f'version = "{number}.1"', f'version = "{number}.2"'))
  (home / ".agents" / "agentkit").mkdir()   # what makes the new version's install refuse: ~/.agents looks like a clone
  failed = subprocess.run([str(tmp_path / "bin" / "agent"), "update"], capture_output=True, check=False, cwd=tmp_path, env=machine, stdin=subprocess.DEVNULL, text=True)
  assert failed.returncode == 1 and f"FAIL  .agents: upgraded {number}.1 -> {number}.2, but its install did not finish (cannot install: " in failed.stdout and "is a clone of .agents" in failed.stdout


def scripted(tmp_path, monkeypatch, uv: dict | None = None, agent: dict | None = None) -> Path:
  """Stand in for uv and the new `agent` with fakes that are all of PATH, each answering by its first argument with the (exit code, stdout, stderr) given for it and failing on any other; no `uv` leaves uv off PATH.

  The new `agent` also writes whether its stdin was a terminal to `fake/stdin`. Returns the log of every call, one line each.
  """
  answering = lambda answers: 'case "$1" in\n' + "".join(f"  {shlex.quote(first)}) printf %s {shlex.quote(out)}; printf %s {shlex.quote(error)} >&2; exit {code} ;;\n" for first, (code, out, error) in answers.items()) + '  *) echo "unexpected arguments: $*" >&2; exit 2 ;;\nesac'
  shutil.rmtree(tmp_path / "fake", ignore_errors=True)   # each script starts from no fakes and an empty log
  log = fake(tmp_path, monkeypatch, "agent", f'{{ [[ -t 0 ]] && echo "a terminal" || echo "not a terminal"; }} > {shlex.quote(str(tmp_path / "fake" / "stdin"))}\n{answering(agent or {})}')
  if uv is not None: fake(tmp_path, monkeypatch, "uv", answering(uv))
  monkeypatch.setenv("PATH", str(tmp_path / "fake"))   # the fakes and nothing else, so a uv not given is a uv not found
  monkeypatch.setattr(install, "CLI", tmp_path / "fake" / "agent")
  monkeypatch.setattr(hub, "version", lambda: "1.0")
  return log


def test_upgrade_installs_nothing_when_the_version_did_not_move(monkeypatch, tmp_path):
  """When the upgraded code reports the version it had, upgrade says so and never runs its install."""
  log = scripted(tmp_path, monkeypatch, uv={"tool": (0, "", "")}, agent={"--version": (0, "agentkit 1.0\n", "")})
  assert install.upgrade() == (0, ["ok    .agents: already current at 1.0"])
  assert log.read_text().splitlines() == ["uv tool upgrade agentkit", "agent --version"]


def test_upgrade_lists_what_the_new_install_changed_and_asks_it_nothing(monkeypatch, tmp_path):
  """A moved version runs the new `agent install --changes` with stdin closed, and its lines follow the upgrade line indented."""
  log = scripted(tmp_path, monkeypatch, uv={"tool": (0, "", "")}, agent={"--version": (0, "agentkit 1.1\n", ""), "install": (0, "copy  1 file into ~/.agents\nwrote hooks block in settings.json\n\n", "")})
  assert install.upgrade() == (0, ["ok    .agents: upgraded 1.0 -> 1.1", "      copy  1 file into ~/.agents", "      wrote hooks block in settings.json"])
  assert log.read_text().splitlines()[-1] == "agent install --changes" and (tmp_path / "fake" / "stdin").read_text() == "not a terminal\n"


def test_upgrade_fails_with_the_last_line_uv_or_the_new_install_gave(monkeypatch, tmp_path):
  """A missing or failing uv, and an install that exits non-zero, each give code 1 and the reason in one line; the install's own lines follow."""
  scripted(tmp_path, monkeypatch)
  assert install.upgrade() == (1, ["FAIL  .agents: uv is not on PATH"])
  scripted(tmp_path, monkeypatch, uv={"tool": (2, "", "warning: x\nerror: no index\n\n")})
  assert install.upgrade() == (1, ["FAIL  .agents: error: no index"])
  scripted(tmp_path, monkeypatch, uv={"tool": (0, "", "")}, agent={"--version": (1, "", "ModuleNotFoundError: No module named 'rich'\n")})   # the new version cannot start
  assert install.upgrade() == (1, ["FAIL  .agents: upgraded, but the new version does not run (ModuleNotFoundError: No module named 'rich'); run `agent doctor`"])

  scripted(tmp_path, monkeypatch, uv={"tool": (0, "", "")}, agent={"--version": (0, "agentkit 1.1\n", ""), "install": (1, "cannot install: ~/.agents is a clone\n", "")})
  assert install.upgrade() == (1, ["FAIL  .agents: upgraded 1.0 -> 1.1, but its install did not finish (cannot install: ~/.agents is a clone); run `agent install`", "      cannot install: ~/.agents is a clone"])
  scripted(tmp_path, monkeypatch, uv={"tool": (0, "", "")}, agent={"--version": (0, "agentkit 1.1\n", ""), "install": (1, "", "")})
  assert install.upgrade() == (1, ["FAIL  .agents: upgraded 1.0 -> 1.1, but its install did not finish (it said nothing); run `agent install`"])


def test_handing_over_runs_the_kept_agent_with_these_arguments_and_a_path_without_uvxs_own_environment(monkeypatch, tmp_path):
  """The kept `agent` replaces this process with this process's arguments, and PATH loses every entry that is uvx's `sys.prefix/bin`, a link to it included, and nothing else."""
  alias, calls = tmp_path / "alias", []
  alias.symlink_to(Path(sys.prefix) / "bin")
  monkeypatch.setenv("PATH", os.pathsep.join([str(alias), str(tmp_path / "first"), str(Path(sys.prefix) / "bin"), str(tmp_path / "second")]))
  monkeypatch.setattr(sys, "argv", ["agent", "install", "--profile", "none"])
  monkeypatch.setattr(install.os, "execve", lambda *call: calls.append(call))
  install.hand_over("/kept/agent")
  assert calls == [("/kept/agent", ["/kept/agent", "install", "--profile", "none"], os.environ | {"PATH": os.pathsep.join([str(tmp_path / "first"), str(tmp_path / "second")]), install.HANDED_OVER: "1"})]


def test_doctor_judges_the_agent_a_shell_finds_not_the_one_uv_run_puts_first(monkeypatch, tmp_path):
  """Run through `uv run`, this venv's bin leads PATH with an `agent` of its own; doctor looks past it, to the one a shell outside reaches."""
  (shell := tmp_path / "bin").mkdir()
  (shell / "agent").symlink_to(install.CLI)
  monkeypatch.setenv("PATH", os.pathsep.join([str(Path(sys.prefix) / "bin"), str(shell)]))   # as `uv run` leaves it
  (passed, label, _), = [check for check in doctor.checks() if check[1].startswith("`agent` on PATH")]
  assert passed and label == f"`agent` on PATH -> {shell / 'agent'}"


def test_the_kept_tool_never_keeps_itself_again_when_uvs_tools_live_in_its_cache(monkeypatch, tmp_path):
  """A tool directory inside uv's cache looks like uvx's own environment, so the handed-over `agent` is told by its environment that it is the kept one."""
  scripted(tmp_path, monkeypatch, uv={"cache": (0, str(Path(sys.prefix).parent), ""), "tool": (0, str(tmp_path / "tools"), "")})   # `uv cache dir` holds this environment, as a tool dir inside the cache would
  monkeypatch.setattr(hub, "INSTALLED", True)
  monkeypatch.setattr(hub, "source", dict)
  monkeypatch.setattr(install, "preflight", lambda profile=None: [])
  handed = []
  monkeypatch.setattr(install.os, "execve", lambda *call: handed.append(call))
  code, kept = install.keep()
  assert code == 0 and kept
  install.hand_over(kept)
  for key, value in handed[-1][2].items() - os.environ.items(): monkeypatch.setenv(key, value)   # the kept tool starts with what it was handed
  assert install.keep() == (0, "")


def test_install_sh_dry_run_anywhere_among_its_arguments_runs_nothing(tmp_path):
  """--dry-run, first or last, prints what would run and passes the rest on, and neither uv nor `agent` runs."""
  put(tmp_path, "fake/uv", text=f"#!/usr/bin/env bash\necho \"$*\" >> {tmp_path}/ran\n")
  (tmp_path / "fake" / "uv").chmod(0o755)
  for arguments in (["--dry-run", "--profile", "none"], ["--profile", "none", "--dry-run"]):
    shown = subprocess.run(["bash", str(REPO / "install.sh"), *arguments], capture_output=True, check=False, cwd=tmp_path, env=os.environ | {"HOME": str(tmp_path), "PATH": f"{tmp_path / 'fake'}{os.pathsep}{os.environ['PATH']}"}, stdin=subprocess.DEVNULL, text=True)
    assert shown.returncode == 0 and shown.stdout.startswith("would run: uv tool install") and shown.stdout.endswith("agent install --profile none\n"), shown
  assert not (tmp_path / "ran").exists()


def test_an_install_through_uvx_keeps_agentkit_as_a_tool_and_installs_from_it(wheel, machine, tmp_path):
  """`uvx --from <wheel> agent install` leaves `agent` installed as a uv tool, and the install that ran is that tool's, so its hooks call it."""
  home = Path(machine["HOME"])
  (home / ".claude").mkdir(parents=True)
  ran = subprocess.run(["uvx", "--from", str(wheel), "agent", "install"], capture_output=True, check=True, cwd=tmp_path, env=machine, stdin=subprocess.DEVNULL, text=True).stdout
  assert ran.startswith("keep  agentkit as a uv tool") and (tmp_path / "bin" / "agent").is_file()
  assert f"  ok    {tmp_path / 'bin' / 'agent'}" in ran and (home / ".agents" / "hooks" / "inject.sh").is_file()   # the `agent` on PATH is the one that installed


def test_install_sh_installs_the_tool_then_wires_the_machine_and_reruns_cleanly(wheel, machine, tmp_path):
  """install.sh installs agentkit as a uv tool from AGENTS_SOURCE and runs that tool's `agent install`, and a second run changes nothing."""
  (Path(machine["HOME"]) / ".claude").mkdir(parents=True)
  run = lambda: subprocess.run(["bash", str(REPO / "install.sh")], capture_output=True, check=True, cwd=tmp_path, env=machine | {"AGENTS_SOURCE": str(wheel)}, start_new_session=True, stdin=subprocess.DEVNULL, text=True).stdout   # no terminal to hand over
  assert "wrote hooks block in settings.json" in run() and (tmp_path / "bin" / "agent").is_file()
  assert {line.split()[0] for line in run().splitlines() if line.strip()}.isdisjoint(words.CHANGED)


def test_install_asks_for_a_profile_once_and_only_at_a_terminal_with_gh_logged_in(fresh, installed, machine, tmp_path):
  """With no profile chosen, install asks only given a terminal and gh logged in, records whatever is answered, and never asks again."""
  home, fake_bin = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  quiet = fresh(["install"]).stdout
  assert "No profile on this machine" not in quiet and "No profile chosen" in quiet and not (home / ".agents" / "local.toml").exists()
  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], "", machine, tmp_path)
  assert code == 0 and "No profile on this machine" not in shown and "No profile chosen" in shown   # no gh yet, so the question waits

  fake_bin.mkdir()
  (fake_bin / "gh").write_text(FAKE_GH)
  (fake_bin / "gh").chmod(0o755)
  machine.update({"PATH": f"{fake_bin}{os.pathsep}{machine['PATH']}", "GH_LOG": str(tmp_path / "gh.log")})

  quiet = fresh(["install"]).stdout
  assert "No profile on this machine" not in quiet and "No profile chosen" in quiet and not (home / ".agents" / "profile").exists()   # gh is logged in now, but nobody is there to answer

  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], "none\n", machine, tmp_path)
  assert code == 0 and "No profile on this machine" in shown and "Answer (new):" in shown and tomllib.loads((home / ".agents" / "local.toml").read_text())["profile"]["path"] == ""
  code, shown = typed([str(installed / "agent"), "install"], "", machine, tmp_path)
  assert code == 0 and "No profile on this machine" not in shown and "No profile chosen" not in shown


def test_the_profile_question_defaults_to_new_and_takes_a_directory_as_typed(installed, machine, tmp_path):
  """Enter at the profile question makes a new profile and declines to publish it; a directory typed there is used where it is, and URL or DIR picked by number asks for one."""
  home, other, fake_bin, directory =Path(machine["HOME"]), tmp_path / "other", tmp_path / "fake", tmp_path / "dotfiles"
  (home / ".claude").mkdir(parents=True)
  (other / ".claude").mkdir(parents=True)
  fake_bin.mkdir()
  directory.mkdir()
  (fake_bin / "gh").write_text(FAKE_GH)
  (fake_bin / "gh").chmod(0o755)
  machine.update({"PATH": f"{fake_bin}{os.pathsep}{machine['PATH']}", "GH_LOG": str(tmp_path / "gh.log")})
  chosen = lambda where: tomllib.loads((where / ".agents" / "local.toml").read_text())["profile"]["path"]

  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], "\n\n", machine, tmp_path)
  assert code == 0 and (home / ".agents" / "profile" / "standards").is_dir() and chosen(home) == str((home / ".agents" / "profile").resolve())
  assert "repo create" not in (tmp_path / "gh.log").read_text()   # the second Enter declined to publish

  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], f"{directory}\n", machine | {"HOME": str(other)}, tmp_path)
  assert code == 0 and "Answer (new):" in shown and chosen(other) == str(directory.resolve()) and not (other / ".agents" / "profile").exists()

  bare = tmp_path / "mine.git"   # the URL and DIR rows, picked by number, ask for the address
  for command in (["git", "init", "-q", "--bare", "-b", "main", str(bare)], ["git", "clone", "-q", str(bare), str(tmp_path / "mine")], ["git", "-C", str(tmp_path / "mine"), "commit", "-q", "--allow-empty", "-m", "first"], ["git", "-C", str(tmp_path / "mine"), "push", "-q", "origin", "main"]): subprocess.run(command, capture_output=True, check=True, env=machine)
  for number, answer, place in (("2", bare, "by-url"), ("3", directory, "by-directory")):
    (tmp_path / place / ".claude").mkdir(parents=True)
    code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], f"{number}\n{answer}\n", machine | {"HOME": str(tmp_path / place)}, tmp_path)
    assert code == 0 and "no profile at" not in shown, shown
    assert chosen(tmp_path / place) == str((tmp_path / place / ".agents" / "profile").resolve() if number == "2" else directory.resolve())


def test_every_profile_answer_works_from_the_flag_at_a_terminal_or_not(fresh, installed, machine, tmp_path):
  """A URL is cloned and a directory used, at a terminal or not, and none is recorded; the flag is never asked about again."""
  home, bare, clone, directory = Path(machine["HOME"]), tmp_path / "mine.git", tmp_path / "mine", tmp_path / "dotfiles"
  (home / ".claude").mkdir(parents=True)
  directory.mkdir()
  for command in (["git", "init", "-q", "--bare", "-b", "main", str(bare)], ["git", "clone", "-q", str(bare), str(clone)], ["git", "-C", str(clone), "commit", "-q", "--allow-empty", "-m", "first"], ["git", "-C", str(clone), "push", "-q", "origin", "main"]): subprocess.run(command, capture_output=True, check=True, env=machine)
  chosen = lambda: tomllib.loads((home / ".agents" / "local.toml").read_text())["profile"]["path"]

  code, shown = typed([str(installed / "agent"), "install", "--profile", str(bare), "--backend", "claude"], "", machine, tmp_path)
  assert code == 0 and "No profile on this machine" not in shown and (home / ".agents" / "profile" / ".git").is_dir() and chosen() == str((home / ".agents" / "profile").resolve())
  fresh(["install", "--profile", str(directory)])
  assert chosen() == str(directory.resolve())
  fresh(["install", "--profile", "none"])
  assert chosen() == ""


def test_a_new_profile_is_made_and_published_privately_through_gh_only_when_asked(fresh, installed, machine, tmp_path):
  """`new` makes and commits a profile; with no terminal, or no yes, it prints the git commands, and given a yes at a terminal gh makes the repo private and pushes."""
  home, fake_bin = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  fake_bin.mkdir()
  (fake_bin / "gh").write_text(FAKE_GH)
  (fake_bin / "gh").chmod(0o755)
  machine.update({"PATH": f"{fake_bin}{os.pathsep}{machine['PATH']}", "GH_LOG": str(tmp_path / "gh.log"), "GH_REMOTE": str(tmp_path / "remote.git")})
  made = home / ".agents" / "profile"

  said = fresh(["install", "--profile", "new"]).stdout
  assert "a first commit" in said and f"git -C {made} push -u origin main" in said and "Make tester" not in said and (made / "standards").is_dir()
  assert "repo create" not in (tmp_path / "gh.log").read_text()   # no terminal, so never asked
  code, shown = typed([str(installed / "agent"), "install", "--profile", "new", "--backend", "claude"], "\n", machine, tmp_path)
  assert code == 0 and "Make tester/.agents.profile on GitHub, private, and push your profile there? [y/n] (n):" in shown and "repo create" not in (tmp_path / "gh.log").read_text()   # the default is no

  code, shown = typed([str(installed / "agent"), "install", "--profile", "new", "--backend", "claude"], "y\n", machine, tmp_path)
  assert code == 0 and "made  tester/.agents.profile, private, and pushed" in shown and "push -u origin main" not in shown
  assert f"repo create tester/.agents.profile --private --source {made} --remote origin --push" in (tmp_path / "gh.log").read_text()
  assert subprocess.run(["git", "-C", str(made), "status", "-sb"], capture_output=True, check=True, env=machine, text=True).stdout.startswith("## main...origin/main\n")


def test_a_profile_url_that_cannot_be_reached_stops_the_install_before_it_changes_anything(wheel, fresh, machine, tmp_path):
  """An unreachable profile URL is refused before anything is written, run directly or through uvx, which then keeps no tool either."""
  home, nowhere = Path(machine["HOME"]), str(tmp_path / "nowhere.git")
  (home / ".claude").mkdir(parents=True)
  assert "cannot reach" in fresh(["install", "--profile", nowhere], expect=1).stdout
  ran = subprocess.run(["uvx", "--from", str(wheel), "agent", "install", "--profile", nowhere], capture_output=True, check=False, cwd=tmp_path, env=machine, stdin=subprocess.DEVNULL, text=True)
  assert ran.returncode == 1 and "cannot reach" in ran.stderr and not (tmp_path / "bin" / "agent").exists()
  assert not (home / ".agents").exists() and list((home / ".claude").iterdir()) == []


def test_install_sets_the_backend_from_the_flag_or_asks_once_at_a_terminal(fresh, installed, machine, tmp_path):
  """An unknown --backend is refused before anything is written; with no terminal install only says how, at one it lists each backend as here or how to install it, and the answer lands in local.toml, or the profile once there is one."""
  home, fake_bin = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  fake_bin.mkdir()
  (fake_bin / "codex").write_text("#!/usr/bin/env bash\n")
  (fake_bin / "codex").chmod(0o755)
  machine["PATH"] = f"{fake_bin}{os.pathsep}{machine['PATH']}"
  default = lambda where: tomllib.loads(where.read_text()).get("backends", {}).get("default") if where.is_file() else None

  assert "there is no backend called nonesuch" in fresh(["install", "--backend", "nonesuch"], expect=2).stderr and not (home / ".agents").exists()
  assert "No backend: `agent install --backend <claude|codex|ollama>`" in fresh(["install"]).stdout and default(home / ".agents" / "local.toml") is None
  assert "FAIL  a default backend is set, so headless reviews (post-commit, doc-check) can run\n        -> `agent install --backend <claude|codex|ollama>`" in fresh(["doctor"], expect=1).stdout   # the check, as every label is, not the problem

  code, shown = typed([str(installed / "agent"), "install", "--profile", "none"], "ollama\n", machine, tmp_path)
  assert code == 0 and f"codex   OpenAI Codex CLI (found at {fake_bin / 'codex'})" in shown and "Reviews run on a model" in shown
  assert default(home / ".agents" / "local.toml") == "ollama"
  code, shown = typed([str(installed / "agent"), "install"], "", machine, tmp_path)
  assert code == 0 and "Reviews run on a model" not in shown   # asked once

  fresh(["install", "--profile", "new", "--backend", "codex"])
  assert default(home / ".agents" / "profile" / "config.toml") == "codex"


def test_the_backend_question_defaults_to_the_first_one_found_and_an_empty_answer_skips_when_none_is(installed, machine, tmp_path):
  """With none of the backends here, Enter records nothing; with one here, Enter records it, the question showing it as the default."""
  home, fake_bin = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  (home / ".agents").mkdir(parents=True)
  fake_bin.mkdir()
  (home / ".agents" / "local.toml").write_text('[profile]\npath = ""\n\n[backends.claude]\nkind = "cli"\nargv = ["no-claude"]\n\n[backends.codex]\nkind = "cli"\nargv = ["no-codex"]\n\n[backends.ollama]\nkind = "http"\nurl = "http://localhost:1/none"\n')   # none of the three can be found
  default = lambda: tomllib.loads((home / ".agents" / "local.toml").read_text()).get("backends", {}).get("default")

  code, shown = typed([str(installed / "agent"), "install"], "\n", machine, tmp_path)
  assert code == 0 and "Answer:" in shown and default() is None

  (fake_bin / "no-codex").write_text("#!/usr/bin/env bash\n")
  (fake_bin / "no-codex").chmod(0o755)
  machine["PATH"] = f"{fake_bin}{os.pathsep}{machine['PATH']}"
  code, shown = typed([str(installed / "agent"), "install"], "\n", machine, tmp_path)
  assert code == 0 and "Answer (codex):" in shown and default() == "codex"


def test_a_review_with_no_backend_says_how_without_a_terminal_and_offers_the_question_at_one(fresh, installed, machine, tmp_path):
  """With no default, a review run unattended stops and names the fix, writing nothing; at a terminal it asks, and a yes runs the install's question."""
  home, here = Path(machine["HOME"]), tmp_path / "elsewhere"
  subprocess.run(["git", "init", "-q", str(here)], check=True, env=machine)
  (here / "x.py").write_text("x = 1\n")
  (home / ".agents").mkdir(parents=True)
  (home / ".agents" / "local.toml").write_text('[profile]\npath = ""\n\n[backends.echo]\nlabel = "Echo"\nkind = "cli"\nargv = ["true"]\nmodels = { text = "x", code-large = "x" }\n')
  default = lambda: tomllib.loads((home / ".agents" / "local.toml").read_text()).get("backends", {}).get("default")

  stopped = fresh(["sub", "review", "x.py"], expect=2).stderr
  assert "no default backend is set" in stopped and "agent install --backend <" in stopped and default() is None
  code, shown = typed([str(installed / "agent"), "sub", "review", "x.py"], "n\n", machine, here)
  assert code == 2 and "Set one now? [y/n] (y):" in shown and default() is None

  code, shown = typed([str(installed / "agent"), "sub", "run", "doc-check", "x.py"], "\necho\n", machine, here)   # Enter is the yes
  assert code != -signal.SIGKILL and "echo    Echo (found at" in shown and default() == "echo"


def test_an_install_with_no_git_says_so_rather_than_crash_reaching_a_profile(monkeypatch, tmp_path):
  """With git missing, preflight names it and does not run git to check a profile URL, which would raise instead."""
  fake(tmp_path, monkeypatch, "jq", "exit 0")   # every tool preflight looks for but git
  monkeypatch.setenv("PATH", str(tmp_path / "fake"))
  monkeypatch.setenv("HOME", str(tmp_path))
  assert any(problem.startswith("missing git") for problem in install.preflight("git@github.com:someone/.agents.profile.git"))


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


def test_a_global_hook_git_cannot_write_is_a_failure_with_gits_reason_not_a_traceback(home, tmp_path, monkeypatch):
  """A git config that cannot be written, set or unset, returns 1 and the last line git printed."""
  if os.geteuid() == 0: pytest.skip("root writes into a read-only folder")
  (locked := tmp_path / "locked").mkdir()
  (gitconfig := locked / "gitconfig").write_text("")
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
  locked.chmod(0o555)   # git writes a lock file beside the config, which a read-only folder refuses
  try:
    code, message = install.global_install()
    assert code == 1 and message.startswith("could not set core.hooksPath: ") and "lock" in message
    locked.chmod(0o755)
    gitconfig.write_text(f"[core]\n  hooksPath = {install.GITHOOKS}\n")
    locked.chmod(0o555)
    code, message = install.global_uninstall()
    assert code == 1 and message.startswith("could not unset core.hooksPath: ") and install.global_hooks_path() == str(install.GITHOOKS)
  finally: locked.chmod(0o755)


def test_the_global_hook_is_refused_when_there_are_no_hooks_to_point_at(home, tmp_path, monkeypatch):
  """With the hooks directory missing, the global install says how to get it and leaves git's config alone."""
  monkeypatch.setattr(install, "GITHOOKS", tmp_path / "nowhere")
  code, message = install.global_install()
  assert code == 1 and "run `agent install` first" in message and install.global_hooks_path() == ""


def test_the_repo_hook_goes_beside_any_hook_quotes_its_arguments_and_uninstall_removes_only_ours(tmp_path):
  """Install moves a hook that is not ours aside without clobbering an older backup, writes an executable shim with shell-quoted arguments, and uninstall removes only that shim."""
  repo = git(tmp_path / "repo")
  hook = repo / ".git" / "hooks" / "post-commit"
  hook.parent.mkdir(parents=True, exist_ok=True)
  hook.write_text("echo mine\n")
  hook.with_name("post-commit.bak").write_text("echo older\n")
  subprocess.run(["git", "config", "core.hooksPath", str(tmp_path / "elsewhere")], cwd=repo, check=True)   # where git reads hooks, but not where `githooks/_dispatch` looks for the repo's own
  assert install.repo_hook(repo) == hook and not install.repo_hook_ours(repo)
  assert install.repo_uninstall(repo) == (1, f"not ours, leaving it alone: {hook}") and hook.read_text() == "echo mine\n"

  code, lines = install.repo_install(repo, "auto", "")
  assert code == 0 and lines[:2] == ["moved the hook already there aside to post-commit.bak1", f"installed {hook}"] and len(lines) == 3
  assert lines[2] == f"  auto reviews each commit into {repo / '.agents' / '.reviews' / 'reviews.duckdb'}"
  assert sorted(saved.read_text() for saved in hook.parent.glob("post-commit.bak*")) == ["echo mine\n", "echo older\n"]   # never eaten
  assert os.access(hook, os.X_OK) and install.repo_hook_ours(repo)

  assert len(install.repo_install(repo, "a b; echo hi", "")[1]) == 2   # ours already, so nothing to move aside
  assert "post-commit.sh\" 'a b; echo hi' ''\n" in hook.read_text()
  assert install.repo_uninstall(repo) == (0, f"removed {hook}") and not hook.exists()
  assert install.repo_uninstall(repo) == (1, f"nothing installed at {hook}")

  shutil.rmtree(hook.parent)   # a repo made without git's template hooks
  assert install.repo_install(repo, "auto", "")[0] == 0 and install.repo_hook_ours(repo)


def test_the_repo_hook_is_refused_where_the_repos_own_core_hooks_path_means_git_never_reads_it(home, tmp_path):
  """A repo-local core.hooksPath, such as husky's, is where git runs hooks from, so install refuses rather than write a shim git never runs; one at our hooks needs nothing."""
  repo = git(tmp_path / "repo")
  subprocess.run(["git", "config", "core.hooksPath", ".husky"], cwd=repo, check=True)
  assert ".husky" in agent(["hook", "install"], cwd=repo, expect=1).stderr and not install.repo_hook(repo).exists()
  subprocess.run(["git", "config", "core.hooksPath", str(install.GITHOOKS)], cwd=repo, check=True)
  assert "already reviewed" in agent(["hook", "install"], cwd=repo).stderr and not install.repo_hook(repo).exists()


def test_doctor_reads_a_settings_json_that_is_not_an_object_and_checks_the_git_dispatch_can_run(fresh, machine):
  """A hook of the user's beside the hub's is not drift; a settings.json that is a list is a failure, not a crash; and a `_dispatch` that lost +x fails."""
  home = Path(machine["HOME"])
  (home / ".claude").mkdir(parents=True)
  fresh(["install"])
  settings = home / ".claude" / "settings.json"
  settings.write_text(json.dumps((live := json.loads(settings.read_text())) | {"hooks": live["hooks"] | {"Notification": [{"hooks": [{"type": "command", "command": "~/bin/mine.sh"}]}]}}))
  assert "ok    the hub's hooks in Claude Code's settings.json match settings.hooks.json" in fresh(["doctor"], expect=None).stdout

  settings.write_text("[1, 2]")
  (home / ".agents" / "githooks" / "_dispatch").chmod(0o644)
  doctor = fresh(["doctor"], expect=1)
  assert "Traceback" not in doctor.stderr and "is not a JSON object" in doctor.stdout and "FAIL  _dispatch is executable" in doctor.stdout, doctor.stdout


def test_every_script_that_runs_on_its_own_is_strict():
  """Each hook, githook and installer run as a program starts with `set -euo pipefail`; a library a hook sources has no shebang and is left to its caller."""
  scripts = [path for path in [*REPO.glob("hooks/*.sh"), REPO / "githooks" / "_dispatch", REPO / "install.sh"] if path.read_text().startswith("#!")]
  assert len(scripts) > 3 and [path.name for path in scripts if "\nset -euo pipefail\n" not in path.read_text()] == []


def test_the_repo_hook_in_a_linked_worktree_goes_where_git_reads_it_and_runs_on_a_commit(home, tmp_path):
  """A linked worktree's `.git` is a file, so install writes into the main repo's hooks folder, where git runs it for a commit in either checkout, and uninstall from the other checkout removes it."""
  (home / ".agents" / "hooks").mkdir(parents=True)
  (home / ".agents" / "hooks" / "post-commit.sh").write_text(f"#!/usr/bin/env bash\necho \"ran $*\" >> {tmp_path}/marks\n")   # where the real review would start, so no model is called
  (home / ".agents" / "hooks" / "post-commit.sh").chmod(0o755)
  main, linked, identity = git(tmp_path / "main"), tmp_path / "linked", ["-c", "user.name=T", "-c", "user.email=t@t.io"]
  subprocess.run(["git", *identity, "commit", "-q", "--allow-empty", "-m", "first"], cwd=main, check=True)
  subprocess.run(["git", "worktree", "add", "-q", str(linked)], cwd=main, check=True)
  assert (linked / ".git").is_file() and install.repo_hook(linked).resolve() == (main / ".git" / "hooks" / "post-commit").resolve()

  code, lines = install.repo_install(linked, "auto", "ollama")
  assert code == 0 and lines[0] == f"installed {install.repo_hook(linked)}" and install.repo_hook_ours(main) and install.repo_hook_ours(linked)
  subprocess.run(["git", *identity, "commit", "-q", "--allow-empty", "-m", "in the worktree"], cwd=linked, check=True)
  subprocess.run(["git", *identity, "commit", "-q", "--allow-empty", "-m", "in the main checkout"], cwd=main, check=True)
  assert (tmp_path / "marks").read_text() == "ran auto ollama\nran auto ollama\n"

  assert install.repo_uninstall(main) == (0, f"removed {install.repo_hook(main)}") and not install.repo_hook_ours(linked)
  assert install.repo_uninstall(linked)[0] == 1


def test_a_commit_runs_the_repos_own_hook_first_and_is_reviewed_only_where_a_note_says_so(home, tmp_path):
  """The repo's own hook runs first and a failing pre-commit blocks; no review without a note, and ours never twice."""
  (home / ".agents" / "hooks").mkdir(parents=True)
  (home / ".agents" / "hooks" / "post-commit.sh").write_text(f"#!/usr/bin/env bash\necho reviewed >> {tmp_path}/marks\n")   # where the real review would start, so no model is called
  (home / ".agents" / "hooks" / "post-commit.sh").chmod(0o755)
  (home / ".agents" / "hooks" / "log.sh").symlink_to(hub.BUNDLED / "hooks" / "log.sh")   # the real logger, into this HOME
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
