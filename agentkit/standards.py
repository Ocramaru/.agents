"""Which standards govern a file: match `applies` on the basename, then follow `extends` and `related`.
Standards layer rather than replace: a repo's `.agents/standards/python.md` is sent after the machine-wide one, and wins where they disagree.
A dot in a name is a namespace (`ml.runs` layers under `ml`) and a hyphen a compound word; `extends` names a base explicitly.

Author: Marco Cassar (@Ocramaru)
"""

import fnmatch
import functools
from pathlib import Path

from agentkit import profile as _profile
from agentkit.frontmatter import Doc, load

GLOBAL = _profile.HUB / "standards"
AUTO = object()   # the profile goes with the bundled set, and with nothing else


def sections(lines: list[str]) -> list[tuple[str, int, int]]:
  """(heading, first line, line after the last) of each `##` section."""
  headings = [(index, line[3:].strip().strip("`")) for index, line in enumerate(lines) if line.startswith("## ")]
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
  """The standards in force: the machine-wide set, then the profile, then the repo."""
  def __init__(self, root: Path = GLOBAL, overrides: list[Path] | None = None,
               extra_applies: dict[str, list[str]] | None = None, profile=AUTO):
    self.root = Path(root)
    self.overrides = list(overrides or [])
    self.extra_applies = extra_applies or {}  # a repo naming its own files for a standard

    # a root other than the bundled set, as every test passes, is used alone, without the profile
    if profile is AUTO: profile = _profile.file("standards") if self.root == GLOBAL else None
    self.profile = Path(profile) if profile else None

  @functools.cached_property
  def layers(self) -> dict[str, list[Layer]]:
    """Each standard's layers, in the order they apply."""
    out: dict[str, list[Layer]] = {}
    mine = {load(file).name for file in self.profile.glob("*.md")} if self.profile and self.profile.is_dir() else set()

    for directory, origin in [(self.root, "machine-wide"), (self.profile, "profile")] + [(directory, "repo") for directory in self.overrides]:
      if not (directory and Path(directory).is_dir()): continue
      for file in sorted(Path(directory).glob("*.md")):
        document = load(file)
        if origin == "machine-wide" and document.name in mine: continue   # a profile standard replaces the starter of its name
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
      bits = name.split(".")
      for base in [".".join(bits[:length]) for length in range(1, len(bits))] + document.list("extends"): add(base)
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
