"""Machine-readable description of the hub, for indexers that are not this code.
An indexer reads this rather than parsing frontmatter, so the format of a standard stays ours to change; INTEGRATION.md is the contract.

Author: Marco Cassar (@Ocramaru)
"""

import re
from pathlib import Path

from agentkit import agents, tree
from agentkit.frontmatter import load
from agentkit.notes import NOTES
from agentkit.standards import GLOBAL, Library

SCHEMA = "agents-hub/1"


def hub() -> dict:
  """The hub's standards and reviewers, for indexers."""
  root = GLOBAL.parent

  reviewers = {}
  for name, definition in agents.definitions(root / "agents").items():
    reviewers[name] = {"path": str(definition.path), "description": definition.get("description"),
                       "standards": definition.list("standards"), "model": definition.get("model"),
                       "tools": definition.get("tools", "none")}
  return {"schema": SCHEMA, "kind": "hub", "root": str(root),
          "standards": Library(root / "standards").index(), "agents": reviewers}


def notes(root: Path) -> dict:
  """Every `.agents/` note directory under a tree, with what each file declares and whether it is the hub's."""
  root = Path(root).resolve()
  found = []
  for agents_dir in tree.find_note_dirs(root):
    files = {}

    for name in NOTES:
      note = agents_dir / f"{name}.md"
      if not note.is_file(): continue
      document = load(note)
      # wikilink targets, so an indexer gets the graph without a markdown parser
      files[name] = {"path": str(note), "description": document.get("description"),
                     "links": sorted({target for target in (link.split("|")[0].split("#")[0].strip() for link in re.findall(r"\[\[(.*?)\]\]", document.body)) if target})}
    if files: found.append({"dir": str(agents_dir), "scope": str(agents_dir.parent), "hub": tree.is_hub(agents_dir), "files": files})
  return {"schema": SCHEMA, "kind": "notes", "root": str(root), "notes": found}
