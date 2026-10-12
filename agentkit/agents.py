"""Agent definitions from agents/*.md, and the subject matter handed to them.

Author: Marco Cassar (@Ocramaru)
"""

import subprocess
from pathlib import Path

from agentkit import notes, profile as _profile, tree
from agentkit.frontmatter import Doc, load
from agentkit.standards import Library

AGENTS = _profile.HUB / "agents"


def definitions(root: Path = AGENTS) -> dict[str, Doc]:
  """Every reviewer definition by name, the profile's replacing .agents' own, with [review]'s `model` where none is named."""
  default = _profile.section("review", tree.git_root(Path.cwd()) or Path.cwd())["model"]

  found = {path.stem: load(path) for directory in (Path(root), _profile.file("agents") if Path(root) == AGENTS else None) if directory for path in sorted(directory.glob("*.md"))}
  for definition in found.values(): definition.meta.setdefault("model", default)
  return found


def kind_of(found: dict[str, Doc]) -> dict[str, str]:
  """Agent name -> the kind of review it does: what a person asks for, and what output names."""
  return {name: document.get("kind") or name for name, document in found.items()}


def kinds(found: dict[str, Doc]) -> dict[str, list[str]]:
  """Kind of review -> the agents that do it, such as `logic`, `docs`, `prose`."""
  grouped: dict[str, list[str]] = {}
  for name, kind in sorted(kind_of(found).items()): grouped.setdefault(kind, []).append(name)
  return grouped


def definition(name: str, found: dict[str, Doc]) -> Doc:
  """The reviewer definition by name; exits naming the ones there are when there is none."""
  if name in found: return found[name]
  raise SystemExit(f"no agent or kind called {name!r}; agents are {', '.join(found)}, and `agent sub agents` lists the kinds")


def instructions(definition: Doc, library: Library | None = None, path: Path | str | None = None) -> str:
  """The definition body plus its standards: those governing `path` when given and any do, else all of them.
  A reviewer given rules for other files loses track of the one it is reviewing."""
  library = library or Library()
  names = definition.list("standards")
  if path is not None:
    governs = {standard.doc.name for standard in library.for_file(notes.match_name(path))}
    names = [name for name in names if name in governs] or names

  rules = "\n".join(f"--- standard: {layer.doc.name} ---\n{layer.doc.body}\n" for layer in library.resolve(names))
  return f"{definition.body}\n\nThe standards you are judging against:\n\n{rules}" if rules else definition.body


def prompt(files: list[tuple[str, str]], changed: bool = False) -> str:
  """The prompt body: the diff if `changed`, then each (path, text) numbered."""
  parts = []
  if changed and (diff := subprocess.run(["git", "diff", "--unified=3", "HEAD"], capture_output=True, check=False, text=True)).returncode != 0:
    raise SystemExit(f"git diff failed, so there is no working diff to send: {diff.stderr.strip()}")
  if changed and diff.stdout.strip(): parts.append(f"--- working diff ---\n{diff.stdout.strip()}")

  for path, text in files: parts.append(f"--- file: {path} ---\n{"\n".join(f"{number:>5}\t{line}" for number, line in enumerate(text.splitlines(), 1))}")

  if not parts: return ""
  return "\n\n".join(["What follows is the whole of what you were asked about. Do not ask which files to look at. These are them.", *parts])
