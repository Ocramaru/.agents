"""Where your own standards, reviewers, backends, config and AGENTS.md live, apart from the public hub's starters.
A profile, usually a private repo cloned to `~/.agents/profile`, replaces a starter of the same name; a repo's standards still layer on top.
Where it lives is this machine's, in the gitignored `local.toml`, which also takes any config.toml section for a machine with no profile.

Author: Marco Cassar (@Ocramaru)
"""

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
INSTALLED = (PACKAGE / "shipped").is_dir()   # a wheel carries the hub's files inside the package; a checkout has them beside it
SHIPPED = PACKAGE / "shipped" if INSTALLED else PACKAGE.parent   # standards, agents, templates and hooks as released, replaced by an upgrade
HOME = Path.home() / ".agents" if INSTALLED else PACKAGE.parent   # this machine's state and the hooks at their fixed paths; a clone is its own
CONFIG = SHIPPED / "config.toml"   # what ships, and so every key's default
LOCAL = HOME / "local.toml"
TEMPLATES = SHIPPED / "templates"   # what `agent init` and `agent profile init` write, one folder each
DEFAULT = HOME / "profile"


def source() -> dict:
  """Where uv installed agentkit from, as its direct_url.json records it: a `url`, with `vcs_info` for a git source; empty from an index."""
  try: return json.loads(importlib.metadata.distribution("agentkit").read_text("direct_url.json") or "{}")
  except (importlib.metadata.PackageNotFoundError, ValueError): return {}


def path() -> Path | None:
  """The profile in force; `AGENTS_PROFILE=""` means none, which keeps a test off the machine's."""
  override = os.environ.get("AGENTS_PROFILE")
  if override is not None: return Path(override).expanduser() if override else None
  if (saved := chosen()) is not None: return Path(saved).expanduser() if saved else None
  return DEFAULT if DEFAULT.is_dir() else None


def chosen() -> str | None:
  """The profile this machine's local.toml records: a path, `""` for a choice of none, or None when it records no choice."""
  try: local = tomllib.loads(LOCAL.read_text(encoding="utf-8")) if LOCAL.is_file() else {}
  except tomllib.TOMLDecodeError: local = {}      # a broken local file is no profile, not a crash
  return local.get("profile", {}).get("path")


def file(name: str) -> Path | None:
  """One piece of the profile, such as `standards` or `config.toml`, if it has that piece."""
  root = path()
  return root / name if root and (root / name).exists() else None


def section(name: str, repo: Path | None = None, add: tuple[str, ...] = ()) -> dict:
  """One config section: the hub's config.toml, the profile's, this machine's local.toml, then `repo`'s .agents/agents.toml and its .local/agents.toml, each key replacing the last except those in `add`, which accumulate.
  `AGENTS_PROFILE=""` leaves out the profile and local.toml, so a test reads only the config it is given."""
  settings: dict = {}
  for layer in (CONFIG, file("config.toml"), None if os.environ.get("AGENTS_PROFILE") == "" else LOCAL, *((Path(repo) / ".agents" / "agents.toml", Path(repo) / ".agents" / ".local" / "agents.toml") if repo else ())):
    if not layer or not layer.is_file(): continue
    for key, value in tomllib.loads(layer.read_text(encoding="utf-8")).get(name, {}).items(): settings[key] = settings.get(key, []) + value if key in add else value
  return settings


def save(where: Path | None) -> None:
  """Record this machine's profile, or an empty path for none, changing only the `path` line so the rest stays as written.

  JSON's string escaping is TOML's, so any path is quoted validly.
  """
  line = f"path = {json.dumps(str(Path(where).expanduser().resolve()) if where else '')}"
  text = LOCAL.read_text(encoding="utf-8") if LOCAL.is_file() else HEADER
  table = re.search(r"(?ms)^\[profile\][ \t]*(?:#[^\n]*)?\n(.*?)(?=^\[|\Z)", text)

  if table is None: text = f"{text.rstrip()}\n\n[profile]\n{line}\n"
  else:
    body = table.group(1)
    body = (re.sub(r"(?m)^[ \t]*path\s*=.*$", lambda _: line, body, count=1) if re.search(r"(?m)^[ \t]*path\s*=", body)
            else f"{line}\n{body}")
    text = text[:table.start(1)] + body + text[table.end(1):]
  LOCAL.write_text(text, encoding="utf-8")


HEADER = "# This machine's install. Not tracked: where your profile lives is local.\n"


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
    origin = git(DEFAULT, "remote", "get-url", "origin").stdout.strip()
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


def git(where: Path, *args: str) -> subprocess.CompletedProcess:
  """Run git in `where`, never raising."""
  return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, check=False)


def drift(where: Path) -> list[str]:
  """What would leave another machine without the profile's latest: uncommitted, unpushed, or behind.

  Behind is as of the last fetch, since doctor does not fetch.
  """
  if not (where / ".git").exists(): return []
  out = []
  dirty = len(git(where, "status", "--porcelain").stdout.splitlines())
  if dirty: out.append(f"{dirty} uncommitted change{'s' if dirty != 1 else ''}")

  counts = git(where, "rev-list", "--left-right", "--count", "@{u}...HEAD")
  if counts.returncode: return out + ["no upstream to push to"]
  behind, ahead = (int(count) for count in counts.stdout.split())
  if ahead: out.append(f"{ahead} commit{'s' if ahead != 1 else ''} not pushed")
  if behind: out.append(f"{behind} behind, as of the last fetch")
  return out


def init(where: Path) -> list[str]:
  """Create an empty profile, the layout the hub reads plus a git repo, and return what it made."""
  where, made = Path(where).expanduser(), []
  if not (where / "standards").is_dir():
    (where / "standards").mkdir(parents=True)
    made.append("standards/")

  for template in sorted((TEMPLATES / "profile").iterdir()):
    if not (where / template.name).exists():
      shutil.copy(template, where / template.name)
      made.append(template.name)

  # nested in the .agents clone is fine, .agents ignores it; and .git only if init worked
  if not (where / ".git").exists() and subprocess.run(["git", "init", "-q", "-b", "main", str(where)], check=False).returncode == 0:
    made.append(".git")
    if git(where, "add", "-A").returncode == 0 and git(where, "commit", "-qm", "Start a profile").returncode == 0: made.append("a first commit, so it can be pushed")
  return made
