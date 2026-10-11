"""Where your own standards, reviewers, backends, config and AGENTS.md live, apart from the public hub's starters.
A profile, usually a private repo cloned to `~/.agents/profile`, replaces a starter of the same name; a repo's standards still layer on top.
Where it lives is this machine's, in the gitignored `local.toml`, which also takes any config.toml section for a machine with no profile.

Author: Marco Cassar (@Ocramaru)
"""

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
CONFIG = HUB / "config.toml"   # what ships, and so every key's default
LOCAL = HUB / "local.toml"
TEMPLATES = HUB / "templates"   # what `agent init` and `agent profile init` write, one folder each
DEFAULT = HUB / "profile"


def path() -> Path | None:
  """The profile in force; `AGENTS_PROFILE=""` means none, which keeps a test off the machine's."""
  override = os.environ.get("AGENTS_PROFILE")
  if override is not None: return Path(override).expanduser() if override else None

  try: local = tomllib.loads(LOCAL.read_text(encoding="utf-8")) if LOCAL.is_file() else {}   # this machine's install
  except tomllib.TOMLDecodeError: local = {}      # a broken local file is no profile, not a crash
  saved = local.get("profile", {}).get("path")
  if saved: return Path(saved).expanduser()
  return DEFAULT if DEFAULT.is_dir() else None


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


def save(where: Path) -> None:
  """Record this machine's profile, changing only the `path` line so the rest stays as written.

  JSON's string escaping is TOML's, so any path is quoted validly.
  """
  line = f"path = {json.dumps(str(Path(where).expanduser().resolve()))}"
  text = LOCAL.read_text(encoding="utf-8") if LOCAL.is_file() else HEADER
  table = re.search(r"(?ms)^\[profile\][ \t]*\n(.*?)(?=^\[|\Z)", text)

  if table is None: text = f"{text.rstrip()}\n\n[profile]\n{line}\n"
  else:
    body = table.group(1)
    body = (re.sub(r"(?m)^path\s*=.*$", lambda _: line, body, count=1) if re.search(r"(?m)^path\s*=", body)
            else f"{line}\n{body}")
    text = text[:table.start(1)] + body + text[table.end(1):]
  LOCAL.write_text(text, encoding="utf-8")


HEADER = "# This machine's install. Not tracked: where your profile lives is local.\n"


def adopt(source: str) -> tuple[int, str]:
  """Make `source` this machine's profile: clone it if it is a URL, then remember where it is."""
  if not ("://" in source or source.endswith(".git") or (":" in source and "@" in source.split(":")[0])):   # scp-style too
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
  if not (where / ".git").exists() and subprocess.run(["git", "init", "-q", "-b", "main", str(where)],
                                                      check=False).returncode == 0:
    made.append(".git")
  return made
