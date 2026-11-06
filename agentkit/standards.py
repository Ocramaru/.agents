"""Which standards govern a file: match `applies` on the basename, then follow `extends`, `related` and a dotted name's families (`ml.runs` layers under `ml`; a hyphen is only a compound word).
Standards layer rather than replace: a repo's `.agents/standards/python.md` is sent after the bundled one, and wins where they disagree.
The table of standards in the hub's AGENTS.md and the profile's is generated here from each one's `description`, so the frontmatter is the one copy.
"""

import fnmatch
import functools
import re
from pathlib import Path

from agentkit import hub, mapblock, profile as _profile
from agentkit.frontmatter import Doc, load

AUTO = object()   # the profile goes with the bundled set, and with nothing else
# the standards table in an AGENTS.md, generated from each standard's description as mapblock generates a note's map
TABLE_START = "<!-- standards: generated from each standard's description. Edit the description, not this; after a manual edit run `agent remap` here -->"
TABLE_END = "<!-- /standards -->"
TABLE = re.compile(r"<!-- standards\b[^>]*-->.*?" + re.escape(TABLE_END), re.DOTALL)   # any `<!-- standards` marker, so an older one is replaced


def bases(document: Doc) -> list[str]:
  """The standards one layers on, by name alone: each enclosing family of a dotted name, `a.b.c` -> `a`, `a.b`, then any `extends`."""
  bits = document.name.split(".")
  return [".".join(bits[:length]) for length in range(1, len(bits))] + document.list("extends")


def files(directory: Path) -> list[Path]:
  """The standards in a directory, a family's folder included: `latex/robotics.md` holds `latex.robotics` beside `latex/latex.md`. A hidden folder is skipped.
  Layout only: a folder carries no meaning, the name in each file's frontmatter does."""
  return sorted(file for file in Path(directory).rglob("*.md") if not any(part.startswith(".") for part in file.relative_to(directory).parts))


def tables() -> dict[Path, Path]:
  """Each AGENTS.md holding a generated standards table, with the directory it lists: the hub's, of the starters, and the profile's, of its own."""
  pairs = [(hub.BUNDLED / "AGENTS.md", hub.STANDARDS), (_profile.file("AGENTS.md"), _profile.file("standards"))]
  return {agents_md.resolve(): directory.resolve() for agents_md, directory in pairs
          if agents_md and directory and agents_md.is_file() and directory.is_dir() and TABLE.search(agents_md.read_text(encoding="utf-8"))}


def table(agents_md: Path, directory: Path) -> str:
  """The text of `agents_md` with its standards table rebuilt, a row for each standard in `directory` in name order, a family's members under it."""
  documents = sorted((load(file) for file in files(directory)), key=lambda document: document.name.split("."))   # by part, so `latex.stats` follows `latex` and not `latex-x`
  rows = [f"| [`{document.name}`]({document.path.relative_to(agents_md.parent).as_posix()}) | {document.get('description').replace('|', '\\|')} |" for document in documents]
  return TABLE.sub(lambda _: "\n".join([TABLE_START, "", "| | |", "|---|---|", *rows, "", TABLE_END]), agents_md.read_text(encoding="utf-8"), count=1)


def sections(lines: list[str]) -> list[tuple[str, int, int]]:
  """(heading, first line, line after the last) of each `##` section; a `##` line inside a fenced block is text."""
  headings = [(number - 1, heading.strip("`")) for heading, number in mapblock.headings(lines) if lines[number - 1].startswith("## ")]
  return [(heading, index, end) for (index, heading), end in zip(headings, [start for start, _ in headings[1:]] + [len(lines)])]


def scoped(body: str, name: str) -> list[tuple[str, str]]:
  """(heading, text) of each section a `##` filename heading scopes to `name`, in order."""
  lines = body.splitlines()
  return [(heading, "\n".join(lines[start:end]).strip("\n")) for heading, start, end in sections(lines) if names_a_file(heading) and fnmatch.fnmatch(name, heading)]


def names_a_file(heading: str) -> bool:
  """Whether a `##` heading is a filename rather than prose: no spaces, and an extension or a glob."""
  return " " not in heading and ("." in heading or "*" in heading or "?" in heading)


class Layer:
  """One file contributing to a standard. Precedence is its place in the list, not a field."""

  def __init__(self, document: Doc, origin: str):
    self.doc, self.origin = document, origin

  @property
  def header(self) -> str:
    """How the layer is introduced when sent."""
    return f"--- {self.doc.name} ({self.origin}) ---"

  def section_header(self, heading: str) -> str:
    """How one file-scoped section is introduced when sent on its own, its standard already out."""
    return f"--- {self.doc.name} ({self.origin}) § {heading} ---"

  def for_name(self, name: str | None) -> str:
    """This standard as it applies to one file: sections whose `##` heading names another file are dropped.

    `name=None` keeps only what loads for every file, which is what a size limit measures.
    """
    lines = self.doc.body.splitlines()
    files = [(heading, start, end) for heading, start, end in sections(lines) if names_a_file(heading)]
    if not files: return self.doc.body

    drop = {dropped for heading, start, end in files if name is None or not fnmatch.fnmatch(name, heading) for dropped in range(start, end)}
    return "\n".join(line for index, line in enumerate(lines) if index not in drop).strip("\n")


class Library:
  """The standards in force: the bundled set, then the profile, then the repo."""
  def __init__(self, root: Path | None = None, overrides: list[Path] | None = None,
               extra_applies: dict[str, list[str]] | None = None, profile=AUTO):
    self.root = Path(hub.STANDARDS if root is None else root)
    self.overrides = list(overrides or [])
    self.extra_applies = extra_applies or {}  # a repo naming its own files for a standard

    # a root other than the bundled set, as every test passes, is used alone, without the profile
    if profile is AUTO: profile = _profile.file("standards") if self.root == hub.STANDARDS else None
    self.profile = Path(profile) if profile else None

  @functools.cached_property
  def layers(self) -> dict[str, list[Layer]]:
    """Each standard's layers, in the order they apply."""
    out: dict[str, list[Layer]] = {}
    mine = {load(file).name for file in files(self.profile)} if self.profile and self.profile.is_dir() else set()

    for directory, origin in [(self.root, "bundled"), (self.profile, "profile")] + [(directory, "repo") for directory in self.overrides]:
      if not (directory and Path(directory).is_dir()): continue
      for file in files(directory):
        document = load(file)
        if origin == "bundled" and document.name in mine: continue   # a profile standard replaces the starter of its name
        out.setdefault(document.name, []).append(Layer(document, origin))
    return out

  @property
  def docs(self) -> dict[str, Doc]:
    """The most specific layer of each standard, for metadata like `applies` and `related`."""
    return {name: layers[-1].doc for name, layers in self.layers.items()}

  def matching(self, filename: str) -> list[str]:
    """Standards with a layer or an `[applies]` entry globbing the filename; patterns match the basename, never a path."""
    base = Path(filename).name
    return sorted(name for name, layers in self.layers.items()
                  if any(fnmatch.fnmatch(base, pattern)
                         for pattern in [declared for layer in layers for declared in layer.doc.list("applies")] + self.extra_applies.get(name, [])))

  def resolve(self, names: list[str]) -> list[Layer]:
    """Every layer that applies, general before specific, so the last word is the nearest one."""
    out, seen, queue = [], set(), list(names)

    def add(name: str) -> None:
      if name in seen or name not in self.layers: return
      seen.add(name)
      document = self.docs[name]

      # every base arrives first, recursively, and a dotted name implies its enclosing standards: a.b.c -> [a, a.b]
      for base in bases(document): add(base)
      out.extend(self.layers[name])
      queue.extend(document.list("related"))

    while queue: add(queue.pop(0))
    return out

  def for_file(self, filename: str) -> list[Layer]:
    """The standards governing a filename, in delivery order."""
    return self.resolve(self.matching(filename))

  def index(self) -> dict:
    """Flat table of the library, for `agent manifest` and outside indexers."""
    return {name: {"path": str(layers[-1].doc.path), "layers": [layer.origin for layer in layers],
                   "applies": sorted({pattern for layer in layers for pattern in layer.doc.list("applies")}),
                   "extends": layers[-1].doc.list("extends"), "related": layers[-1].doc.list("related"),
                   "description": layers[-1].doc.get("description")} for name, layers in sorted(self.layers.items())}
