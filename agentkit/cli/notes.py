"""Commands for notes and standards: making a `.agents`, what governs a file, and keeping maps current."""

import json
import sys
import uuid
from pathlib import Path

from agentkit import inject, manifest, notes, standards, tree
from agentkit.command import arg, command
from agentkit.cli.out import done, dump, escape, fail, line, table

# what `agent inject` exits with, the one place they are defined: hooks/inject.sh and hooks/session-start.sh compare against these numbers, and tests/test_hooks.py holds them to it
SENT, ALREADY_SENT, NOTHING_GOVERNS = 0, 1, 3


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
@arg("--start", action="store_true", help="FILE is the directory a session starts in: its notes, from the repo root down, and no standards")
@arg("--depends", action="store_true", help="when there is nothing to send, print the paths whose change could change that, one per line, for the hook's gate")
def cmd_inject(args) -> int:
  """Exit SENT when it printed something, ALREADY_SENT when everything governing the file was already sent, NOTHING_GOVERNS when nothing does."""
  path = Path(args.file)
  # a fresh session each run by hand, so nothing one run stamps hides the next
  text, keys, governed = (inject.start if args.start else inject.payload)(path, args.session or f"look-{uuid.uuid4().hex}")

  warn = ""
  if args.edit:
    # a payload that is not what Claude Code sends must not cost the edit its standards
    try: payload = json.loads(sys.stdin.read() or "{}")
    except ValueError: payload = {}   # bad JSON, or bytes that are not text
    tool = (payload.get("tool_input") if isinstance(payload, dict) else None) or {}
    warn = notes.abandoned(path, tool.get("old_string") or "", tool.get("new_string") or "")

  sent = "\n\n".join(filter(None, (text, warn)))
  if not sent:
    if args.depends: line("\n".join(str(watched) for watched in inject.depends(path)))
    return ALREADY_SENT if governed else NOTHING_GOVERNS
  line(sent)
  if args.session: inject.mark(args.session, keys)   # after it is out, and never for the warning
  return SENT


@command("standards", help="which standards govern a file")
@arg("file", help="the file whose standards to list")
def cmd_standards(args) -> int:
  path = Path(args.file)
  layers = inject.library_for(path).for_file(notes.match_name(path))
  if not layers: return fail(f"no standard governs {path.name}")
  return table(["standard", "from", "what"], [[escape(layer.doc.name), escape(layer.origin), escape(layer.doc.get("description") or "")] for layer in layers], wide=("what",))


@command("remap", help="refresh the section table at the top of each note, and the standards table in the hub's AGENTS.md and the profile's")
@arg("path", nargs="?", default=".", help="a note, an AGENTS.md or a standard it lists, or a directory to remap every note in, under or above (default: here)")
@arg("--if-note", action="store_true", help="skip a file that is neither a note nor behind a standards table rather than fail, as the hook does for every .md under a .agents/")
def cmd_remap(args) -> int:
  path = Path(args.path).resolve()          # resolve first: Path(".").name is empty
  if not path.exists(): return fail(f"no such path: {args.path}")
  # a standards table is rebuilt from its AGENTS.md, a standard it lists, or a directory it sits in, under or above
  tables = standards.tables()
  rebuilt = [agents_md for agents_md, directory in tables.items()
             if (path == agents_md or path in standards.files(directory) if path.is_file() else agents_md.is_relative_to(path) or path.is_relative_to(agents_md.parent))]
  if path.is_file() and not notes.is_note(path) and not rebuilt: return done(f"skipped  {path}, not a note") if args.if_note else fail(f"{path.name} is not a note; only files in a .agents/ carry a map")

  targets = ([path] if notes.is_note(path) else []) if path.is_file() else tree.note_dirs_for(path)
  if not targets and not rebuilt: return fail(f"no .agents in, under or above {path}")
  lines = [("remapped " if notes.remap(target) else "current  ") + str(target) for target in targets]
  for agents_md in rebuilt:
    if changed := (text := standards.table(agents_md, tables[agents_md])) != agents_md.read_text(encoding="utf-8"): agents_md.write_text(text, encoding="utf-8")
    lines.append(("remapped " if changed else "current  ") + str(agents_md))
  return done(*lines)


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
  return dump(manifest.notes(args.notes) if args.notes is not None else manifest.bundled())
