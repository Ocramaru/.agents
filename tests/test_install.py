"""The installer and the global git hooks, run against a throwaway HOME and a throwaway git config."""

import json, os, shutil, signal, subprocess, sys, tomllib, uuid, zipfile
from pathlib import Path

import pytest
from conftest import REPO, git, note, put, typed

from agentkit import hooks, hub, install


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
  assert {line.strip().partition(" ")[0] for line in lines} & set(install.CHANGED) == {"link", "saved", "wrote", "point"}   # the words install says a change with

  code, lines = install.run([])
  changes = [line for line in lines if line.strip().partition(" ")[0] in install.CHANGED]
  assert code == 0 and changes == [], changes
  assert f"  ok    .agents -> {hub.HOME}" in lines   # a second run says the link it found

  for text in ("{not json", "[1, 2]"):
    settings.write_text(text)
    assert install.hooks(settings)[0].startswith("skip  hooks block") and settings.read_text() == text


def test_an_installed_package_reads_its_own_copy_and_keeps_state_in_home(tmp_path):
  """A package carrying `bundled/` reads standards, reviewers and config from it and keeps state in ~/.agents; a checkout is both."""
  site = tmp_path / "site"
  shutil.copytree(hub.BUNDLED / "agentkit", site / "agentkit", ignore=shutil.ignore_patterns("__pycache__"))
  (site / "agentkit" / "bundled").mkdir()
  shown = subprocess.run([sys.executable, "-P", "-c", "from agentkit import hub, profile; print(hub.BUNDLED, hub.HOME, hub.CONFIG, hub.LOCAL, profile.DEFAULT, hub.STANDARDS, hub.REVIEWERS)"], cwd=tmp_path, capture_output=True, check=True, text=True, env={**os.environ, "PYTHONPATH": str(site), "HOME": str(tmp_path / "home")}).stdout.split()
  bundled, home = (site / "agentkit" / "bundled").resolve(), tmp_path / "home" / ".agents"
  assert shown == [str(path) for path in (bundled, home, bundled / "config.toml", home / "local.toml", home / "profile", bundled / "standards", bundled / "agents")]
  assert hub.BUNDLED == hub.HOME == REPO   # a checkout is its own state


def test_the_wheel_carries_the_package_and_every_bundled_file_and_nothing_of_this_machine(wheel):
  """The wheel holds agentkit, the hub's tracked files under agentkit/bundled with the hooks executable, and the `agent` entry point."""
  tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "agentkit", "AGENTS.md", "agents", "commands", "config.toml", "githooks", "hooks", "settings.hooks.json", "standards", "templates"], cwd=REPO, capture_output=True, check=True, text=True).stdout.split()
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

  assert {line.split()[0] for line in fresh(["install"]).stdout.splitlines() if line.strip()}.isdisjoint(install.CHANGED)
  assert "ok    hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=None).stdout
  (home / ".agents" / "hooks" / "inject.sh").write_text("stale\n")
  assert "FAIL  hooks, githooks, commands and AGENTS.md in" in fresh(["doctor"], expect=1).stdout
  assert "copy  1 file into" in fresh(["install"]).stdout


def test_an_installs_stale_copies_are_files_nested_ones_included(tmp_path, monkeypatch):
  """stale() names every bundled file beneath the fixed paths whose copy is missing or differs, and never a directory, which a copy would fail on."""
  bundled, home = tmp_path / "bundled", tmp_path / "home"
  put(bundled, "AGENTS.md", "hooks/a.sh", "githooks/_dispatch", "commands/nested/b.md")
  put(home, "hooks/a.sh")
  monkeypatch.setattr(hub, "INSTALLED", True)
  monkeypatch.setattr(hub, "BUNDLED", bundled)
  monkeypatch.setattr(hub, "HOME", home)
  assert [str(source.relative_to(bundled)) for source in install.stale()] == ["AGENTS.md", "commands/nested/b.md", "githooks/_dispatch"]


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
  assert f"already current at {number}" in agent("update")

  (source / "pyproject.toml").write_text((source / "pyproject.toml").read_text().replace(f'version = "{number}"', f'version = "{number}.1"'))
  (source / "hooks" / "forget.sh").write_text((source / "hooks" / "forget.sh").read_text() + "# newer\n")
  updated = agent("update")
  assert f"upgraded {number} -> {number}.1" in updated and "copy  1 file into" in updated
  assert (home / ".agents" / "hooks" / "forget.sh").read_text().endswith("# newer\n")

  (source / "pyproject.toml").write_text((source / "pyproject.toml").read_text().replace(f'version = "{number}.1"', f'version = "{number}.2"'))
  (home / ".agents" / "agentkit").mkdir()   # what makes the new version's install refuse: ~/.agents looks like a clone
  failed = subprocess.run([str(tmp_path / "bin" / "agent"), "update"], capture_output=True, check=False, cwd=tmp_path, env=machine, stdin=subprocess.DEVNULL, text=True)
  assert failed.returncode == 1 and f"FAIL   .agents: upgraded {number}.1 -> {number}.2, but its install did not finish (cannot install: " in failed.stdout and "is a clone of .agents" in failed.stdout


def scripted(monkeypatch, **answers) -> list:
  """Stand in for uv and the new `agent`: install's subprocess answers by the first word after the program (`uv` for uv itself), and every call lands in the returned list."""
  calls = []

  def run(argv, **options):
    calls.append((argv, options))
    answer = answers[argv[0] if argv[0] == "uv" else argv[1]]
    if isinstance(answer, Exception): raise answer
    return subprocess.CompletedProcess(argv, *answer)

  monkeypatch.setattr(install.subprocess, "run", run)
  monkeypatch.setattr(hub, "version", lambda: "1.0")
  return calls


def test_upgrade_installs_nothing_when_the_version_did_not_move(monkeypatch):
  """When the upgraded code reports the version it had, upgrade says so and never runs its install."""
  calls = scripted(monkeypatch, uv=(0, "", ""), **{"--version": (0, "agentkit 1.0\n", "")})
  assert install.upgrade() == (0, ["ok     .agents: already current at 1.0"])
  assert [argv[:3] for argv, _ in calls] == [["uv", "tool", "upgrade"], [str(install.CLI), "--version"]]


def test_upgrade_lists_what_the_new_install_changed_and_asks_it_nothing(monkeypatch):
  """A moved version runs the new `agent install --changes` with stdin closed, and its lines follow the upgrade line indented."""
  calls = scripted(monkeypatch, uv=(0, "", ""), **{"--version": (0, "agentkit 1.1\n", ""), "install": (0, "copy  1 file into ~/.agents\nwrote hooks block in settings.json\n\n", "")})
  assert install.upgrade() == (0, ["ok     .agents: upgraded 1.0 -> 1.1", "       copy  1 file into ~/.agents", "       wrote hooks block in settings.json"])
  argv, options = calls[-1]
  assert argv == [str(install.CLI), "install", "--changes"] and options["stdin"] == subprocess.DEVNULL


def test_upgrade_fails_with_the_last_line_uv_or_the_new_install_gave(monkeypatch):
  """A missing or failing uv, and an install that exits non-zero, each give code 1 and the reason in one line; the install's own lines follow."""
  scripted(monkeypatch, uv=FileNotFoundError("uv"))
  assert install.upgrade() == (1, ["FAIL   .agents: uv is not on PATH"])
  scripted(monkeypatch, uv=(2, "", "warning: x\nerror: no index\n\n"))
  assert install.upgrade() == (1, ["FAIL   .agents: error: no index"])

  scripted(monkeypatch, uv=(0, "", ""), **{"--version": (0, "agentkit 1.1\n", ""), "install": (1, "cannot install: ~/.agents is a clone\n", "")})
  assert install.upgrade() == (1, ["FAIL   .agents: upgraded 1.0 -> 1.1, but its install did not finish (cannot install: ~/.agents is a clone); run `agent install`", "       cannot install: ~/.agents is a clone"])
  scripted(monkeypatch, uv=(0, "", ""), **{"--version": (0, "agentkit 1.1\n", ""), "install": (1, "", "")})
  assert install.upgrade() == (1, ["FAIL   .agents: upgraded 1.0 -> 1.1, but its install did not finish (it said nothing); run `agent install`"])


def test_handing_over_runs_the_kept_agent_with_these_arguments_and_a_path_without_uvxs_own_environment(monkeypatch, tmp_path):
  """The kept `agent` replaces this process with this process's arguments, and PATH loses every entry that is uvx's `sys.prefix/bin`, a link to it included, and nothing else."""
  alias, calls = tmp_path / "alias", []
  alias.symlink_to(Path(sys.prefix) / "bin")
  monkeypatch.setenv("PATH", os.pathsep.join([str(alias), str(tmp_path / "first"), str(Path(sys.prefix) / "bin"), str(tmp_path / "second")]))
  monkeypatch.setattr(sys, "argv", ["agent", "install", "--profile", "none"])
  monkeypatch.setattr(install.os, "execve", lambda *call: calls.append(call))
  install.hand_over("/kept/agent")
  assert calls == [("/kept/agent", ["/kept/agent", "install", "--profile", "none"], os.environ | {"PATH": os.pathsep.join([str(tmp_path / "first"), str(tmp_path / "second")])})]


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
  assert {line.split()[0] for line in run().splitlines() if line.strip()}.isdisjoint(install.CHANGED)


def test_install_asks_for_a_profile_once_and_only_at_a_terminal_with_gh_logged_in(fresh, installed, machine, tmp_path):
  """With no profile chosen, install asks only given a terminal and gh logged in, records whatever is answered, and never asks again."""
  home, fake = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  quiet = fresh(["install"]).stdout
  assert "No profile on this machine" not in quiet and "No profile chosen" in quiet and not (home / ".agents" / "local.toml").exists()
  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], "", machine, tmp_path)
  assert code == 0 and "No profile on this machine" not in shown and "No profile chosen" in shown   # no gh yet, so the question waits

  fake.mkdir()
  (fake / "gh").write_text(FAKE_GH)
  (fake / "gh").chmod(0o755)
  machine.update({"PATH": f"{fake}{os.pathsep}{machine['PATH']}", "GH_LOG": str(tmp_path / "gh.log")})

  quiet = fresh(["install"]).stdout
  assert "No profile on this machine" not in quiet and "No profile chosen" in quiet and not (home / ".agents" / "profile").exists()   # gh is logged in now, but nobody is there to answer

  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], "none\n", machine, tmp_path)
  assert code == 0 and "No profile on this machine" in shown and "Answer (new):" in shown and tomllib.loads((home / ".agents" / "local.toml").read_text())["profile"]["path"] == ""
  code, shown = typed([str(installed / "agent"), "install"], "", machine, tmp_path)
  assert code == 0 and "No profile on this machine" not in shown and "No profile chosen" not in shown


def test_the_profile_question_defaults_to_new_and_takes_a_directory_as_typed(installed, machine, tmp_path):
  """Enter at the profile question makes a new profile and declines to publish it; a directory typed there is used where it is."""
  home, other, fake, directory = Path(machine["HOME"]), tmp_path / "other", tmp_path / "fake", tmp_path / "dotfiles"
  (home / ".claude").mkdir(parents=True)
  (other / ".claude").mkdir(parents=True)
  fake.mkdir()
  directory.mkdir()
  (fake / "gh").write_text(FAKE_GH)
  (fake / "gh").chmod(0o755)
  machine.update({"PATH": f"{fake}{os.pathsep}{machine['PATH']}", "GH_LOG": str(tmp_path / "gh.log")})
  chosen = lambda where: tomllib.loads((where / ".agents" / "local.toml").read_text())["profile"]["path"]

  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], "\n\n", machine, tmp_path)
  assert code == 0 and (home / ".agents" / "profile" / "standards").is_dir() and chosen(home) == str((home / ".agents" / "profile").resolve())
  assert "repo create" not in (tmp_path / "gh.log").read_text()   # the second Enter declined to publish

  code, shown = typed([str(installed / "agent"), "install", "--backend", "claude"], f"{directory}\n", machine | {"HOME": str(other)}, tmp_path)
  assert code == 0 and "Answer (new):" in shown and chosen(other) == str(directory.resolve()) and not (other / ".agents" / "profile").exists()


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
  home, fake = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  fake.mkdir()
  (fake / "gh").write_text(FAKE_GH)
  (fake / "gh").chmod(0o755)
  machine.update({"PATH": f"{fake}{os.pathsep}{machine['PATH']}", "GH_LOG": str(tmp_path / "gh.log"), "GH_REMOTE": str(tmp_path / "remote.git")})
  made = home / ".agents" / "profile"

  said = fresh(["install", "--profile", "new"]).stdout
  assert "a first commit" in said and f"git -C {made} push -u origin main" in said and "Make tester" not in said and (made / "standards").is_dir()
  assert "repo create" not in (tmp_path / "gh.log").read_text()   # no terminal, so never asked
  code, shown = typed([str(installed / "agent"), "install", "--profile", "new", "--backend", "claude"], "\n", machine, tmp_path)
  assert code == 0 and "Make tester/.agents.profile on GitHub, private, and push your profile there? [y/n] (n):" in shown and "repo create" not in (tmp_path / "gh.log").read_text()   # the default is no

  code, shown = typed([str(installed / "agent"), "install", "--profile", "new", "--backend", "claude"], "y\n", machine, tmp_path)
  assert code == 0 and "made  tester/.agents.profile, private, and pushed" in shown and "push -u origin main" not in shown
  assert f"repo create tester/.agents.profile --private --source {made} --remote origin --push" in (tmp_path / "gh.log").read_text()
  assert subprocess.run(["git", "-C", str(made), "status", "-sb"], capture_output=True, check=True, text=True).stdout.startswith("## main...origin/main\n")


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
  home, fake = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  fake.mkdir()
  (fake / "codex").write_text("#!/usr/bin/env bash\n")
  (fake / "codex").chmod(0o755)
  machine["PATH"] = f"{fake}{os.pathsep}{machine['PATH']}"
  default = lambda where: tomllib.loads(where.read_text()).get("backends", {}).get("default") if where.is_file() else None

  assert "there is no backend called nonesuch" in fresh(["install", "--backend", "nonesuch"], expect=2).stderr and not (home / ".agents").exists()
  assert "No backend: `agent install --backend <claude|codex|ollama>`" in fresh(["install"]).stdout and default(home / ".agents" / "local.toml") is None
  assert "FAIL  a default backend is set" in fresh(["doctor"], expect=1).stdout

  code, shown = typed([str(installed / "agent"), "install", "--profile", "none"], "ollama\n", machine, tmp_path)
  assert code == 0 and f"codex   OpenAI Codex CLI (found at {fake / 'codex'})" in shown and "Reviews run on a model" in shown
  assert default(home / ".agents" / "local.toml") == "ollama"
  code, shown = typed([str(installed / "agent"), "install"], "", machine, tmp_path)
  assert code == 0 and "Reviews run on a model" not in shown   # asked once

  fresh(["install", "--profile", "new", "--backend", "codex"])
  assert default(home / ".agents" / "profile" / "config.toml") == "codex"


def test_the_backend_question_defaults_to_the_first_one_found_and_an_empty_answer_skips_when_none_is(installed, machine, tmp_path):
  """With none of the backends here, Enter records nothing; with one here, Enter records it, the question showing it as the default."""
  home, fake = Path(machine["HOME"]), tmp_path / "fake"
  (home / ".claude").mkdir(parents=True)
  (home / ".agents").mkdir(parents=True)
  fake.mkdir()
  (home / ".agents" / "local.toml").write_text('[profile]\npath = ""\n\n[backends.claude]\nkind = "cli"\nargv = ["no-claude"]\n\n[backends.codex]\nkind = "cli"\nargv = ["no-codex"]\n\n[backends.ollama]\nkind = "http"\nurl = "http://localhost:1/none"\n')   # none of the three can be found
  default = lambda: tomllib.loads((home / ".agents" / "local.toml").read_text()).get("backends", {}).get("default")

  code, shown = typed([str(installed / "agent"), "install"], "\n", machine, tmp_path)
  assert code == 0 and "Answer:" in shown and default() is None

  (fake / "no-codex").write_text("#!/usr/bin/env bash\n")
  (fake / "no-codex").chmod(0o755)
  machine["PATH"] = f"{fake}{os.pathsep}{machine['PATH']}"
  code, shown = typed([str(installed / "agent"), "install"], "\n", machine, tmp_path)
  assert code == 0 and "Answer (codex):" in shown and default() == "codex"


def test_a_review_with_no_backend_says_how_without_a_terminal_and_offers_the_question_at_one(fresh, installed, machine, tmp_path):
  """With no default, a review run unattended stops and names the fix, writing nothing; at a terminal it asks, and a yes runs the install's question."""
  home, here = Path(machine["HOME"]), tmp_path / "elsewhere"
  subprocess.run(["git", "init", "-q", str(here)], check=True)
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


def test_an_install_with_no_git_says_so_rather_than_crash_reaching_a_profile(monkeypatch):
  """With git missing, preflight names it and does not run git to check a profile URL, which would raise instead."""
  def no_git(argv, **options):
    if argv[0] == "git": raise FileNotFoundError("git")
    return subprocess.CompletedProcess(argv, 0, "", "")
  monkeypatch.setattr(install.shutil, "which", lambda tool: None if tool == "git" else f"/usr/bin/{tool}")
  monkeypatch.setattr(install.subprocess, "run", no_git)
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
