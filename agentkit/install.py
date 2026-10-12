"""Wire this repo into the coding agents on this machine, and git into every repo that opts in.
It links rather than copies, so `git pull` updates a machine without a reinstall, and `~/.agents/bin/agent install` needs nothing on PATH.
Anything in place that is not ours is moved aside rather than overwritten, and a second run changes nothing.

Author: Marco Cassar (@Ocramaru)
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from agentkit import profile as _profile
from agentkit.profile import HUB

GITHOOKS = HUB / "githooks"
POINTER = "The `.agents/` notes convention, the standards, and how they load:"


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
  if destination.is_symlink() and destination.resolve() == source.resolve(): return [f"ok    {home(destination)}"]
  out = []
  if destination.exists() or destination.is_symlink(): out.append(f"saved {home(destination.rename(backup(destination)))}")
  destination.symlink_to(source)
  return out + [f"link  {home(destination)}"]


def point_at(file: Path) -> list[str]:
  """Append pointers to the hub's AGENTS.md, then the profile's, to an instructions file, never replacing its notes.

  The profile's comes last, so how you work refines the convention.
  """
  hub, mine = f"@{HUB}/AGENTS.md", _profile.file("AGENTS.md")
  have = file.read_text(encoding="utf-8") if file.is_file() else ""
  add = ([] if hub in have else [hub]) + ([f"@{mine}"] if mine and f"@{mine}" not in have else [])
  if not add: return [f"ok    pointer in {home(file)}"]

  file.parent.mkdir(parents=True, exist_ok=True)
  separator = "" if not have or have.endswith("\n") else "\n"   # never join the file's last line
  if hub in add: separator += ("\n" if have.strip() else "") + f"{POINTER}\n\n"
  with file.open("a", encoding="utf-8") as handle: handle.write(separator + "\n".join(add) + "\n")
  return [f"point {home(file)}" + (" (and your profile)" if mine and f"@{mine}" in add else "")]


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
    file.write_text(text.replace(f"@{old}\n", f"@{new}\n" if new else "").replace(f"@{old}", f"@{new}" if new else ""),
                    encoding="utf-8")
    out.append(f"point {home(file)} at {home(new) if new else 'no profile'}")
  return out


def hooks(settings: Path) -> list[str]:
  """Replace the hooks block in Claude Code's settings.json whole, leaving every other key as it was."""
  ours = json.loads((HUB / "settings.hooks.json").read_text(encoding="utf-8"))
  try: data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
  except ValueError: data = None
  if not isinstance(data, dict): return [f"skip  hooks block: {home(settings)} is not a JSON object, so it is left as it is; fix it and run this again"]
  if data.get("hooks") == ours: return ["ok    hooks block in settings.json"]

  out = []
  if settings.is_file():
    saved = backup(settings)   # a free name, so an earlier install's backup survives
    saved.write_text(settings.read_text(encoding="utf-8"), encoding="utf-8")
    out.append(f"saved {home(saved)}, your settings.json as it was")

  data["hooks"] = ours
  settings.parent.mkdir(parents=True, exist_ok=True)
  settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
  return out + ["wrote hooks block in settings.json"]


def preflight() -> list[str]:
  """Problems that must stop the install before it writes anything. Empty means go ahead."""
  problems = []
  if hasattr(os, "geteuid") and os.geteuid() == 0:
    problems.append("run this as yourself, not root: everything it writes lives in your home")

  missing = [tool for tool in ("git", "jq") if not shutil.which(tool)]
  if missing:   # jq: every hook parses its payload with it, so without it none does anything
    problems.append(f"missing {', '.join(missing)} (on a Mac: brew install {' '.join(missing)})")

  here = Path.home() / ".agents"
  if (here.exists() or here.is_symlink()) and here.resolve() != HUB:
    problems.append(f"{here} is something else, and every hook expects this repo there. "
                    f"Move it aside and run this again. This repo is at {HUB}")
  return problems


def run(targets: list[str], create: bool = False, profile: str | None = None) -> tuple[int, list[str]]:
  """Install into each target, returning an exit code and the lines to print.

  `profile`, a URL to clone or a directory, is saved to `local.toml` so later commands find it unasked.
  """
  problems = preflight()
  if problems: return 1, [f"cannot install: {problem}" for problem in problems]

  lines = []
  if profile:   # first, so the pointer and every link below see it
    was = _profile.file("AGENTS.md")
    code, said = _profile.adopt(profile)
    if code: return code, [f"cannot install: {said}"]
    lines += ["profile", f"  {said}", *(f"  {change}" for change in repoint(was))]

  here = Path.home() / ".agents"
  if not here.exists():   # every hook and settings.json name ~/.agents, wherever the clone lives
    here.symlink_to(HUB)
    lines.append(f"  link  .agents -> {HUB}")

  for script in [*HUB.glob("hooks/*.sh"), HUB / "bin" / "agent", *GITHOOKS.glob("*")]:
    if script.is_file(): script.chmod(script.stat().st_mode | 0o111)

  lines.append("bin")
  lines += [f"  {change}" for change in link(HUB / "bin" / "agent", Path.home() / ".local" / "bin" / "agent")]
  if str(Path.home() / ".local" / "bin") not in os.environ.get("PATH", "").split(os.pathsep):
    lines.append(f"  note  {home(Path.home() / '.local' / 'bin')} is not on PATH; add it to type `agent`")

  if not targets:
    targets = [target for target in INSTRUCTIONS if config_dir(target).is_dir()] or (list(INSTRUCTIONS) if create else [])
    if not targets:
      return 1, lines + [f"no agent config directory found. Name one, or pass --all. Known: {', '.join(INSTRUCTIONS)}"]

  for target in targets:
    directory = config_dir(target)
    if not directory.is_dir() and not create:
      lines.append(f"skip {target}: {home(directory)} does not exist (--all to create it)")
      continue

    lines.append(f"{target} -> {home(directory)}")
    changes = []
    if target in COMMANDS:
      changes += [line for command in sorted((HUB / "commands").glob("*.md"))
                  for line in link(command, directory / COMMANDS[target] / command.name)]
    if target == "claude": changes += hooks(directory / "settings.json")
    changes += point_at(directory / INSTRUCTIONS.get(target, "AGENTS.md"))   # any other agent reads `~/.<name>/AGENTS.md`
    lines += [f"  {change}" for change in changes]

  return 0, lines


# -- git: one set of hooks for every repo, acting only where a repo has opted in -------------------

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

  for hook in GITHOOKS.iterdir(): hook.chmod(hook.stat().st_mode | 0o111)   # every time: a checkout can drop +x
  if current: return 0, f"ok    core.hooksPath is {GITHOOKS}"
  subprocess.run(["git", "config", "--global", "core.hooksPath", str(GITHOOKS)], check=True)
  return 0, (f"set   core.hooksPath -> {GITHOOKS}\n"
             "      every repo with a .agents/ is now reviewed on commit; the rest are untouched,\n"
             "      and any repo's own .git/hooks still run first")


def global_uninstall() -> tuple[int, str]:
  """Unset a global `core.hooksPath` that is ours."""
  current = global_hooks_path()
  if not current: return 0, "ok    core.hooksPath is not set"
  if not ours(current):
    return 1, f"core.hooksPath is {current}, which is not ours. Leaving it alone."
  subprocess.run(["git", "config", "--global", "--unset", "core.hooksPath"], check=True)
  return 0, "unset core.hooksPath; every repo is back to its own .git/hooks"
