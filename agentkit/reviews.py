"""Review conversations, in an append-only DuckDB ledger under the repo they are about; a reply is a new row.
Keys are uuid7, so `id > last_seen` is the sync cursor and rows from two machines never conflict.
DuckDB is imported where it is used, so `agent inject`, `agent standards` and the hooks run with nothing installed.

Author: Marco Cassar (@Ocramaru)
"""

import fnmatch
import getpass
import json
import os
import queue
import re
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from agentkit import agents, tree
from agentkit.session import Message, Session

DIR = ".reviews"
DB = "reviews.duckdb"
IGNORE = ".reviews/\n"

SCHEMA = """
create table if not exists reviews (
  id text primary key, task text, "at" double, author text, agent text, backend text, tier text,
  root text, file text, state text, kind text, body text, max_turns integer,
  handles json, messages json
);
create table if not exists findings (
  id text primary key, review_id text, task text, author text, file text, line text,
  issue text, failure text, fix text, "at" double, closed_by text
);
create table if not exists closures (
  id text primary key, finding_id text, task text, file text, line text, issue text,
  author text, "at" double, verdict text, reason text
);
-- the invocation a review belonged to, so "what did that run say" has an answer. Added, not
-- created, so a ledger from before it gains the column instead of failing every insert.
alter table reviews add column if not exists run text;
-- what a verdict judged -- file, instructions, model, effort -- so an unchanged file need not be asked again
alter table reviews add column if not exists digest text;
"""

# closing verdicts: `wrong` and `wontfix` go to the next reviewer so it does not raise them; `fixed` is a claim it checks
VERDICTS = ("fixed", "wrong", "wontfix")
KEEP_QUIET = ("wrong", "wontfix")


def uuid7() -> uuid.UUID:
  """An RFC 9562 v7 UUID: 48 bits of millisecond, then randomness.
  `uuid.uuid7` exists only from Python 3.14."""
  raw = bytearray(os.urandom(16))
  raw[0:6] = (int(time.time() * 1000) & 0xFFFFFFFFFFFF).to_bytes(6, "big")
  raw[6] = (raw[6] & 0x0F) | 0x70   # version
  raw[8] = (raw[8] & 0x3F) | 0x80   # variant
  return uuid.UUID(bytes=bytes(raw))


def author() -> str:
  """Who wrote a row, as user@host, so rows from two machines stay distinguishable."""
  try:
    return f"{getpass.getuser()}@{socket.gethostname()}"
  except Exception: return "unknown"   # noqa: BLE001 -- getuser raises with no passwd entry


def path(root: Path, create: bool = True) -> Path:
  """The database under the repo's outermost `.agents`. A repo's reviews belong to that repo."""
  directory = (tree.git_root(root) or Path(root)) / ".agents" / DIR

  if create:
    directory.mkdir(parents=True, exist_ok=True)
    ignore = directory.parent / ".gitignore"
    if not ignore.is_file(): ignore.write_text(IGNORE, encoding="utf-8")
  return directory / DB


def connect(root: Path, read_only: bool = False, tries: int = 1):
  """A connection with the schema in place. Raises if duckdb is missing, which only review needs.
  DuckDB gives one process the write lock and concurrent reviews are normal, so a writer retries for it."""
  try:
    import duckdb
  except ModuleNotFoundError as error:
    raise RuntimeError("reviews need duckdb: `uv sync` in ~/.agents, or install it yourself") from error

  database = path(root, create=not read_only)
  if read_only and not database.is_file(): return None

  last = None
  for attempt in range(tries):
    try:
      connection = duckdb.connect(str(database), read_only=read_only)
      if not read_only: connection.execute(SCHEMA)
      return connection
    except duckdb.IOException as error:
      last = error
      if attempt + 1 < tries: time.sleep(0.5 * (attempt + 1))

  raise last


def record(session: Session, agent: str, backend: str, root: Path, file: str, message, findings: list,
           tier: str, run: str | None = None, digest: str | None = None) -> dict:
  """One conversation as a row, flat enough to read and complete enough to resume.
  `tier` is stored because a reply continues on the model the review was done with."""
  return {"id": str(uuid7()), "task": session.task, "at": time.time(), "author": author(), "agent": agent,
          "backend": backend, "tier": tier, "root": str(root), "file": file, "state": message.state,
          "kind": message.kind, "body": message.body, "findings": findings, "max_turns": session.max_turns,
          "handles": session.handles, "messages": [turn.__dict__.copy() for turn in session.messages], "run": run, "digest": digest}


def _insert(connection, record: dict) -> None:
  if record.get("closure"):   # a closure rides the same queue as a review, so one writer does both
    closure = record["closure"]
    connection.execute("insert into closures values (?,?,?,?,?,?,?,?,?,?)",
                       [closure["id"], closure["finding_id"], closure["task"], closure["file"], str(closure["line"]), closure["issue"],
                        closure["author"], closure["at"], closure["verdict"], closure["reason"]])
    return

  connection.execute(   # named columns, so adding one does not shift the values
    """insert into reviews (id, task, "at", author, agent, backend, tier, root, file, state, kind, body,
                            max_turns, handles, messages, run, digest) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    [record["id"], record["task"], record["at"], record["author"], record["agent"], record["backend"], record["tier"],
     record["root"], record["file"], record["state"], record["kind"], record["body"], record["max_turns"],
     json.dumps(record["handles"]), json.dumps(record["messages"]), record.get("run"), record.get("digest")])

  if record["findings"]:
    connection.executemany("insert into findings values (?,?,?,?,?,?,?,?,?,?,?)",
                           [[str(uuid7()), record["id"], record["task"], record["author"], finding.get("file", record["file"]),
                             str(finding.get("line", "")), finding.get("issue", ""), finding.get("failure", ""), finding.get("fix", ""),
                             record["at"], None] for finding in record["findings"]])


@contextmanager
def writer(root: Path):
  """Yield a `put` that queues a record. One thread owns the connection and does every write.
  DuckDB allows a single writer, so workers hand over a dict and never touch the database."""
  inbox: queue.Queue = queue.Queue()
  failures: list[Exception] = []

  def flush(pending: list) -> None:
    """Take the lock, write what has arrived, give it back. Held for an insert, not for a review."""
    if not pending: return
    connection = None
    try:
      connection = connect(root, tries=12)
      for record in pending: _insert(connection, record)
    except Exception as error:  # noqa: BLE001 -- collected, raised once the queue drains
      failures.append(error)   # collect rather than raise: dying here loses the rest of the queue
    finally:
      if connection is not None: connection.close()
      pending.clear()

  def drain():
    pending: list = []
    for record in iter(inbox.get, None):       # the sentinel is the only way out
      pending.append(record)
      if inbox.empty(): flush(pending)      # nothing waiting, so let go of the lock
    flush(pending)

  thread = threading.Thread(target=drain, name="reviews-writer", daemon=True)
  thread.start()
  try:
    yield inbox.put
  finally:
    inbox.put(None)
    thread.join()

  if failures: raise failures[0]


def write(record: dict, root: Path) -> str:
  """One record through the same queue, for a caller that has only the one to write."""
  with writer(root) as put: put(record)
  return record["id"]


@contextmanager
def _reading(root: Path):
  """One read-only connection for a whole operation, closed after; None when there is no ledger yet."""
  connection = connect(root, read_only=True)
  try: yield connection
  finally:
    if connection is not None: connection.close()


def _select(connection, sql: str, parameters: list | None = None) -> list[dict]:
  """The rows of a query on an open connection, as dicts, with the json columns decoded."""
  cursor = connection.execute(sql, parameters or [])
  columns = [column[0] for column in cursor.description]
  rows = [dict(zip(columns, values)) for values in cursor.fetchall()]

  for row in rows:
    for key in ("handles", "messages"):
      if isinstance(row.get(key), str): row[key] = json.loads(row[key])
  return rows


def query(root: Path, sql: str, parameters: list | None = None) -> list[dict]:
  """Read-only, so a review running in another process does not block a look at the ledger."""
  with _reading(root) as connection:
    return [] if connection is None else _select(connection, sql, parameters)


def conversations(root: Path, limit: int = 0, task: str | None = None) -> list[dict]:
  """Conversations oldest first, each with the findings it recorded; the newest `limit`, of one `task` if given."""
  where, parameters = ("where task = ? ", [task]) if task else ("", [])
  newest = f"select * from reviews {where}order by id desc{f' limit {int(limit)}' if limit else ''}"

  with _reading(root) as connection:
    if connection is None: return []
    rows = _select(connection, f"select * from ({newest}) order by id", parameters)   # the uuid7 key is already in time order
    found = _select(connection, f"select review_id, file, line, issue, failure, fix from findings where review_id in (select id from ({newest})) order by id", parameters)

  by_review: dict[str, list] = {}
  for finding in found: by_review.setdefault(finding.pop("review_id"), []).append(finding)
  for review in rows: review["findings"] = by_review.get(review["id"], [])
  return rows


def verdicts(root: Path) -> dict[str, dict]:
  """Each task's latest verdict with a digest and its open findings, checked before asking a model again.
  Read before a writer opens, since duckdb will not hold both connections in one process."""
  with _reading(root) as connection:
    if connection is None or not _has(connection, "reviews", "digest"): return {}

    out = {row["task"]: {**row, "findings": []} for row in _select(connection, f"""select task, digest, run, body from reviews r
                           where digest is not null and state = 'completed'
                             and id = (select max(id) from reviews r2 where r2.task = r.task and {SUPERSEDES})""")}
    for finding in _open(connection, root):
      if finding["task"] in out: out[finding["task"]]["findings"].append(finding)
    return out


def last_run(root: Path) -> str | None:
  """The newest run's id, or None on a ledger no run has been recorded in."""
  with _reading(root) as connection:
    if connection is None or not _has(connection, "reviews", "run"): return None   # read-only cannot add the column; nothing to find
    rows = _select(connection, "select run from reviews where run is not null order by id desc limit 1")
    return rows[0]["run"] if rows else None


def filtered(rows: list[dict], root: Path, agent: str | None = None, path: str | None = None,
             failed: bool = False, run: str | None = None) -> list[dict]:
  """The rows asked for: `path` a folder or a file pattern, `agent` an agent or a kind, `run` an id prefix."""
  folder = path and (path.endswith("/") or (Path(root) / path).is_dir())
  prefix = path.rstrip("/") + "/" if folder else ""
  kind_of = agents.kind_of(agents.definitions()) if agent else {}

  def wanted(row: dict) -> bool:
    file = str(row.get("file", ""))
    if agent and agent not in (row.get("agent"), kind_of.get(row.get("agent"))): return False
    if folder and not file.startswith(prefix): return False
    if path and not folder and not (fnmatch.fnmatch(file, path) or fnmatch.fnmatch(Path(file).name, path)): return False
    if failed and row.get("state") != "failed": return False
    return not run or str(row.get("run") or "").startswith(run)

  return [row for row in rows if wanted(row)]


def _has(connection, table: str, column: str | None = None) -> bool:
  """Whether a table, or a column of it, exists yet.
  A read-only connection cannot create either, so a reader checks rather than assumes the current schema."""
  if column is None:
    return bool(_select(connection, "select 1 from information_schema.tables where table_name = ?", [table]))
  return bool(_select(connection, "select 1 from information_schema.columns where table_name = ? and column_name = ?",
                      [table, column]))


# only a verdict replaces a verdict: a question or a failed recheck leaves the open findings open
SUPERSEDES = "(r2.kind = 'findings' or exists (select 1 from findings f2 where f2.review_id = r2.id))"


def open_findings(root: Path) -> list[dict]:
  """Findings from each task's newest review. An older review's findings are superseded, not open."""
  with _reading(root) as connection:
    return [] if connection is None else _open(connection, root)


def _open(connection, root: Path) -> list[dict]:
  """`open_findings` on a connection already open. Paths come back relative to the repo, since a stored one may be the absolute path a model echoed."""
  base = (tree.git_root(root) or Path(root)).resolve()
  closed = "and f.id not in (select finding_id from closures)" if _has(connection, "closures") else ""
  rows = _select(connection, f"""
    select f.id, f.file, f.line, f.issue, f.fix, f.task, r.agent, r.at{", r.run" if _has(connection, "reviews", "run") else ""}
    from findings f join reviews r on r.id = f.review_id
    where f.closed_by is null {closed}
      and r.id = (select max(id) from reviews r2 where r2.task = r.task and {SUPERSEDES})""")
  rows = [row for row in rows if str(row.get("issue") or "").strip()]   # an entry with no issue text is not a finding

  for row in rows:
    stored = Path(row["file"])
    if stored.is_absolute():
      try: row["file"] = stored.resolve().relative_to(base).as_posix()
      except ValueError: pass

  return sorted([row for row in rows if (base / row["file"]).exists()], key=lambda row: (row["file"], first_line(row["line"])))   # nothing reviews a deleted file again


def short_id(finding_id: str) -> str:
  """What --open shows and close takes: the random tail of the uuid7, since its head is the clock."""
  return finding_id.replace("-", "")[-6:]


def to_recheck(root: Path) -> dict[str, list[str]]:
  """Files to ask about again, by agent: any with an open finding, or one closed as fixed after its last verdict.
  A `fixed` closure is a claim no reviewer has checked yet."""
  out: dict[str, set] = {}
  with _reading(root) as connection:
    if connection is None: return {}
    for finding in _open(connection, root): out.setdefault(finding["agent"], set()).add(finding["file"])

    if _has(connection, "closures"):
      base = tree.git_root(root) or Path(root)
      for row in _select(connection, f"""select distinct c.file, (select agent from reviews r where r.task = c.task limit 1) as agent
                               from closures c where c.verdict = 'fixed'
                                 and c."at" > (select max("at") from reviews r2 where r2.task = c.task and {SUPERSEDES})"""):
        if (base / row["file"]).exists(): out.setdefault(row["agent"], set()).add(row["file"])
  return {agent: sorted(files) for agent, files in sorted(out.items())}


def first_line(line) -> int:
  """The first number in a line field, so `133, 136 vs 137-139` sorts as 133.
  A reviewer's line field is prose as often as a number."""
  match = re.search(r"\d+", str(line))
  return int(match.group()) if match else 0


def latest(task: str, root: Path) -> dict | None:
  """The newest conversation for a task. A later row supersedes an earlier one."""
  rows = conversations(root, 1, task)
  return rows[0] if rows else None


def conversation(record: dict | None) -> Session | None:
  """A stored conversation, as `latest` returns it, as a resumable Session, so a review answers like any other agent."""
  if record is None: return None

  session = Session(record["task"], max_turns=record.get("max_turns") or 8)
  session.handles = record.get("handles") or {}
  session.messages = [Message(**message) for message in record.get("messages") or []]
  return session


def close(root: Path, file: str, line: int, verdict: str, reason: str = "") -> list[dict]:
  """Close the open findings in `file`, at `line` when it is not 0, or with an id as --open shows it in place of `file`. Returns what was closed.
  A closure is appended, never updated, so two machines closing the same finding both survive a sync."""
  if verdict not in VERDICTS: raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")

  by_id = re.fullmatch(r"[0-9a-f]{6}", file)   # an edit moves the line a review recorded; the id stays
  hits = [finding for finding in open_findings(root) if (short_id(finding["id"]) == file if by_id else
          finding["file"] == file and (not line or first_line(finding["line"]) == line))]

  who, now = author(), time.time()
  with writer(root) as put:
    for finding in hits:
      put({"closure": {"id": str(uuid7()), "finding_id": finding["id"], "task": finding["task"], "file": finding["file"],
                       "line": finding["line"], "issue": finding["issue"], "author": who, "at": now,
                       "verdict": verdict, "reason": reason}})
  return hits


def dismissals(root: Path) -> dict[str, list[dict]]:
  """What was closed as wrong or not worth fixing, by file, for the reviewer to read next time."""
  out: dict[str, list[dict]] = {}
  with _reading(root) as connection:
    if connection is None or not _has(connection, "closures"): return {}
    for row in _select(connection, f"""select file, line, issue, verdict, reason, author from closures
                           where verdict in ({", ".join("?" * len(KEEP_QUIET))}) order by id""", list(KEEP_QUIET)): out.setdefault(row["file"], []).append(row)
  return out
