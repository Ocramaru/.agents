"""The chain of `.agents` directories above a file, and which of their notes are injected.
The chain is found by walking up to the repo root and never stored, so a committed `.agents` works wherever it is cloned.
By default only `context.md` (or a split one's index and the parts that apply) is injected and `learned.md` and `todo.md` are named, to read when needed; `inject` in agents.toml changes that.
"""

import fnmatch
import os
import tomllib
from pathlib import Path

from agentkit import config, git, hub, notes
from agentkit.frontmatter import load

AGENTS_TOML = "agents.toml"
INJECTABLE = tuple(name for name in notes.NOTES if name != notes.ARCHIVE)             # the archive is never injected
INJECT_MODES = ("full", "context", "none")   # what agents.toml `inject` may say: every injectable note, the context note alone, or none


def skipped(repo: Path | None = None) -> list[str]:
  """The directory names and globs nothing reads, `[walk] skip` from every layer added together, `repo`'s agents.toml last."""
  try: return config.section("walk", repo, add=("skip",))["skip"]
  except tomllib.TOMLDecodeError: return []   # a layer that does not parse is doctor's to report, and doctor walks before it can; until then nothing is skipped


def ignored(name: str, skip: list[str]) -> bool:
  """Whether nothing should read a directory of this name, as `skipped` lists them."""
  return any(fnmatch.fnmatch(name, pattern) for pattern in skip)


def agents_toml(agents_dir: Path) -> dict:
  """A `.agents` directory's agents.toml, or `{}`."""
  file = Path(agents_dir) / AGENTS_TOML
  try: return tomllib.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
  except tomllib.TOMLDecodeError: return {}   # a file that does not parse is doctor's to report; until then it sets nothing, so an edit still gets its standards and notes


def is_hub(agents_dir: Path) -> bool:
  """Whether this note directory belongs to the hub repo itself."""
  parent = Path(agents_dir).parent
  return (parent / "standards").is_dir() and (parent / "agents").is_dir()


def find_note_dirs(root: Path) -> list[Path]:
  """Every `.agents` directory under a tree that holds notes, and each `.local` inside one that does.

  Inside a repo git's index names them, so another checkout below it and a gitignored directory are never read, and `[walk] skip` still applies; outside one it walks.
  It walks rather than globs, so a skipped directory is pruned before it is entered and no symlink is followed.
  """
  start, skip = Path(root).resolve(), skipped(root)
  listed = git.run(start, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", f":(glob)**/{hub.AGENTS_DIR}/**")
  if listed.returncode:
    found = []
    for here, directories, _ in os.walk(start):
      directories[:] = [name for name in directories if not ignored(name, skip)]
      if hub.AGENTS_DIR in directories: found += [directory for directory in (Path(here) / hub.AGENTS_DIR, Path(here) / hub.AGENTS_DIR / hub.LOCAL_DIR) if notes.note_files(directory)]
    return sorted(found)

  # a `.local` is gitignored, so it is asked for apart; --directory names an ignored directory without entering it, so a `.local` shows as itself and one under an ignored directory not at all
  local = git.run(start, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory", "--", f":(glob)**/{hub.AGENTS_DIR}/{hub.LOCAL_DIR}/**").stdout.split("\0")
  entries = [entry for entry in listed.stdout.split("\0") + local if entry and not any(ignored(name, skip) for name in entry.rstrip("/").split("/")[:-1])]   # judged from `root` down, as review.unread judges a file
  found = {path.parent if notes.holds(path.parent) else path.parent.parent for path in (start / entry for entry in entries) if notes.is_note(path)}   # a split note's part sits one level below its directory
  found |= {path for path in (start / entry for entry in entries if entry.endswith("/")) if path.name == hub.LOCAL_DIR and notes.holds(path)}
  return sorted(directory for directory in found if notes.note_files(directory))


def chain(path: Path) -> list[Path]:
  """`.agents` directories governing a file, outermost first, nearest last, each `.local` right after its own `.agents`.

  It walks up to the repo root, so a chain never leaves its repo.
  """
  found = []
  for current in above(path):
    if (current / hub.AGENTS_DIR).is_dir(): found += [directory for directory in (current / hub.AGENTS_DIR / hub.LOCAL_DIR, current / hub.AGENTS_DIR) if notes.note_files(directory) or (directory / AGENTS_TOML).is_file()]   # the list is reversed below; config alone counts: [applies] with no notes
  return list(reversed(found))


def above(path: Path) -> list[Path]:
  """The directories a chain looks in for a `.agents`, nearest first: the file's own, up to its repo root, or home outside a repo."""
  start = Path(path).resolve()
  start = start if start.is_dir() else start.parent
  stop = git.root(start) or Path.home()   # a repo is the unit a collaborator reproduces

  found, current = [], start
  while True:
    found.append(current)
    if current == stop or current.parent == current: break
    current = current.parent
  return found


def payload(path: Path, skip: set[Path] | None = None) -> tuple[str, list[str], list[Path]]:
  """Notes to inject for a file, less those in `skip`, one-line mentions of the notes not sent, and the notes sent.

  Context notes fill the budget first, nearest to outermost, before anything opted into with `inject = "full"`.
  """
  settings, skip = config.section("inject"), skip or set()
  agents_dirs = chain(path)
  if not agents_dirs: return "", [], []

  allowed, mention = [], []
  nearest = next((owner(agents_dir) for agents_dir in reversed(agents_dirs) if notes.note_files(agents_dir)), None)   # a config-only `.agents` is never nearest
  for agents_dir in reversed(agents_dirs):
    mode = agents_toml(agents_dir).get("inject") or agents_toml(owner(agents_dir)).get("inject") or (settings["nearest"] if owner(agents_dir) == nearest else settings["ancestors"])
    if mode == "none": continue
    names = INJECTABLE if mode == "full" else ("context",)
    allowed.append((agents_dir, names))

    for name in INJECTABLE:
      # an unsent note is named with all its parts; a sent one only with the parts that name no files
      sent, note = name in names, agents_dir / f"{name}.md"
      if not sent and note.is_file(): mention.append(f"{label(agents_dir)}/{notes.summary(note)}")
      mention += [f"{label(agents_dir)}/{name}/{notes.summary(part)}" for part, globs in parts(agents_dir, name)
                  if not (sent and globs)]

  wanted = [(agents_dir, shown, note) for kind in INJECTABLE for agents_dir, names in allowed if kind in names
            for shown, note in note_parts(agents_dir, kind, path) if note not in skip]

  chosen, spent = {}, 0
  for agents_dir, shown, note in wanted:
    document = load(note)
    text = brief(document.body, settings["map_over"])
    room = settings["budget"] - spent
    if len(text) <= room:
      chosen[note] = text
      spent += len(text)
    elif room >= 1500:   # enough left for a cut note to be worth sending; under it the note is only named
      cut = text[:room].rsplit("\n", 1)[0]
      chosen[note] = f"{cut}\n\n[truncated at the budget, {len(text) - len(cut)} more characters in the file]"
      spent = settings["budget"]
    else:
      mention.append(f"{label(agents_dir)}/{shown}: over budget, {document.get('description') or 'no description'}")

  blocks = []
  for agents_dir in agents_dirs:  # outermost first, so the most specific notes land last
    for name in INJECTABLE:
      for shown, note in note_parts(agents_dir, name, path):
        if note in chosen: blocks.append(f"--- {label(agents_dir)}/{shown} ---\n{chosen[note]}")
  return "\n\n".join(blocks), mention, list(chosen)


def note_parts(agents_dir: Path, name: str, path: Path) -> list[tuple[str, Path]]:
  """What one note sends for `path`, by injected name: its index, then each part whose `applies` matches.

  A part naming no files is only advertised, so a split note grows without costing every edit.
  """
  out = []
  index = Path(agents_dir) / f"{name}.md"
  if index.is_file(): out.append((f"{name}.md", index))

  for part, globs in parts(agents_dir, name):
    if globs and any(fnmatch.fnmatch(Path(path).name, pattern) for pattern in globs):
      out.append((f"{name}/{part.name}", part))
  return out


def brief(body: str, over: int) -> str:
  """A note of `over` bytes or fewer in full; a longer one as everything above its first section.

  That head holds the note's generated section table, so the sections stay findable at the lines it gives.
  """
  # a note without sections has no table to stand in for it, so it goes whole and the budget truncates it
  if not over or len(body) <= over or "\n## " not in body: return body
  return f"{body.split("\n## ", 1)[0].rstrip()}\n\n[{len(body)} bytes in full; the sections above are in this file, at those lines]"


def parts(agents_dir: Path, name: str) -> list[tuple[Path, list[str]]]:
  """Each part of a split note with the files it names; a part naming none is read on demand, not sent."""
  split_dir = Path(agents_dir) / name
  return [(part, load(part).list("applies")) for part in sorted(split_dir.glob("*.md"))] if split_dir.is_dir() else []


def owner(directory: Path) -> Path:
  """The `.agents` a note directory belongs to: itself, or the one a `.local` sits in, so a `.local` takes its parent's inject mode, set or default."""
  return directory.parent if directory.name == hub.LOCAL_DIR else directory


def label(agents_dir: Path) -> str:
  """A note directory's scope, repo-relative where possible, so injected text is the same wherever the hook ran; a `.local` is its parent's plus `/.local`."""
  if agents_dir.name == hub.LOCAL_DIR: return f"{label(agents_dir.parent)}/{hub.LOCAL_DIR}"
  scope = Path(agents_dir).parent
  root = git.root(scope)

  for base in (root, Path.home()):
    if not base: continue
    try:
      relative = scope.relative_to(base)
    except ValueError: continue
    return str(relative) if base == root else f"~/{relative}"
  return str(scope)


def note_dirs_for(path: Path) -> list[Path]:
  """The note directories a path means: the `.agents` it is inside, else every one under it, else the nearest above."""
  start = Path(path).resolve()
  for directory in [start, *start.parents]:   # standing in a `.agents`, or in a split note under one
    if notes.holds(directory) and notes.note_files(directory): return [directory]
  if under := find_note_dirs(start): return under

  current = start
  while True:   # the closest above, not counting one inside the path itself
    if current != start and notes.note_files(current / hub.AGENTS_DIR): return [current / hub.AGENTS_DIR]
    if current == Path.home() or current.parent == current: return []
    current = current.parent


def init(target: Path) -> dict:
  """Create a `.agents` here, or add what an existing one lacks.

  Nothing records where it sits, so it survives a clone, and the README explains it to a reader without the tooling.
  """
  target = Path(target).resolve()
  agents_dir = target / hub.AGENTS_DIR
  made = not agents_dir.is_dir()
  agents_dir.mkdir(parents=True, exist_ok=True)

  added = []
  for template in sorted((hub.TEMPLATES / "agents").iterdir()):
    file, text = agents_dir / template.name, template.read_text(encoding="utf-8").replace("{name}", target.name)
    if not file.exists(): file.write_text(text, encoding="utf-8")
    elif template.name == ".gitignore" and (have := file.read_text(encoding="utf-8").splitlines()) is not None and (lacking := [line for line in text.splitlines() if line not in have]):   # read once, not once per line
      file.write_text("\n".join(have + lacking) + "\n", encoding="utf-8")   # an existing file stays as written; an ignore list gains the lines it lacks
    else: continue
    added.append(template.name)
  return {"path": str(agents_dir), "made": made, "added": added, "inherits": [label(ancestor) for ancestor in chain(target) if ancestor != agents_dir]}


