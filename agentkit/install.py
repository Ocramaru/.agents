"""Wire .agents into the coding agents on this machine, and git into every repo that opts in.
A clone is linked, so `git pull` updates a machine without a reinstall; an install copies what agents name by path into ~/.agents, since a link into the tool's venv dangles when its Python changes.
Anything in place that is not ours is moved aside rather than overwritten, and a second run changes nothing.
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from agentkit import config, git, hub, profile as _profile, reviews, words

GITHOOKS = hub.HOME / "githooks"
CLI = Path(sys.executable).parent / "agent" if hub.INSTALLED else hub.BUNDLED / "bin" / "agent"   # the `agent` this code runs as, and the one hooks should find
RECORD = hub.HOME / ".cli"   # an install's CLI by absolute path, which hooks/log.sh reads before PATH; a clone's hooks find its bin/agent
COPIED = hub.HOME / ".copied"   # each file an install copied into ~/.agents, by its sha256, so the next install knows which are still as it left them
HANDED_OVER = "AGENTS_HANDED_OVER"   # set for the kept tool, which never keeps itself again: a tool directory inside uv's cache looks like uvx's own
FIXED = ("AGENTS.md", "commands", "githooks", "hooks")   # what agents and git name by path under ~/.agents, so an install keeps a copy there
POINTER = "The `.agents/` notes convention, the standards, and how they load:"
HOOK_MARK = "# installed by `agent hook install`"
HOOK = f"""#!/usr/bin/env bash
{HOOK_MARK} -- review each commit into this repo's reviews.
exec "$HOME/.agents/hooks/post-commit.sh" {{agent}} {{backend}}
"""


def config_dir(target: str) -> Path:
  """An agent's config directory, such as `~/.claude`."""
  if target == "claude": return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
  return Path.home() / f".{target}"


def home(path: Path) -> str:
  """A path relative to home, for output."""
  try: return str(Path(path).relative_to(Path.home()))
  except ValueError: return str(path)


def backup(path: Path) -> Path:
  """The first backup name for `path` not already taken, so an older backup is never clobbered."""
  name, number = path.with_name(path.name + ".bak"), 1
  while name.exists() or name.is_symlink(): name, number = path.with_name(f"{path.name}.bak{number}"), number + 1
  return name


def link(source: Path, destination: Path) -> list[str]:
  """Symlink `destination` to `source`, setting aside what was there."""
  destination.parent.mkdir(parents=True, exist_ok=True)
  if destination.is_symlink() and destination.resolve() == source.resolve(): return [words.status("ok", home(destination))]
  out = []
  if destination.exists() or destination.is_symlink(): out.append(words.status("saved", home(destination.rename(backup(destination)))))
  destination.symlink_to(source)
  return out + [words.status("link", home(destination))]


def point_at(file: Path) -> list[str]:
  """Append pointers to the hub's AGENTS.md, then the profile's, to an instructions file, never replacing its notes.

  The profile's comes last, so how you work refines the convention.
  """
  convention, mine = f"@{hub.HOME}/AGENTS.md", _profile.file("AGENTS.md")
  have = file.read_text(encoding="utf-8") if file.is_file() else ""
  add = ([] if convention in have else [convention]) + ([f"@{mine}"] if mine and f"@{mine}" not in have else [])
  if not add: return [words.status("ok", f"pointer in {home(file)}")]

  file.parent.mkdir(parents=True, exist_ok=True)
  separator = "" if not have or have.endswith("\n") else "\n"   # never join the file's last line
  if convention in add: separator += ("\n" if have.strip() else "") + f"{POINTER}\n\n"
  with file.open("a", encoding="utf-8") as handle: handle.write(separator + "\n".join(add) + "\n")
  return [words.status("point", home(file) + (" (and your profile)" if mine and f"@{mine}" in add else ""))]


INSTRUCTIONS = {"claude": "CLAUDE.md", "codex": "AGENTS.md", "gemini": "GEMINI.md"}
COMMANDS = {"claude": "commands", "codex": "prompts"}   # where each agent finds the slash commands


def repoint(old: Path | None) -> list[str]:
  """Move each agent's pointer from the old profile's AGENTS.md to the current one's, or drop it when there is none.

  Installing only appends, so without this a moved profile leaves every agent importing the old file.
  """
  new = _profile.file("AGENTS.md")
  if old is None or old == new: return []

  out = []
  for target, name in INSTRUCTIONS.items():
    file = config_dir(target) / name
    if not file.is_file() or f"@{old}" not in (text := file.read_text(encoding="utf-8")): continue
    # line by line, so a dropped pointer takes its whole line, whatever whitespace it had
    file.write_text("".join((line.replace(f"@{old}", f"@{new}") if new else line) for line in text.splitlines(keepends=True) if new or line.strip() != f"@{old}"), encoding="utf-8")   # with no profile, only the pointer's own line goes
    out.append(words.status("point", f"{home(file)} at {home(new) if new else 'no profile'}"))
  return out


def claude_block() -> dict:
  """The hooks block for Claude Code's settings.json: settings.hooks.json, with Read added to inject's matcher when `[inject] read` is on.
  The switch is in the matcher rather than the hook, so with it off a Read starts no hook at all."""
  ours = json.loads(hub.HOOKS_BLOCK.read_text(encoding="utf-8"))
  if config.section("inject").get("read"):
    for entry in ours.get("PreToolUse", []):
      if any(hook.get("command", "").endswith("/inject.sh") for hook in entry.get("hooks", [])): entry["matcher"] = f"{entry['matcher']}|Read"
  return ours


def partition(live: object) -> tuple[dict, dict]:
  """A settings.json hooks block as (the hub's hooks, everyone else's), each by event with its groups in order and their other keys kept.
  The hub's are known by the script they run, `~/.agents/hooks/*.sh` however home is spelled; what is not shaped like a hooks block holds none of them and is dropped."""
  def hubs(hook: object) -> bool:
    if not isinstance(hook, dict): return False
    try: command = shlex.split(str(hook.get("command", "")))   # quoted, or run through bash, it is the same script
    except ValueError: return False   # a command shlex cannot read is the user's
    if command[:1] in (["bash"], ["sh"], ["env"]): command = command[1:]
    return bool(command) and (script := Path(os.path.expandvars(os.path.expanduser(command[0])))).suffix == ".sh" and script.parent == Path.home() / hub.AGENTS_DIR / "hooks"

  ours, theirs = {}, {}
  for event, groups in (live.items() if isinstance(live, dict) else ()):
    for group in (groups if isinstance(groups, list) else ()):
      listed = group.get("hooks") if isinstance(group, dict) else None
      found = [hook for hook in listed if hubs(hook)] if isinstance(listed, list) else []
      if found: ours.setdefault(event, []).append(group | {"hooks": found})
      if not found or len(found) < len(listed): theirs.setdefault(event, []).append(group | {"hooks": [hook for hook in listed if not hubs(hook)]} if found else group)
  return ours, theirs


def claude_hooks(settings: Path) -> list[str]:
  """Bring the hub's hooks in Claude Code's settings.json to the bundle's, adding, updating and removing only those, and leave every other hook and key as it was."""
  ours = claude_block()
  try: data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
  except ValueError: data = None
  if not isinstance(data, dict): return [words.status("skip", f"hooks block: {home(settings)} is not a JSON object, so it is left as it is; fix it and run this again")]
  found, theirs = partition(data.get("hooks"))
  if found == ours: return [words.status("ok", "hooks block in settings.json")]

  out = []
  if settings.is_file():
    saved = backup(settings)   # a free name, so an earlier install's backup survives
    saved.write_text(settings.read_text(encoding="utf-8"), encoding="utf-8")
    out.append(words.status("saved", f"{home(saved)}, your settings.json as it was"))

  data["hooks"] = {event: [*theirs.get(event, []), *ours.get(event, [])] for event in dict.fromkeys([*theirs, *ours])}   # theirs first in each event, as they were, then the bundle's
  settings.parent.mkdir(parents=True, exist_ok=True)
  settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
  return out + [words.status("wrote", "hooks block in settings.json")]


def digest(path: Path) -> str:
  """A file's sha256, which is how the record tells a copy still as an install left it."""
  return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle() -> list[Path]:
  """Every bundled file at or beneath the fixed paths, nested ones included, and never a directory, which a copy would fail on."""
  return [source for name in FIXED for source in sorted([hub.BUNDLED / name] if (hub.BUNDLED / name).is_file() else (path for path in (hub.BUNDLED / name).rglob("*") if path.is_file()))]


def stale() -> list[Path]:
  """The bundled files whose copy at its fixed path in ~/.agents is missing, differs, or is reached through a link out of it; none in a clone, which is its own copy."""
  if not hub.INSTALLED: return []
  return [source for source in bundle() if not ((copy := hub.HOME / source.relative_to(hub.BUNDLED)).is_file() and copy.resolve().is_relative_to(hub.HOME.resolve()) and copy.read_bytes() == source.read_bytes())]


def copied() -> dict[str, str] | None:
  """What the last install copied into ~/.agents, by the record: each path beneath it to its sha256. None before an install kept one, when every copy there counts as an install's."""
  if not COPIED.is_file(): return None
  return {name: checksum for checksum, _, name in (entry.partition("  ") for entry in COPIED.read_text(encoding="utf-8").splitlines()) if name}


def dropped() -> list[Path]:
  """The copies in ~/.agents that the record names and the bundle no longer has."""
  return [copy for name in (copied() or {}) if not (hub.BUNDLED / name).is_file() and ((copy := hub.HOME / name).exists() or copy.is_symlink())]


def preflight(profile: str | None = None) -> list[str]:
  """Problems that must stop the install before it writes anything, `profile` being the answer to clone or use. Empty means go ahead."""
  problems = []
  if hasattr(os, "geteuid") and os.geteuid() == 0:
    problems.append("run this as yourself, not root: everything it writes lives in your home")

  missing = [tool for tool in ("git", "jq") if not shutil.which(tool)]
  if missing:   # jq: every hook parses its payload with it, so without it none does anything
    problems.append(f"missing {', '.join(missing)} (on a Mac: brew install {' '.join(missing)})")

  here = Path.home() / hub.AGENTS_DIR
  if (here.exists() or here.is_symlink()) and here.resolve() != hub.HOME.resolve():
    problems.append(f"{here} is something else, and every hook expects this repo there. "
                    f"Move it aside and run this again. This repo is at {hub.HOME}")
  if hub.INSTALLED and (here / "agentkit").is_dir():
    problems.append(f"{here} is a clone of .agents, and an install keeps its state there. Run the clone's own "
                    "bin/agent install, or move it aside and bring back its profile/ and local.toml")

  # a clone over ssh with no key or an unknown host stops halfway, or waits on a prompt, so ask first and never interactively
  # a default with no .git of its own reports the origin of a repo around it, such as a clone's
  if profile and "git" not in missing and _profile.remote(profile) and not ((_profile.DEFAULT / ".git").exists() and git.run(_profile.DEFAULT, "remote", "get-url", "origin").stdout.strip() == profile):   # with no git, the line above says so
    try: reached = subprocess.run(["git", "ls-remote", profile, "HEAD"], capture_output=True, check=False, text=True, timeout=60, env=os.environ | {"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")})
    except subprocess.TimeoutExpired: reached = subprocess.CompletedProcess([], 1, "", "no answer in 60 seconds")
    if reached.returncode: problems.append(f"cannot reach {profile}: {git.last_line(reached, 'git said nothing')}. `git ls-remote {profile}` should work first; nothing was changed")
  return problems


def keep(profile: str | None = None) -> tuple[int, str]:
  """Under uvx, install agentkit as a uv tool from where this copy came, so `agent` outlives the run: (0, the tool's `agent`), (0, "") outside uvx, or (1, why not).

  The checks come first, so a machine the install would refuse is left without a tool too.
  """
  if not hub.INSTALLED or os.environ.get(HANDED_OVER): return 0, ""   # the kept tool itself, run by hand_over
  try: cache = subprocess.run(["uv", "cache", "dir"], capture_output=True, check=False, text=True).stdout.strip()
  except FileNotFoundError: return 0, ""   # no uv, so no uvx either
  if not (cache and Path(sys.prefix).resolve().is_relative_to(Path(cache).resolve())): return 0, ""   # uvx runs from an environment in uv's cache
  if problems := preflight(profile): return 1, "\n".join(f"cannot install: {problem}" for problem in problems)

  found = hub.source()   # the next line names it again for uv: git+URL@revision for git, the URL for a file or directory, the name for an index
  vcs = found.get("vcs_info", {})
  kept = subprocess.run(["uv", "tool", "install", f"agentkit @ {'git+' if vcs else ''}{found['url']}{'@' + vcs['requested_revision'] if vcs.get('requested_revision') else ''}" if found else "agentkit"], capture_output=True, check=False, text=True)
  if kept.returncode: return 1, f"could not keep agentkit as a uv tool: {git.last_line(kept, 'uv said nothing')}"
  if not (tools := subprocess.run(["uv", "tool", "dir", "--bin"], capture_output=True, check=False, text=True).stdout.strip()): return 1, "kept agentkit as a uv tool, but `uv tool dir --bin` does not say where; run `agent install` from there"
  return 0, str(Path(tools) / "agent")


def shell_path() -> str:
  """PATH as a shell outside this process has it: without this environment's own bin, which `uv run` and `uvx` put first."""
  own = (Path(sys.prefix) / "bin").resolve()
  return os.pathsep.join(entry for entry in os.environ.get("PATH", "").split(os.pathsep) if Path(entry).resolve() != own)


def hand_over(kept: str) -> NoReturn:
  """Run the kept tool's `agent` in this one's place with the same arguments, marked as handed over, and a PATH without uvx's own environment, which leads it."""
  os.execve(kept, [kept, *sys.argv[1:]], os.environ | {"PATH": shell_path(), HANDED_OVER: "1"})


def upgrade() -> tuple[int, list[str]]:
  """Upgrade an install through uv and let the new version install its own hooks: the exit code and the lines to print."""
  was = hub.version()
  try: upgraded = subprocess.run(["uv", "tool", "upgrade", "agentkit"], capture_output=True, check=False, text=True)
  except FileNotFoundError: upgraded = subprocess.CompletedProcess(["uv"], 127, "", "uv is not on PATH")
  if upgraded.returncode: return 1, [words.status("FAIL", f".agents: {git.last_line(upgraded, 'uv said nothing')}")]

  version = subprocess.run([str(CLI), "--version"], capture_output=True, check=False, text=True)
  if version.returncode: return 1, [words.status("FAIL", f".agents: upgraded, but the new version does not run ({git.last_line(version, 'it said nothing')}); run `agent doctor`")]
  now = version.stdout.strip().removeprefix("agentkit ")   # the new code says its version
  if now == was: return 0, [words.status("ok", f".agents: already current at {now}")]

  copied = subprocess.run([str(CLI), "install", "--changes"], capture_output=True, check=False, stdin=subprocess.DEVNULL, text=True)   # no terminal, so it never asks
  said = [words.indented(text.strip(), words.STATUS) for text in copied.stdout.splitlines() if text.strip()]
  if copied.returncode: return 1, [words.status("FAIL", f".agents: upgraded {was} -> {now}, but its install did not finish ({git.last_line(copied, 'it said nothing')}); run `agent install`"), *said]
  return 0, [words.status("ok", f".agents: upgraded {was} -> {now}"), *said]


def run(targets: list[str], create: bool = False, profile: str | None = None) -> tuple[int, list[str]]:
  """Install into each target, returning an exit code and the lines to print.

  `profile`, a URL to clone or a directory, is saved to `local.toml` so later commands find it unasked.
  """
  problems = preflight(profile)
  if problems: return 1, [f"cannot install: {problem}" for problem in problems]

  lines = []
  if profile:   # first, so the pointer and every link below see it
    was = _profile.file("AGENTS.md")
    code, said = _profile.adopt(profile)
    if code: return code, [f"cannot install: {said}"]
    lines += ["profile", *(words.indented(change) for change in [said, *repoint(was)])]

  here = Path.home() / hub.AGENTS_DIR
  if hub.INSTALLED:   # rewritten whenever they differ, so an upgrade carries its hooks
    record, aside = copied(), []
    # a folder on the way that links out of ~/.agents is someone else's, as a linked file is: set aside whole, outermost first, before anything is copied into it
    for folder in sorted({hub.HOME / parent for name in [*(str(source.relative_to(hub.BUNDLED)) for source in bundle()), *(record or {})] for parent in Path(name).parents[:-1]}, key=lambda folder: len(folder.parts)):
      if folder.is_symlink() and not folder.resolve().is_relative_to(hub.HOME.resolve()): aside.append(words.status("saved", f"{home(folder.rename(backup(folder)))}, a link out of {home(hub.HOME)}", words.UNDER))
    for source in (copies := stale()):
      copy = hub.HOME / (name := str(source.relative_to(hub.BUNDLED)))
      # a link, or a file not as the last install left it, is someone else's: set aside, never written through or over
      if copy.is_symlink() or (copy.exists() and (not copy.is_file() or record is not None and record.get(name) != digest(copy))): aside.append(words.status("saved", f"{home(copy.rename(backup(copy)))}, which the last install did not leave there", words.UNDER))
      copy.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy(source, copy)
    for copy in dropped():   # gone from the bundle: removed as the last install left it, set aside if changed since
      if copy.is_symlink() or not copy.is_file() or digest(copy) != record[str(copy.relative_to(hub.HOME))]: aside.append(words.status("saved", f"{home(copy.rename(backup(copy)))}, which this version no longer has", words.UNDER))
      else:
        copy.unlink()
        aside.append(words.status("drop", f"{home(copy)}, which this version no longer has", words.UNDER))
    COPIED.write_text("".join(f"{digest(source)}  {source.relative_to(hub.BUNDLED)}\n" for source in bundle()), encoding="utf-8")   # every copy matches its source now
    lines += ["hooks", *aside, words.status("copy", f"{words.count(len(copies), 'file')} into {home(hub.HOME)}", words.UNDER) if copies else words.status("ok", f"hooks, githooks, commands and AGENTS.md in {home(hub.HOME)}", words.UNDER)]
  elif not here.exists():   # every hook and settings.json name ~/.agents, wherever the clone lives
    here.symlink_to(hub.HOME)
    lines += ["hub", words.status("link", f".agents -> {hub.HOME}", words.UNDER)]
  else: lines += ["hub", words.status("ok", f".agents -> {hub.HOME}", words.UNDER)]

  for script in [*hub.HOME.glob("hooks/*.sh"), CLI, *GITHOOKS.glob("*")]:
    if script.is_file(): script.chmod(script.stat().st_mode | 0o111)

  lines.append("bin")
  if hub.INSTALLED:   # uv put the console script on PATH, and an install's hooks call the one recorded, which a PATH without uv's bin still reaches
    found = shutil.which("agent")
    lines.append(words.status("ok", home(Path(found)), words.UNDER) if found and Path(found).resolve() == CLI.resolve() else words.status("note", f"`agent` on PATH is {home(Path(found)) if found else 'missing'}, not {home(CLI)}; `uv tool update-shell` puts uv's on PATH", words.UNDER))
    if RECORD.is_file() and RECORD.read_text(encoding="utf-8").strip() == str(CLI): lines.append(words.status("ok", f"hooks call {home(CLI)}", words.UNDER))
    else:
      RECORD.write_text(f"{CLI}\n", encoding="utf-8")
      lines.append(words.status("wrote", f"{home(RECORD)}: the hooks call {home(CLI)}", words.UNDER))
  else:
    lines += [words.indented(change) for change in link(CLI, Path.home() / ".local" / "bin" / "agent")]
    if str(Path.home() / ".local" / "bin") not in os.environ.get("PATH", "").split(os.pathsep):
      lines.append(words.status("note", f"{home(Path.home() / '.local' / 'bin')} is not on PATH; add it to type `agent`", words.UNDER))

  if not targets:
    targets = [target for target in INSTRUCTIONS if config_dir(target).is_dir()] or (list(INSTRUCTIONS) if create else [])
    if not targets:
      return 1, lines + [f"no agent config directory found. Name one, or pass --all. Known: {', '.join(INSTRUCTIONS)}"]

  for target in targets:
    directory = config_dir(target)
    if not directory.is_dir() and not create:
      lines.append(words.status("skip", f"{target}: {home(directory)} does not exist (--all to create it)"))
      continue

    lines.append(f"{target} -> {home(directory)}")
    changes = []
    if target in COMMANDS:
      changes += [line for command in sorted((hub.HOME / "commands").glob("*.md"))
                  for line in link(command, directory / COMMANDS[target] / command.name)]
    if target == "claude": changes += claude_hooks(directory / "settings.json")
    changes += point_at(directory / INSTRUCTIONS.get(target, "AGENTS.md"))   # any other agent reads `~/.<name>/AGENTS.md`
    lines += [words.indented(change) for change in changes]

  return 0, lines


# -- git: one set of hooks for every repo, acting only where a repo has opted in, or one repo's own ---

def global_hooks_path() -> str:
  """git's global `core.hooksPath`, or `""` when unset."""
  return subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                        capture_output=True, check=False, text=True).stdout.strip()


def ours(hooks_path: str) -> bool:
  """Whether a `core.hooksPath` value is our hooks directory."""
  return Path(hooks_path).expanduser().resolve() == GITHOOKS.resolve()


def global_install() -> tuple[int, str]:
  """Point git's global `core.hooksPath` at our hooks, refusing to replace one that is not ours."""
  current = global_hooks_path()
  if current and not ours(current):
    return 1, (f"core.hooksPath is already {current}. Not replacing it: every repo's hooks run "
               "from there. Unset it yourself if it is stale, then run this again.")

  if not GITHOOKS.is_dir(): return 1, f"no hooks at {home(GITHOOKS)} to point git at; run `agent install` first"
  for hook in GITHOOKS.iterdir(): hook.chmod(hook.stat().st_mode | 0o111)   # every time: a checkout can drop +x
  if current: return 0, words.status("ok", f"core.hooksPath is {GITHOOKS}")
  if (written := subprocess.run(["git", "config", "--global", "core.hooksPath", str(GITHOOKS)], capture_output=True, check=False, text=True)).returncode: return 1, f"could not set core.hooksPath: {git.last_line(written, 'git said nothing')}"
  return 0, words.status("set", f"core.hooksPath -> {GITHOOKS}\n"
                                "every repo with a .agents/ is now reviewed on commit; the rest are untouched,\n"
                                "and any repo's own .git/hooks still run first")


def global_uninstall() -> tuple[int, str]:
  """Unset a global `core.hooksPath` that is ours."""
  current = global_hooks_path()
  if not current: return 0, words.status("ok", "core.hooksPath is not set")
  if not ours(current):
    return 1, f"core.hooksPath is {current}, which is not ours. Leaving it alone."
  if (written := subprocess.run(["git", "config", "--global", "--unset", "core.hooksPath"], capture_output=True, check=False, text=True)).returncode: return 1, f"could not unset core.hooksPath: {git.last_line(written, 'git said nothing')}"
  return 0, words.status("unset", "core.hooksPath; every repo is back to its own .git/hooks")


def repo_hook(root: Path) -> Path:
  """Where `root`'s own post-commit hook lives, in the common git folder that `githooks/_dispatch` reads too: a linked worktree's `.git` is a file, and its hooks are the main checkout's."""
  return root / git.run(root, "rev-parse", "--git-common-dir").stdout.strip() / "hooks" / "post-commit"


def repo_hook_ours(root: Path) -> bool:
  """Whether the post-commit hook in `root` is the shim this module writes."""
  return (hook := repo_hook(root)).is_file() and HOOK_MARK in hook.read_text(encoding="utf-8", errors="replace")


def repo_install(root: Path, agent: str, backend: str) -> tuple[int, list[str]]:
  """Write the review shim as `root`'s post-commit hook, moving one that is not ours aside to a free `.bak` name: the exit code and the lines to print."""
  destination, lines = repo_hook(root), []
  if (destination.exists() or destination.is_symlink()) and not repo_hook_ours(root): lines.append(f"moved the hook already there aside to {destination.rename(backup(destination)).name}")
  destination.parent.mkdir(parents=True, exist_ok=True)
  destination.write_text(HOOK.format(agent=shlex.quote(agent), backend=shlex.quote(backend)), encoding="utf-8")   # quoted: these land in a bash script run on every commit, where a space or a ; would be code
  destination.chmod(0o755)
  return 0, [*lines, f"installed {destination}", words.indented(f"{agent} reviews each commit into {reviews.path(root, create=False)}")]


def repo_uninstall(root: Path) -> tuple[int, str]:
  """Remove `root`'s post-commit hook when it is ours: (0, what was removed) or (1, why not)."""
  destination = repo_hook(root)
  if not (destination.exists() or destination.is_symlink()): return 1, f"nothing installed at {destination}"
  if not repo_hook_ours(root): return 1, f"not ours, leaving it alone: {destination}"
  destination.unlink()
  return 0, f"removed {destination}"
