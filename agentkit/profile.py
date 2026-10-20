"""Where your own standards, reviewers, backends, config and AGENTS.md live, apart from the public hub's starters.
A profile, usually a private repo cloned to `~/.agents/profile`, replaces a starter of the same name; a repo's standards still layer on top.
Where it lives is this machine's, in the gitignored `local.toml`, which also takes any config.toml section for a machine with no profile.

Author: Marco Cassar (@Ocramaru)
"""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

from agentkit import git, hub

DEFAULT = hub.HOME / "profile"   # where a profile is made or cloned when none is named


def path() -> Path | None:
  """The profile in force; `AGENTS_PROFILE=""` means none, which keeps a test off the machine's."""
  override = os.environ.get("AGENTS_PROFILE")
  if override is not None: return Path(override).expanduser() if override else None
  if (saved := chosen()) is not None: return Path(saved).expanduser() if saved else None
  return DEFAULT if DEFAULT.is_dir() else None


def chosen() -> str | None:
  """The profile this machine's local.toml records: a path, `""` for a choice of none, or None when it records no choice."""
  try: local = tomllib.loads(hub.LOCAL.read_text(encoding="utf-8")) if hub.LOCAL.is_file() else {}
  except tomllib.TOMLDecodeError: local = {}      # a broken local file is no profile, not a crash
  return saved if isinstance(table := local.get("profile"), dict) and isinstance(saved := table.get("path"), str) else None   # nor is one of the wrong shape


def file(name: str) -> Path | None:
  """One piece of the profile, such as `standards` or `config.toml`, if it has that piece."""
  root = path()
  return root / name if root and (root / name).exists() else None


def save(where: Path | None) -> None:
  """Record this machine's profile, or an empty path for none."""
  from agentkit import config   # config imports profile, so importing it at the top would be a cycle
  config.write(hub.LOCAL, "profile", "path", str(Path(where).expanduser().resolve()) if where else "")


def adopt(source: str) -> tuple[int, str]:
  """Make `source` this machine's profile and remember it: `new` makes one at the default path, `none` records that there is none, a URL is cloned and a directory used where it is."""
  if source == "none":
    save(None)
    return 0, "set   no profile: the starters in .agents are in use, and install stops asking"

  if source == "new":
    made = init(DEFAULT)
    save(DEFAULT)
    return 0, f"made  profile at {DEFAULT}: {', '.join(made)}" if made else f"ok    profile at {DEFAULT}"

  if not remote(source):
    where = Path(source).expanduser()
    if not where.is_dir(): return 1, f"no profile at {where}"
    save(where)
    return 0, f"set   profile -> {where}"

  if DEFAULT.exists():
    origin = git.run(DEFAULT, "remote", "get-url", "origin").stdout.strip()
    if origin != source: return 1, f"{DEFAULT} already holds {origin or 'something else'}, not {source}"
    save(DEFAULT)
    return 0, f"ok    profile -> {DEFAULT} ({source})"

  result = subprocess.run(["git", "clone", "-q", source, str(DEFAULT)], capture_output=True, text=True, check=False)
  if result.returncode: return 1, f"could not clone {source}: {result.stderr.strip()}"
  save(DEFAULT)
  return 0, f"clone profile {source} -> {DEFAULT}"


def remote(source: str) -> bool:
  """Whether a profile answer names a repo to clone rather than a directory: a URL, an scp-style address, or a path ending .git."""
  return "://" in source or source.endswith(".git") or (":" in source and "@" in source.split(":")[0])


def drift(where: Path) -> list[str]:
  """What would leave another machine without the profile's latest: uncommitted, unpushed, or behind.

  Behind is as of the last fetch, since doctor does not fetch.
  """
  if not (where / ".git").exists(): return []
  if (status := git.run(where, "status", "--porcelain=v2", "--branch")).returncode: return [f"git status failed: {status.stderr.strip().partition('\n')[0]}"]
  branch = dict(line[2:].split(" ", 1) for line in status.stdout.splitlines() if line.startswith("# "))   # its headers, which git never translates
  out = []
  dirty = len(status.stdout.splitlines()) - len(branch)
  if dirty: out.append(f"{dirty} uncommitted change{'s' if dirty != 1 else ''}")

  if "branch.upstream" not in branch: return out + ["no upstream to push to"]
  if "branch.ab" not in branch: return out + [f"its upstream {branch['branch.upstream']} is gone, or was never fetched"]
  ahead, behind = (abs(int(count)) for count in branch["branch.ab"].split())   # "+ahead -behind"
  if ahead: out.append(f"{ahead} commit{'s' if ahead != 1 else ''} not pushed")
  if behind: out.append(f"{behind} behind, as of the last fetch")
  return out


def init(where: Path) -> list[str]:
  """Create an empty profile, the layout the hub reads plus a git repo, and return what it made."""
  where, made = Path(where).expanduser(), []
  if not (where / "standards").is_dir():
    (where / "standards").mkdir(parents=True)
    made.append("standards/")

  for template in sorted((hub.TEMPLATES / "profile").iterdir()):
    if not (where / template.name).exists():
      shutil.copy(template, where / template.name)
      made.append(template.name)

  # nested in the .agents clone is fine, .agents ignores it; and .git only if init worked
  if not (where / ".git").exists() and subprocess.run(["git", "init", "-q", "-b", "main", str(where)], check=False).returncode == 0:
    made.append(".git")
    if git.run(where, "add", "-A").returncode == 0 and git.run(where, "commit", "-qm", "Start a profile").returncode == 0: made.append("a first commit, so it can be pushed")
  return made
