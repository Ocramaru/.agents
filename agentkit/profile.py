"""Where your own standards, reviewers, backends, config and AGENTS.md live, apart from the public hub's starters.
A profile, usually a private repo cloned to `~/.agents/profile`, replaces a starter of the same name; a repo's standards still layer on top.
Where it lives is this machine's, in the gitignored `local.toml`, which also takes any config.toml section for a machine with no profile; `subject` is what a review of it reads.
"""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

from agentkit import gh, git, hub, words
from agentkit.frontmatter import load

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


def unasked() -> bool:
  """Whether no profile is in force and local.toml records no choice, so install has not yet had an answer."""
  return path() is None and chosen() is None


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
  source = source.strip()
  if not source: return 1, "name a profile: new, none, a URL or a directory"   # Path("") is the current directory
  if source == "none":
    save(None)
    return 0, words.status("set", "no profile: the starters in .agents are in use, and install stops asking")

  if source == "new":
    made = init(DEFAULT)
    save(DEFAULT)
    return 0, words.status("made", f"profile at {DEFAULT}: {', '.join(made)}") if made else words.status("ok", f"profile at {DEFAULT}")

  if not remote(source):
    where = Path(source).expanduser()
    if not where.is_dir(): return 1, f"no profile at {where}"
    save(where)
    return 0, words.status("set", f"profile -> {where}")

  if DEFAULT.exists():
    origin = git.run(DEFAULT, "remote", "get-url", "origin").stdout.strip() if (DEFAULT / ".git").exists() else ""   # with no .git of its own, git reads the repo around it
    if origin != source: return 1, f"{DEFAULT} already holds {origin or 'something else'}, not {source}"
    save(DEFAULT)
    return 0, words.status("ok", f"profile -> {DEFAULT} ({source})")

  result = subprocess.run(["git", "clone", "-q", source, str(DEFAULT)], capture_output=True, text=True, check=False)
  if result.returncode: return 1, f"could not clone {source}: {result.stderr.strip()}"
  save(DEFAULT)
  return 0, words.status("clone", f"profile {source} -> {DEFAULT}")


def remote(source: str) -> bool:
  """Whether a profile answer names a repo to clone rather than a directory: a URL, an scp-style address, or a path ending .git."""
  return "://" in source or source.endswith(".git") or (":" in source and "@" in source.split(":")[0])


def published(where: Path | None = None) -> bool:
  """Whether the repo at `where`, by default the default profile, has a git remote, which is how a profile reaches other machines."""
  return bool(git.run(where or DEFAULT, "remote").stdout.strip())


def publish(login: str) -> list[str]:
  """Make `login`/.agents.profile on GitHub, private, from the default profile and push it; the lines to print."""
  made = gh.run("repo", "create", f"{login}/.agents.profile", "--private", "--source", str(DEFAULT), "--remote", "origin", "--push")
  return [words.status("made", f"{login}/.agents.profile, private, and pushed", words.UNDER) if made.returncode == 0 else words.status("FAIL", git.last_line(made, "gh said nothing"), words.UNDER)]


def drift(where: Path) -> list[str]:
  """What would leave another machine without the profile's latest: uncommitted, unpushed, or behind.

  Behind is as of the last fetch, since doctor does not fetch.
  """
  if not (where / ".git").exists(): return []
  if (status := git.run(where, "status", "--porcelain=v2", "--branch")).returncode: return [f"git status failed: {status.stderr.strip().partition('\n')[0]}"]
  branch = dict(line[2:].split(" ", 1) for line in status.stdout.splitlines() if line.startswith("# "))   # its headers, which git never translates
  out = []
  dirty = len(status.stdout.splitlines()) - len(branch)
  if dirty: out.append(words.count(dirty, "uncommitted change"))

  if "branch.upstream" not in branch: return out + ["no upstream to push to"]
  if "branch.ab" not in branch: return out + [f"its upstream {branch['branch.upstream']} is gone, or was never fetched"]
  ahead, behind = (abs(int(count)) for count in branch["branch.ab"].split())   # "+ahead -behind"
  if ahead: out.append(f"{words.count(ahead, 'commit')} not pushed")
  if behind: out.append(f"{behind} behind, as of the last fetch")
  return out


def subject() -> dict[Path, str]:
  """What `agent profile review` reads, each file with what it is: the profile's AGENTS.md and standards, each starter one replaces or extends, the repo overrides along every place Claude Code has run, and the memory inbox.
  An override met in two checkouts of one repo is read once, by its place in the repo."""
  from agentkit import memory, standards as _standards, tree   # all reach this module again, through install and config

  out, where = {}, path()
  mine = [load(file) for file in _standards.files(where / "standards")] if where and (where / "standards").is_dir() else []
  starters, names = {load(file).name: file for file in _standards.files(hub.STANDARDS)}, {document.name for document in mine}
  if where and (where / "AGENTS.md").is_file(): out[where / "AGENTS.md"] = "the profile's AGENTS.md: how this person works, in every repo"
  for document in mine: out[document.path] = f"a profile standard, {document.name}" + (", replacing the starter of its name" if document.name in starters else "")
  for document in mine:
    if document.name in starters: out[starters[document.name]] = f"the starter {document.name}, which the profile's replaces whole"
    for base in _standards.bases(document):
      if base in starters and base not in names: out.setdefault(starters[base], f"the starter {base}, which the profile's {document.name} layers on")

  # repo overrides: the chain from each place up to its repo root, as inject walks it
  seen, read = {hub.STANDARDS.resolve(), *([(where / "standards").resolve()] if where else [])}, set()
  for place in [*memory.places(), Path.cwd()]:
    for agents_dir in tree.chain(place):
      if (standards := agents_dir / hub.STANDARDS_DIR).resolve() in seen or not standards.is_dir(): continue
      seen.add(standards.resolve())
      # a repo is its origin, else its main checkout, so its worktrees and clones are one repo and another repo with the same text is not
      checkout = (git.root(agents_dir) or agents_dir.parent).resolve()
      repo = (git.run(checkout, "remote", "get-url", "origin").stdout.strip() or str(git.main_checkout(checkout) or checkout), os.path.relpath(agents_dir.resolve(), checkout))
      for file in _standards.files(standards):
        if (repo, file.relative_to(agents_dir)) in read: continue   # the same override in another worktree of its repo
        read.add((repo, file.relative_to(agents_dir)))
        name = load(file).name
        out[file] = f"a repo standard, {name}, for files in {agents_dir.parent}, " + ("layered on the profile's of its name" if name in names else "layered on the starter of its name" if name in starters else "the repo's own, since no profile or starter standard has its name")

  inbox = memory.inbox()
  homes = {project: memory.place(project) for project in {file.parent.parent for file in inbox}}   # a project folder holds several memories, and finding its place walks the disk
  for file in inbox: out[file] = f"a memory Claude Code saved for sessions in {homes[file.parent.parent] or f'a directory that no longer exists ({file.parent.parent.name})'}"
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

  # what `agent profile review` keeps in the profile is ignored from the first commit, so a review leaves nothing to commit
  if not (ignore := where / hub.AGENTS_DIR / ".gitignore").exists():
    ignore.parent.mkdir(exist_ok=True)
    shutil.copy(hub.TEMPLATES / "agents" / ".gitignore", ignore)
    made.append(".agents/.gitignore")

  # nested in the .agents clone is fine, .agents ignores it; and .git only if init worked
  if not (where / ".git").exists() and subprocess.run(["git", "init", "-q", "-b", "main", str(where)], check=False).returncode == 0:
    made.append(".git")
    if git.run(where, "add", "-A").returncode == 0 and git.run(where, "commit", "-qm", "Start a profile").returncode == 0: made.append("a first commit, so it can be pushed")
  return made
