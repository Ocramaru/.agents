"""Note files, their tasks, and one-line summaries of the notes not sent, so an agent can choose which to open.
A note that outgrows one file becomes a directory of parts, so the filename is the map; `mapblock` keeps a section table atop each note.
Nothing is stored outside the notes themselves, so there is no second copy to drift.

Author: Marco Cassar (@Ocramaru)
"""

import re
from pathlib import Path

from agentkit import mapblock
from agentkit.frontmatter import load, parse

NOTES = ("context", "learned", "todo", "todo.archive")  # every note file the convention defines


def note_files(agents_dir: Path) -> list[Path]:
  """Every note in a `.agents`: the notes themselves, and the parts of any that has been split.

  Only the convention's names count, two levels deep, since the hub repo is itself a `.agents` holding other markdown.
  """
  directory = Path(agents_dir)
  if directory.name in NOTES: return sorted(directory.glob("*.md"))   # a split note: every file in it is a part
  return sorted([note for note in directory.glob("*.md") if note.stem in NOTES]
                + [part for part in directory.glob("*/*.md") if part.parent.name in NOTES])


def holds(directory: Path) -> bool:
  """Whether `directory` is a note directory: a `.agents`, or the `.local` directly inside one."""
  return directory.name == ".agents" or (directory.name == ".local" and directory.parent.name == ".agents")


def is_note(path: Path) -> bool:
  """Whether `path` is a note directly in a note directory or a part one level down, the two levels `note_files` walks."""
  candidate = Path(path)
  if candidate.suffix != ".md": return False
  if holds(candidate.parent): return candidate.stem in NOTES
  return candidate.parent.name in NOTES and holds(candidate.parent.parent)


TASK = re.compile(r"^\s*-\s*\[[ xX]\]\s*(.+?)\s*$")


def tasks(text: str) -> list[str]:
  """The task lines in a note, by their text, so reflowing or reordering is not a deletion."""
  return [matched.group(1) for line in text.splitlines() if (matched := TASK.match(line))]


def abandoned(path: Path, old: str, new: str) -> str:
  """The warning for tasks an edit takes out of `todo.md` that are not in `todo.archive.md` either, or "".
  It warns rather than refuses, since rewording and dedup are ordinary reasons for a task to leave, and it is never stamped, so every such edit gets it."""
  note = Path(path)
  if not is_note(note) or match_name(note) != "todo.md": return ""
  kept = tasks(new)
  gone = [task for task in tasks(old) if not _listed(task, kept)]   # annotated in place is still kept
  if not gone: return ""

  done = [archived for archive in note_files(note.parent if holds(note.parent) else note.parent.parent) if match_name(archive) == "todo.archive.md" for archived in tasks(archive.read_text(encoding="utf-8"))]   # or its parts
  # task against task, never the archive as text, where any line mentioning a task counts as filing it
  if not (gone := [task for task in gone if not _listed(task, done)]): return ""
  return (f"This edit removes {len(gone)} task{'' if len(gone) == 1 else 's'} from {note.name}, {'which is' if len(gone) == 1 else 'which are'} not in todo.archive.md. A finished task is moved "
          f"there, not deleted: it is the cheapest record of why the code looks the way it does. If one is abandoned rather than done, say that where it goes.\n{"\n".join(f"  - {task}" for task in gone)}")


def _listed(task: str, pool: list[str]) -> bool:
  """Whether an entry in `pool` starts the way `task` does, ignoring markdown and runs of whitespace.

  A move or an edit reformats a task and annotates its end, but keeps its start.
  """
  start, *entries = (" ".join(re.sub(r"[`*\[\]]", "", text).split()) for text in (task, *pool))
  return any(entry.startswith(start[:48]) for entry in entries)


def match_name(path: Path) -> str:
  """The filename standards are matched against; a split note's part is governed as its note."""
  file = Path(path)
  if is_note(file) and file.parent.name in NOTES: return f"{file.parent.name}.md"
  return file.name


def remap(path: Path) -> bool:
  """Refresh a note's section table, or every note in a directory. True when anything changed."""
  path = Path(path)

  changed = False
  for note in note_files(path) if path.is_dir() else [path]:
    text = note.read_text(encoding="utf-8")
    new = mapblock.apply(text)
    if new == text: continue
    note.write_text(new, encoding="utf-8")
    changed = True
  return changed


def summary(path: Path) -> str:
  """One line: what the file is, how big it is (`840c`, `6k`), and what is in it."""
  path = Path(path)
  document = load(path)
  size = f"{len(document.body) // 1000}k" if len(document.body) >= 1000 else f"{len(document.body)}c"
  description = document.get("description")
  if description: return f"{path.name} ({size}): {description}"

  names = [heading for heading, _ in mapblock.headings(path.read_text(encoding="utf-8").splitlines()) if heading.lower() not in ("what we learned", "todo")]   # the notes' own titles
  return f"{path.name} ({size}){f": {', '.join(names[:6])}" if names else ""}"


def split(path: Path) -> list[Path]:
  """Split a note into a directory, one file per `##` section, and return the parts written.

  The preamble stays in the note, which becomes an index, so a link to the note still resolves.
  """
  path = Path(path)
  out = path.parent / path.stem
  if out.is_dir() and any(out.glob("*.md")):
    # a second split overwrites some parts and strands others, which still load; add a part as a file instead
    raise ValueError(f"{path.name} is already split into {out.name}/")

  stripped = mapblock.strip(path.read_text(encoding="utf-8"))
  document = parse(stripped)
  lines = document.body.splitlines()
  # the map's own reading, so a `## ` inside a fence is not a section here either
  starts = [line_number - 1 for _, line_number in mapblock.headings(lines) if lines[line_number - 1].startswith("## ")]
  if not starts: return []   # checked before writing, so a note with nothing to split is untouched
  path.write_text(stripped, encoding="utf-8")

  out.mkdir(exist_ok=True)
  written = []
  for index, start in enumerate(starts):
    title = lines[start][3:].strip()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(slug) > 32: slug = slug[:32].rsplit("-", 1)[0]   # at a word boundary, or mid-word for one long word
    slug = slug or f"section-{index}"
    part = out / f"{index + 1:02d}-{slug}.md"   # keep the note's order; the filenames are read in sequence
    part.write_text(f"---\nname: {slug}\ndescription: {title}\nkind: {path.stem}\n---\n\n# {title}\n\n{"\n".join(lines[start + 1:starts[index + 1] if index + 1 < len(starts) else len(lines)]).strip("\n")}\n",
                    encoding="utf-8")
    written.append((title, part))

  head = "\n".join(lines[:starts[0]]).strip("\n")
  keep = [f"---\n{''.join(f'{key}: {value}\n' for key, value in document.meta.items())}---"] if document.meta else []
  if head: keep += ([""] if keep else []) + [head]

  # context parts load on their own, so an index telling the reader to go and fetch them would lie
  keep += ["", ("Split by section. A part naming `applies` is sent for those files; the rest are here to read:"
                if path.stem == "context" else "Split by section. Read the one you need:"), ""]
  keep += [f"- [{title}]({path.stem}/{part.name})" for title, part in written]

  path.write_text("\n".join(keep) + "\n", encoding="utf-8")
  remap(out)
  remap(path)
  return [part for _, part in written]

