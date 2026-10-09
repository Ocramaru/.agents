"""Everything a file needs in context (standards, notes and open findings), resolved in one pass.
One pass is one interpreter start and one stamp directory for the whole answer.
Standards layer along the `.agents` chain, and where two disagree the nearest wins.

Author: Marco Cassar (@Ocramaru)
"""

import hashlib
import tempfile
from pathlib import Path

from agentkit import notes, tree
from agentkit.standards import GLOBAL, Library, scoped

MENTION = "Not loaded. Read one when you have a reason to."


def library_for(path: Path) -> Library:
  """Machine-wide standards, layered along the chain, nearest last.
  A repo names its own files for a standard in `[applies]`, since one project's entry point is another's ordinary script."""
  links, extra = tree.chain(path), {}
  for agents_dir in links:
    for name, globs in flatten_applies(tree.toml(agents_dir).get("applies") or {}).items(): extra.setdefault(name, []).extend(globs)
  return Library(GLOBAL, [agents_dir / "standards" for agents_dir in links if (agents_dir / "standards").is_dir()], extra)


def flatten_applies(table: dict, prefix: str = "") -> dict[str, list[str]]:
  """An `[applies]` table as standard name -> globs, a bare string being one glob.
  TOML reads a dotted key as a path, so `ml.runs = [...]` arrives nested unless quoted; both spellings work."""
  out: dict[str, list[str]] = {}
  for key, value in table.items():
    name = f"{prefix}{key}"
    if isinstance(value, dict): out.update(flatten_applies(value, f"{name}."))
    elif isinstance(value, list): out[name] = [str(pattern) for pattern in value]
    elif isinstance(value, str): out[name] = [value]
  return out


def _stamp(session: str, key: Path | str) -> Path:
  """The stamp for `key`, per session, in the directory `hooks/forget.sh` clears on compaction."""
  return Path(tempfile.gettempdir()) / f"agents-{session}" / hashlib.md5(str(key).encode()).hexdigest()[:16]


def payload(path: Path, session: str) -> tuple[str, list[Path | str], bool]:
  """What this file needs in context and has not had this session, the stamp keys of what that holds, and whether anything governs the file at all.
  It stamps nothing; `mark` does once the text is out, so a failure in between is not recorded as delivered."""
  path, parts, keys = Path(path), [], []
  match = notes.match_name(path)
  layers, links, found = library_for(path).for_file(match), tree.chain(path), open_findings(path)

  rules = [layer for layer in layers if not _stamp(session, layer.doc.path).exists()]
  late = [(layer, heading, text) for layer in layers if layer not in rules for heading, text in scoped(layer.doc.body, match) if not _stamp(session, f"{layer.doc.path}#{heading}").exists()]   # a section for this file, unsent though its standard went out
  if rules or late:
    parts.append("Standards governing this file. They layer rather than replace: later ones refine earlier ones, and where two disagree the later wins.\n\n" + "\n\n".join([f"{layer.header}\n{layer.for_name(match)}" for layer in rules] + [f"{layer.section_header(heading)}\n{text}" for layer, heading, text in late]))
    keys += [key for layer in rules for key in (layer.doc.path, *(f"{layer.doc.path}#{heading}" for heading, _ in scoped(layer.doc.body, match)))] + [f"{layer.doc.path}#{heading}" for layer, heading, _ in late]

  if found:
    from agentkit import reviews   # only once there are findings, which means duckdb is already loaded
    body = "\n".join(f"  {reviews.short_id(finding['id'])}  {finding['file']}:{finding['line']}  {finding['issue']}" for finding in found)
    # the key hashes the findings, so those from a review landing mid-session are sent too
    if not _stamp(session, key := f"findings:{path.resolve()}:{hashlib.md5(body.encode()).hexdigest()[:8]}").exists():
      parts.append(f"Open review findings on this file. A reviewer has already read it and these are not addressed yet. Fix one, or if it is wrong or not worth fixing, record that so the next review does not raise it again:\n  agent sub close <id> --as wrong --reason '<why>'\n\n{body}")
      keys.append(key)

  notes_text, mention, sent = tree.payload(path, skip={note for agents_dir in links for kind in tree.INJECTABLE for _, note in tree.note_parts(agents_dir, kind, path) if _stamp(session, note).exists()})
  if notes_text:
    parts.append(f"Notes from .agents on the path to this file. Read before changing behaviour.\n\n{notes_text}")
    keys += sent
  if mention and not _stamp(session, key := f"mention:{path.parent}").exists():
    parts.append(f"{MENTION}\n  " + "\n  ".join(mention))
    keys.append(key)
  return "\n\n".join(parts), keys, bool(layers or links or found)


def mark(session: str, keys: list[Path | str]) -> None:
  """Stamp what `payload` sent, once it is out."""
  for key in keys:
    (stamp := _stamp(session, key)).parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()


def open_findings(path: Path) -> list[dict]:
  """What the newest review of this file still reports.
  It returns nothing rather than fail an edit, and checks for the ledger first so an unreviewed repo never imports duckdb."""
  path = Path(path).resolve()
  root = tree.git_root(path.parent) or path.parent

  try:
    from agentkit import reviews
    if not reviews.path(root, create=False).is_file() or not path.is_relative_to(root): return []   # outside its repo, nothing in the ledger can name it
    return [finding for finding in reviews.open_findings(root) if finding.get("file") == path.relative_to(root).as_posix()]
  except Exception: return []   # noqa: BLE001 -- enrichment must never block an edit
