"""Claude Code's auto memory: the files waiting under `~/.claude/projects/*/memory`, and the directory each project is.
They are an inbox, since a rule or fact there has a home in a `.agents` or the profile, where every session reads it; `agent profile review` says which.
Claude names a project's folder after its path with every character but a letter or digit made `-`, so the path is found again by walking the disk.
"""

import re
from pathlib import Path

from agentkit import install

INDEX = "MEMORY.md"   # Claude's own list of a folder's memories, not a memory


def projects() -> Path:
  """Where Claude Code keeps a folder per project it has run in."""
  return install.config_dir("claude") / "projects"


def inbox() -> list[Path]:
  """Every memory file waiting, by project folder name, without the index each folder keeps."""
  return sorted(path for path in projects().glob("*/memory/*.md") if path.name != INDEX)


def place(project: Path) -> Path | None:
  """The directory a project folder is named after, or None when it no longer exists or cannot be read.
  Each step down keeps only the children whose flattened path the name still starts with, so `-`, `.`, `/` and `_` are told apart by what is on disk."""
  name, pending = Path(project).name, [Path("/")]
  while pending:
    try: children = list(pending.pop().iterdir())
    except OSError: continue   # unreadable, so not where a project ran
    for child in children:
      flat = re.sub(r"[^A-Za-z0-9]", "-", str(child))
      if flat != name and not name.startswith(f"{flat}-"): continue   # by name first, so only a match is read from disk
      try:
        if not child.is_dir(): continue
      except OSError: continue   # one entry that cannot be read, not the whole folder
      if flat == name: return child
      pending.append(child)   # the next `-` is this child's `/`
  return None


def places() -> list[Path]:
  """Every directory Claude Code has run a project in that still exists, each once."""
  return sorted({found for project in projects().glob("*/") if (found := place(project))})
