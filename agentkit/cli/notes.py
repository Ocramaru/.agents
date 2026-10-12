"""Commands for notes and standards: making a `.agents`, what governs a file, and keeping maps current.

Author: Marco Cassar (@Ocramaru)
"""

import json
import sys
import uuid
from pathlib import Path

from agentkit import inject, manifest, notes, tree
from agentkit.command import arg, command
from agentkit.cli.out import done, dump, escape, fail, line, table


@command("init", help="create a .agents here")
@arg("dir", nargs="?", default=".", help="the directory to give a .agents (default: here)")
def cmd_init(args) -> int:
  created = tree.init(Path(args.dir))
  return done(f"{'created' if created['made'] else 'found'} {created['path']}", *(f"added    {added}" for added in created["added"]),
              *([f"inherits {inherited}" for inherited in created["inherits"]] or ["nothing above it in this repo"]))


@command("context", help="notes governing a file, budgeted nearest-first")
@arg("file", help="the file whose notes to show")
def cmd_context(args) -> int:
  body, mention, _ = tree.payload(Path(args.file))
  return done(body or None, "\nnot loaded:\n  " + "\n  ".join(mention) if mention else None,
              code=0 if body or mention else 1)


@command("inject", help="standards and notes for a file, deduped per session")
@arg("file", help="the file about to be edited")
@arg("--session", default=None, help="dedupe against this session; without one, show everything and stamp nothing")
@arg("--edit", action="store_true", help="read the hook payload on stdin, to notice what an edit removes")
def cmd_inject(args) -> int:
  """Exit 0 when it printed something, 1 when everything governing the file was already sent, 3 when nothing does."""
  path = Path(args.file)
  # a fresh session each run by hand, so nothing one run stamps hides the next
  text, keys, governed = inject.payload(path, args.session or f"look-{uuid.uuid4().hex}")

  warn = ""
  if args.edit:
    # a payload that is not what Claude Code sends must not cost the edit its standards
    try: payload = json.loads(sys.stdin.read() or "{}")
    except ValueError: payload = {}   # bad JSON, or bytes that are not text
    tool = (payload.get("tool_input") if isinstance(payload, dict) else None) or {}
    warn = notes.abandoned(path, tool.get("old_string") or "", tool.get("new_string") or "")

  sent = "\n\n".join(filter(None, (text, warn)))
  if not sent: return 1 if governed else 3
  line(sent)
  if args.session: inject.mark(args.session, keys)   # after it is out, and never for the warning
  return 0


@command("standards", help="which standards govern a file")
@arg("file", help="the file whose standards to list")
def cmd_standards(args) -> int:
  path = Path(args.file)
  layers = inject.library_for(path).for_file(notes.match_name(path))
  if not layers: return fail(f"no standard governs {path.name}")
  return table(["standard", "from", "what"], [[escape(layer.doc.name), escape(layer.origin), escape(layer.doc.get("description") or "")] for layer in layers], wide=("what",))


@command("remap", help="refresh the section table at the top of each note")
@arg("path", nargs="?", default=".", help="a note, or a directory to remap every note in, under or above (default: here)")
def cmd_remap(args) -> int:
  path = Path(args.path).resolve()          # resolve first: Path(".").name is empty
  if not path.exists(): return fail(f"no such path: {args.path}")
  if path.is_file() and not notes.is_note(path): return fail(f"{path.name} is not a note; only files in a .agents/ carry a map")

  targets = [path] if path.is_file() else tree.note_dirs_for(path)
  if not targets: return fail(f"no .agents in, under or above {path}")
  return done(*(("remapped " if notes.remap(target) else "current  ") + str(target) for target in targets))


@command("split", help="break a note into a directory, one file per section")
@arg("file", help="the note to split, such as .agents/learned.md")
def cmd_split(args) -> int:
  try:
    written = notes.split(Path(args.file))
  except ValueError as error:
    return fail(f"{error}; add a section as a new file there instead")
  if not written: return fail(f"no ## sections in {args.file}")
  return done(*written)


@command("manifest", help="machine-readable description of the hub, for indexers")
@arg("--notes", nargs="?", const=".", metavar="ROOT", help="instead list .agents note directories under ROOT (default: here)")
def cmd_manifest(args) -> int:
  return dump(manifest.notes(args.notes) if args.notes is not None else manifest.hub())
