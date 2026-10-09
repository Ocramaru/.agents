"""Fan an agent out over many files, one session each.

One file per session keeps findings specific, costs one file per failure, and never needs the repo in one context window.

Author: Marco Cassar (@Ocramaru)
"""

import fnmatch
import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agentkit import agents, inject, notes, reviews, tree, profile as _profile
from agentkit.backends import Backend
from agentkit.session import Message, Session
from agentkit.standards import Library


def skipped(path: Path, root: Path) -> bool:
  """Whether `path` sits under a directory no review reads, judged from `root` down.
  Judged on the absolute path, every file of a repo living under a directory called `build` or `vendor` is skipped."""
  try: parts = Path(path).resolve().relative_to(Path(root).resolve()).parts
  except ValueError: parts = Path(path).parts
  return any(tree.ignored(directory) for directory in parts[:-1])


def _matches(name: str, globs: list[str]) -> bool:
  """Basename globs, as a standard's `applies` are written."""
  return any(fnmatch.fnmatch(name, glob) for glob in globs)


def discover(root: Path, exclude: list[str], max_bytes: int) -> list[Path]:
  """The files under `root` that a review may read: not in a skipped directory, not excluded, not over `max_bytes`. `exclude` matches the relative path.
  Names are filtered before any file is stat'ed, since the stat is the costly part."""
  # git's tracked files honour .gitignore; -z, since git otherwise quotes a non-ASCII name that exists on no disk
  listed = _profile.git(root, "ls-files", "-z")
  if listed.returncode == 0: relatives = [name for name in listed.stdout.split("\0") if name]
  else:   # no git: a walk that never enters a skipped directory
    relatives = []
    for here, directories, files in os.walk(root):   # pruned before descending, where rglob walks everything and filters after
      directories[:] = [directory for directory in directories if not tree.ignored(directory)]
      base = Path(here).relative_to(root)
      relatives += [(base / name).as_posix() for name in files]

  out = []
  for relative in relatives:
    parts = relative.split("/")
    if any(tree.ignored(directory) for directory in parts[:-1]): continue
    if any(fnmatch.fnmatch(relative, glob) for glob in exclude): continue
    path = Path(root) / relative
    if path.is_file() and path.stat().st_size <= max_bytes: out.append(path)
  return sorted(out)


EMPTY = "empty, nothing to review"


def new_run() -> str:
  """An invocation's id, readable and sortable.
  A uuid7's leading digits change about once a minute, so they do not tell two runs apart."""
  return f"{time.strftime('%m%d-%H%M')}-{uuid.uuid4().hex[:4]}"
AUTO = "auto"   # the agent name that means "whichever agents govern the file"


def library(path: Path, libraries: dict[Path, Library]) -> Library:
  """The standards that govern a file's directory, resolved through `library_for` as inject resolves them so the repo's [applies] counts.
  Kept in `libraries` by directory."""
  if (directory := Path(path).parent) not in libraries: libraries[directory] = inject.library_for(path)
  return libraries[directory]


def plan(names: list[str], found: dict, files: list[Path], discovered: list[Path], libraries: dict[Path, Library],
         globs: list[str] | None = None, explicit: bool = True) -> list[tuple[str, list[Path]]]:
  """What each agent reads; within a kind, each file goes to the most specific agent that takes it.
  An agent takes a file inside its own `applies`, if any, that a standard it judges against governs.
  A file named on the command line skips the filter unless the agent has its own `applies`; one from a commit never does."""
  plans, kind = [], agents.kind_of(found)

  for name in names:
    definition = agents.definition(name, found)
    own = definition.list("applies")
    if globs: keep = lambda path: _matches(path.name, globs)
    else: keep = lambda path, definition=definition, own=own: (not own or _matches(notes.match_name(path), own)) and bool({standard.doc.name for standard in library(path, libraries).for_file(notes.match_name(path))} & set(definition.list("standards")))
    selected = list(files) if explicit and len(names) == 1 and not globs and not own else [file for file in files if keep(file)]
    selected = sorted(set(selected + [path for path in discovered if keep(path)]))
    if selected: plans.append((name, selected))

  # the agent named after its kind is the general one: `refine` takes what `refine.learned` leaves
  taken = {(kind[name], path) for name, selected in plans if name != kind[name] for path in selected}
  return [(name, kept) for name, selected in plans if (kept := [path for path in selected if name != kind[name] or (name, path) not in taken])]


def variant(kind: str, name: str, kinds: dict[str, list[str]]) -> str:
  """The agent `--variant` picks within a kind: `default` is the general one, any other name the one after the dot."""
  if (family := kinds.get(kind)) is None: raise ValueError(f"{kind} is not a kind of review")

  named = {"default" if member == kind else member.removeprefix(f"{kind}."): member for member in family if member == kind or member.startswith(f"{kind}.")}
  if name not in named: raise ValueError(f"{kind} has no {name!r} variant" + (f"; it has {', '.join(named)}" if named else ""))
  return named[name]


def globs_of(definition, standards: Library) -> list[str]:
  """What this agent reads: its own `applies`, else the globs of every standard it judges against."""
  if definition.list("applies"): return definition.list("applies")
  return [glob for name in definition.list("standards") if name in standards.docs for glob in standards.docs[name].list("applies")]


def label(path: Path, root: Path) -> str:
  """What to call a file: relative to the root, or absolute when named explicitly from outside it."""
  try: return str(path.relative_to(root))
  except ValueError: return str(path)


def findings(data) -> list[dict]:
  """Findings out of `data`, whether the `findings` mapping asked for or a bare list.
  A model returns the bare list about as often as the mapping, and reading `[]` off it loses a real review."""
  found = data if isinstance(data, list) else data.get("findings") if isinstance(data, dict) else None
  if not isinstance(found, list): return []
  # an entry with no issue text is not a finding
  return [finding for finding in found if isinstance(finding, dict) and str(finding.get("issue", "")).strip()]


def recheck(text: str, root: Path, relative: str) -> str:
  """A reply to a review, carrying the file as it is now.
  The reviewer has no tools and holds only the version it was first shown, so a recheck without the file judges that one."""
  path = Path(root) / relative
  if not path.is_file(): return f"{text}\n\nThe file has since been deleted."
  if not (current := path.read_text(encoding="utf-8")).strip(): return f"{text}\n\nThe file is now empty."
  return f"{text}\n\nThe file as it is now, which is what to judge:\n\n{agents.prompt([(str(path), current)])}"


def task_id(agent: str, root: Path, relative: str) -> str:
  """A conversation's id within its repo's ledger: one per reviewer and file."""
  return f"review-{agent}-{Path(root).name}-{relative.replace('/', '_').strip('_')}"


DISMISSED = ("Already raised on this file and closed by someone who read it. Do not raise these "
             "again unless the reason given no longer holds; if it no longer does, say so.")


def file(agent: str, backend: Backend, path: Path, definition, tier: str, root: Path,
        dismissed: list[dict] | None = None, on_start=None, run: str | None = None, *,
        effort: str | None = None, previous: dict | None = None, libraries: dict[Path, Library]) -> tuple[dict, dict | None]:
  """One file's review: skipped if empty, reused if its verdict still stands, otherwise asked."""
  relative, began = label(path, root), time.monotonic()
  if on_start: on_start(relative)
  session = Session(task_id(agent, root, relative))

  if not (text := path.read_text(encoding="utf-8")).strip():
    # nothing to judge, but recorded as a review so findings from before it was emptied stop being open
    message = session.post(Message(agent, "findings", "completed", EMPTY))   # a verdict, so it supersedes
    return ({"file": relative, "agent": agent, "task": session.task, "state": message.state, "kind": message.kind,
             "body": message.body, "findings": [], "seconds": 0.0}, reviews.record(session, agent, backend.name, root, relative, message, [], tier, run))

  # inject's resolution, [applies] and local overrides included, so a file is reviewed under the rules it was written under
  instructions = agents.instructions(definition, library(path, libraries), path)
  body = agents.prompt([(str(path), text)])

  # what a verdict judged: the file, the instructions and standards, the model, the effort
  judged = hashlib.sha256("\0".join(part or "" for part in (body, instructions, tier, backend.name, effort)).encode()).hexdigest()[:16]
  if previous and previous["digest"] == judged:   # nothing it read has changed, so neither would its answer
    return {"file": relative, "agent": agent, "task": session.task, "state": "completed", "kind": "findings",
            "body": previous["body"], "findings": previous["findings"], "seconds": 0.0,
            "reused": previous["run"] or "an earlier run"}, None

  # closed findings go to the reviewer with their reasons, or it raises them again
  if dismissed:
    body += f"\n\n{DISMISSED}\n\n" + "\n".join(
      f"- line {closure['line']}: {closure['issue']} (closed as {closure['verdict']}: {closure['reason'] or 'no reason given'})"
      for closure in dismissed)

  message = session.send(agent, backend, body, instructions=instructions, tier=tier, effort=effort)
  found = findings(message.data)
  # assigned, not setdefault: the file is known here, and a path the model echoes may match nothing in the ledger
  for finding in found: finding["file"] = relative

  return ({"file": relative, "agent": agent, "task": session.task, "state": message.state, "kind": message.kind,
           "body": message.body, "findings": found, "seconds": round(time.monotonic() - began, 1)},
          reviews.record(session, agent, backend.name, root, relative, message, found, tier, run, judged))


def run(agent: str, backend: Backend, paths: list[Path], root: Path, definition, libraries: dict[Path, Library], tier: str | None = None,
        jobs: int = 4, on_start=None, on_done=None, run: str | None = None,
        effort: str | None = None, fresh: bool = False) -> list[dict]:
  """One conversation per file, `jobs` at a time, each result reported as it finishes, not in the order asked.
  A file whose verdict still stands (same content, standards, model and effort) is not asked again unless `fresh`."""
  tier, effort = tier or definition.get("model"), effort or definition.get("effort") or None

  # read before the writer opens: duckdb will not hold a read-only and a read-write connection to one file in one process
  try:
    closed, known = reviews.dismissals(root), {} if fresh else reviews.verdicts(root)
  except Exception: closed, known = {}, {}   # noqa: BLE001 -- no memory of earlier runs beats no review

  jobs = max(1, min(jobs, backend.parallel))   # never more than the backend declares it takes
  results = []
  with reviews.writer(root) as put, ThreadPoolExecutor(max_workers=jobs) as pool:
    asked = {pool.submit(file, agent, backend, path, definition, tier, root, closed.get(label(path, root)), on_start, run,
                         effort=effort, previous=known.get(task_id(agent, root, label(path, root))), libraries=libraries): path
             for path in paths}

    for future in as_completed(asked):
      try:
        result, record = future.result()
        if record: put(record)   # a verdict that still stands is already in the ledger
      except Exception as error:  # noqa: BLE001 -- one file failing is that file's result
        result = {"file": label(asked[future], root), "agent": agent, "state": "failed", "kind": "note",
                  "body": f"{type(error).__name__}: {error}", "findings": []}   # named, so the report says which file failed
      results.append(result)
      if on_done: on_done(result)
  return results
