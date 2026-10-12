"""Commands for subagents: running one, replying to it, fanning a review out over files, and reading what any of them said.

Author: Marco Cassar (@Ocramaru)
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from agentkit import agents, backends, hooks, profile, review, reviews, tree
from agentkit.command import GROUPS, arg, command
from agentkit.cli import show
from agentkit.cli.out import done, dump, escape, fail, line, note, say, table, took
from agentkit.session import Session
from agentkit.standards import Library

GROUPS["sub"] = "subagents: run, reply, review, and their conversations"


def _repo(given: str | None) -> Path:
  """The repo a conversation belongs to: what was asked for, else where the command was run."""
  return Path(given).resolve() if given else Path.cwd()


def _turn(args, conversation: Session, agent: str, backend, root: Path, file: str, message, tier: str, run: str) -> int:
  """A conversation's new turn: kept in the ledger, the one store, then shown as a review result is."""
  findings = review.findings(message.data)
  if file:   # one file per conversation, so the file is known here and the model's name for it is not
    for finding in findings: finding["file"] = file
  reviews.write(reviews.record(conversation, agent, backend.name, root, file, message, findings, tier, run), root)

  outcome = {"file": file or "(several files)", "agent": agent, "task": conversation.task, "state": message.state,
             "kind": message.kind, "body": message.body, "findings": findings}
  if args.json: dump({**outcome, "data": message.data})
  else: show.result(outcome)
  return 1 if message.state == "failed" else 0


def _missing_model(args, backend, roles) -> int:
  """Fail before sending anything when the backend has no model for a role, then list what every backend has."""
  for role in roles:
    try: backend.model_for(role)
    except ValueError as error:
      fail(error)
      cmd_backends(args)
      return 2
  return 0


@command("run", help="start or continue a conversation with an agent", group="sub", variadic="paths")
@arg("agent", help="the agent to talk to, as `agent sub agents` lists them")
@arg("paths", nargs="*", help="files to send it")
@arg("--changed", action="store_true", help="include the working diff")
@arg("--backend", help="where to run it, as `agent sub backends` lists them (default: the configured one)")
@arg("--task", help="continue this conversation instead of starting one")
@arg("--tier", help="the model role, overriding the agent's own")
@arg("--json", action="store_true", help="the result as JSON, for an agent to read")
def cmd_run(args) -> int:
  definition = agents.definition(args.agent, agents.definitions())
  if missing := [path for path in args.paths if not Path(path).is_file()]: return fail(f"no such file: {', '.join(missing)}", 2)
  body = agents.prompt([(path, Path(path).read_text(encoding="utf-8")) for path in args.paths], changed=args.changed)
  if not body: return fail("nothing to check: pass --changed or some files", 2)

  root = tree.git_root(Path.cwd()) or Path.cwd()
  task = args.task or f"{args.agent}-{hashlib.sha1(body.encode()).hexdigest()[:8]}"
  conversation = reviews.conversation(reviews.latest(task, root)) or Session(task)

  backend, tier = backends.get(args.backend), args.tier or definition.get("model")
  if (code := _missing_model(args, backend, [tier])): return code
  # one file is about that file, so it is reviewed and rechecked as one; several, or a diff, are not
  return _turn(args, conversation, args.agent, backend, root, review.label(Path(args.paths[0]).resolve(), root) if len(args.paths) == 1 and not args.changed else "",
               conversation.send(args.agent, backend, body, instructions=agents.instructions(definition), tier=tier, effort=definition.get("effort") or None), tier, review.new_run())


@command("reply", help="answer a question, or tell a review you fixed what it found", group="sub")
@arg("task", help="the conversation's task id, as a run or `agent sub reviews` prints it")
@arg("text", help="what to say")
@arg("--backend", help="where to run it (default: where the conversation ran)")
@arg("--tier", help="the model role, overriding the one the conversation ran on")
@arg("--json", action="store_true", help="the result as JSON, for an agent to read")
@arg("--root", help="the repo the conversation belongs to (default: here)")
def cmd_reply(args) -> int:
  root = _repo(args.root)
  record = reviews.latest(args.task, root)
  conversation = reviews.conversation(record)
  if conversation is None or not conversation.messages:
    return fail(f"no conversation {args.task!r} in {reviews.path(root, create=False)}", 2)
  agent = next((turn.sender for turn in reversed(conversation.messages) if turn.sender != "caller"), None)
  if agent is None: return fail(f"conversation {args.task!r} has no agent to reply to", 2)

  backend, definition = backends.get(args.backend or record.get("backend")), agents.definition(agent, agents.definitions())
  # continue on the model the conversation started on; the default role belongs to a fresh run
  tier = args.tier or record.get("tier") or definition.get("model")
  if (code := _missing_model(args, backend, [tier])): return code
  return _turn(args, conversation, agent, backend, root, record.get("file") or "",
               conversation.answer(agent, backend, review.recheck(args.text, Path(record["root"]), record["file"]) if record.get("file") else args.text, tier=tier, effort=definition.get("effort") or None), tier, review.new_run())


@command("review", help="fan an agent out over a repo, one conversation per file",
         group="sub", variadic="paths")
@arg("agent", nargs="?", default=review.AUTO,
     help="a kind (logic, docs, prose), an agent, or `auto`; left out, a path means auto")
@arg("paths", nargs="*", help="files to review, or directories to search (default: .)")
@arg("--commit", metavar="REF", help="review what a commit touched, filtered to what the standards govern")
@arg("--glob", action="append", help="override which files (default: what the agent's standards govern)")
@arg("--exclude", action="append", help="repeatable; adds to the excludes from review.toml")
@arg("--no-config-excludes", action="store_true", help="ignore the excludes config sets")
@arg("--jobs", type=int, help="default 4, or jobs in review.toml")
@arg("--limit", type=int, help="cap files reviewed; reports what it dropped")
@arg("--dry-run", action="store_true", dest="dry", help="print the routing and stop")
@arg("--keep", action="store_true", help="leave the models loaded, for a second review straight after")
@arg("--jsonl", action="store_true", help="one JSON object per file as each finishes, for an agent to read")
@arg("--effort", choices=("low", "medium", "high"), help="how hard each review thinks: low is fast and shallow")
@arg("--variant", help="within a kind, which reviewer: `default` for the general one, or e.g. `learned` for refine.learned")
@arg("--fresh", action="store_true", help="ask about every file again, even one whose verdict still stands")
@arg("--recheck", action="store_true", help="only files with findings open or closed as fixed since, by their reviewer")
@arg("--backend", help="where to run it (default: the configured one)")
@arg("--tier", help="the model role, overriding each agent's own")
def cmd_review(args) -> int:
  # `review eval.py` means the agent was left out: an agent or kind name is never an existing path
  found = agents.definitions()
  kinds, kind = agents.kinds(found), agents.kind_of(found)
  if args.agent != review.AUTO and args.agent not in found and args.agent not in kinds and Path(args.agent).exists():
    args.paths, args.agent = [args.agent, *args.paths], review.AUTO

  if args.recheck and args.commit: return fail("--recheck reads the ledger and --commit reads a commit; use one", 2)
  if args.recheck or args.commit:
    root = tree.git_root(Path.cwd()) or Path.cwd()
    touched = profile.git(root, "diff-tree", "--no-commit-id", "--name-only", "-z", "-r", "--root", args.commit) if args.commit else None
    # NUL-separated: a whitespace split breaks a spaced path, and git quotes a non-ASCII one per line; a deleted file has nothing left to review
    if touched and touched.returncode: return fail(f"git could not read {args.commit}: {touched.stderr.strip()}", 2)
    files, roots = [path for name in touched.stdout.split("\0") if name and (path := root / name).is_file()] if touched else [], []
  else:
    given = [Path(path) for path in (args.paths or ["."])]
    missing = [path for path in given if not path.exists()]
    if missing: return fail(f"no such path: {', '.join(str(path) for path in missing)}", 2)
    files = sorted(path.resolve() for path in given if path.is_file())
    roots = [path.resolve() for path in given if path.is_dir()]
    root = roots[0] if roots else (files[0].parent if files else Path.cwd())
    root = tree.git_root(root) or root

  config = profile.section("review", root, add=("exclude",))   # excludes accumulate from every layer; anything else, the nearest wins
  exclude = [] if args.no_config_excludes else list(config["exclude"])
  exclude += args.exclude or []
  jobs = args.jobs or config["jobs"]
  limit = args.limit if args.limit is not None else config["limit"]

  # `auto` reads the config, a kind is every agent of that kind, any other name that agent
  names = [] if args.recheck else list(config.get("agents") or []) if args.agent == review.AUTO else kinds.get(args.agent) or [args.agent]
  if args.variant:
    try: names = [review.variant(args.agent, args.variant, kinds)]
    except ValueError as error:
      return fail(error, 2)
  if not names and not args.recheck:
    return fail("no agents to route to: set `agents` under [review] in config.toml", 2)

  # every route, not only discovery: a commit's file list and a named file arrive unfiltered
  dropped = {file: ignored for file in files if (ignored := review.skipped(file, root))}
  if dropped:
    note(f"skipping {len(dropped)} file{'s' if len(dropped) != 1 else ''} under {', '.join(sorted({name for ignored in dropped.values() for name in ignored}))}")
    files = [file for file in files if file not in dropped]

  if args.recheck and not args.paths and (here := _subfolder(root)):
    note(f"rechecking under {here} (run it from the repo root for all of it)")
    args.paths = [str(Path.cwd())]

  discovered = [path for folder in roots for path in review.discover(folder, exclude, config["max_bytes"])]
  libraries = {}
  if args.recheck:   # each reviewer with the files it has something open on, narrowed to an agent or kind and to paths
    under = [Path(path).resolve() for path in args.paths]
    plans = [(name, selected) for name, open_files in reviews.to_recheck(root).items() if args.agent in (review.AUTO, name, kind.get(name))
             if (selected := [root / file for file in open_files if not under or any((root / file).is_relative_to(folder) for folder in under)])]
  else:
    plans = review.plan(names, found, files, discovered, libraries, globs=args.glob, explicit=not args.commit)

  if not plans and args.recheck:
    note("nothing to recheck: no finding is open or claimed fixed")
    return 0
  if not plans:
    standards = Library()
    return fail(f"nothing under {root} is governed by {', '.join(names)} ({"; ".join(f"{name} reads {', '.join(review.globs_of(agents.definition(name, found), standards)) or 'what its standards govern'}" for name in names)})", 2)

  if limit:
    for index, (name, selected) in enumerate(plans):
      if len(selected) > limit:
        note(f"{name}: {len(selected)} files matched, reviewing the first {limit}")
        plans[index] = (name, selected[:limit])

  if not args.recheck:
    _unreviewed(sorted((set(files) | set(discovered)) - {path for _, selected in plans for path in selected}), root)

  if args.dry:
    for name, selected in plans:
      line(f"{kind.get(name, name)} review · {name} ({agents.definition(name, found).get("model")})")
      for file in selected: line(f"  {review.label(file, root)}")
    return 0

  if exclude and roots: note(f"excluding {', '.join(exclude)}")  # only discovery honours them
  backend = backends.get(args.backend or config.get("backend"))   # a repo may keep its reviews local
  if (code := _missing_model(args, backend, {args.tier or agents.definition(name, found).get("model") for name, _ in plans})): return code

  # what actually runs at once: plans go one after another, and the backend caps each of them
  at_once = min(jobs, backend.parallel, max(len(selected) for _, selected in plans))
  run = review.new_run()
  note(f"run {run} · " + "; ".join(f"{name} over {len(selected)} file{'' if len(selected) == 1 else 's'}" for name, selected in plans)
       + (f", {at_once} at a time" if at_once > 1 else ""))

  began = time.monotonic()
  return _report_review(args, root, _fan_out(plans, backend, root, jobs, args.tier, found, kind, libraries, keep=args.keep, run=run, mode="jsonl" if args.jsonl else "text", effort=args.effort, fresh=args.fresh),
                        run, time.monotonic() - began)


def _unreviewed(paths: list[Path], root: Path) -> None:
  """Name what no reviewer reads, by type and folder, so a run never looks clean for a file it skipped."""
  if not paths: return
  relative = [Path(review.label(path, root)) for path in paths]

  listed = lambda counts: ", ".join(f"{name} {count}" for name, count in counts.most_common(4)) + (", …" if len(counts) > 4 else "")
  note(f"not reviewed, no standard covers them: {len(paths)} file{'' if len(paths) == 1 else 's'} ({listed(Counter(path.suffix or path.name for path in relative))}) in {listed(Counter(f"{path.parent.as_posix()}/" if path.parent != Path(".") else "./" for path in relative))}")
  note(f"  to review one anyway, name a reviewer: agent sub review logic {os.path.relpath(paths[0], Path.cwd())}")


def _subfolder(root: Path) -> str | None:
  """The folder you stand in, relative to the repo, when it is below the repo's root: where a listing defaults to."""
  base, here = (tree.git_root(root) or root).resolve(), Path.cwd().resolve()
  return f"{here.relative_to(base).as_posix()}/" if here != base and here.is_relative_to(base) else None


@command("reviews", help="what reviews said: a run, the open findings, or the history", group="sub")
@arg("task", nargs="?", help="print one conversation in full; with --json, ready to feed an agent")
@arg("--last", action="store_true", help="the newest run, file by file, as it printed")
@arg("--run", metavar="ID", help="one run by the id it printed; a prefix is enough")
@arg("--open", action="store_true", dest="open_", help="findings still open, newest review per file")
@arg("--agent", help="only this agent, or this kind of review (logic, docs, prose, simplify)")
@arg("--path", help="only files under this folder, or matching this pattern: src/models/, '*.py'")
@arg("--failed", action="store_true", help="only reviews that could not run, with why")
@arg("--full", action="store_true", help="with --open, show each finding in full with its fix")
@arg("--sql", help="run a read-only query against the review tables")
@arg("--json", action="store_true", help="print every record")
@arg("--all", action="store_true", dest="whole", help="the whole repo, not only the folder you are in")
@arg("--tail", type=int, default=20, help="how many to show, as `agent hooks` spells it")
@arg("--root", help="the repo to read (default: here)")
def cmd_reviews(args) -> int:
  root = _repo(args.root)
  if args.sql: return dump(reviews.query(root, args.sql), default=str)

  if args.task:
    record = reviews.latest(args.task, root)
    if record is None: return fail(f"no conversation {args.task!r} in {reviews.path(root, create=False)}", 2)
    return dump(record) if args.json else done(reviews.conversation(record).transcript())

  if not args.path and not args.whole and not args.root and (here := _subfolder(root)):
    note(f"under {here} (--all for the whole repo)")
    args.path = here

  run = reviews.last_run(root) if args.last else args.run
  if (args.last or args.run) and not run: return fail("no run recorded yet: runs are tagged from this version on")
  last = lambda rows: rows[-args.tail:] if args.tail > 0 else []   # [-0:] is everything
  keep = lambda rows: reviews.filtered(rows, root, agent=args.agent, path=args.path, failed=args.failed, run=run)
  if args.open_: return show.findings(keep(reviews.open_findings(root)), full=args.full)

  data = keep(reviews.conversations(root))
  if args.json: return dump(data)
  if not data: return fail(f"nothing matches in {reviews.path(root, create=False)}")

  if run or args.failed:   # what each said, the way a run prints it as it lands
    for record in data if run else last(data): show.result(record)
    return 0

  when = lambda record: time.strftime("%Y-%m-%d %H:%M", time.localtime(record.get("at", 0)))
  return done(*(f"{when(record)}  {record.get('run') or '-':<14} {record.get('state', '?'):<14} {len(record.get('findings', [])):>3}  "
                f"{record.get('file', '?')}  {record.get('agent', '')}" for record in last(data)))


@command("close", help="close an open finding: fixed, wrong, or not worth fixing", group="sub")
@arg("targets", nargs="+", help="ids, files or file:line, as `agent sub reviews --open` shows them")
@arg("--as", dest="verdict", choices=reviews.VERDICTS, required=True, help="why it is closed")
@arg("--reason", default="", help="why; required for wrong and wontfix, so the reviewer can read it")
@arg("--root", help="the repo it belongs to (default: here)")
def cmd_close(args) -> int:
  if args.verdict in reviews.KEEP_QUIET and not args.reason.strip():
    return fail(f"--as {args.verdict} needs a --reason: the next review reads it so it does not raise this again", 2)

  root = _repo(args.root)
  base = tree.git_root(root) or root

  missed = []
  for target in args.targets:
    head, _, tail = target.rpartition(":")
    # a line as reviewers write it (12, 12-14, "86, 90"): read as its first number, so a range closes the findings at its start
    file, at = (head, reviews.first_line(tail)) if head and re.match(r"\s*\d", tail) else (target, 0)
    if Path(file).exists():   # accept a path as typed from wherever you stand, not only repo-relative
      file = review.label(Path(file).resolve(), base)

    closed = reviews.close(root, file, at, args.verdict, args.reason)
    if not closed: missed.append(target)
    for finding in closed:
      line(f"closed {reviews.short_id(finding['id'])} {finding['file']}:{reviews.first_line(finding['line'])} as {args.verdict}"
            f"  {' '.join(finding['issue'].split())[:70]}")
  return fail(f"nothing open at {', '.join(missed)}; `agent sub reviews --open` lists what is") if missed else 0


@command("agents", help="the kinds of review there are, and what each reads", group="sub", default=True)
def cmd_agents(args) -> int:
  backend, found, standards, rows = backends.get(None), agents.definitions(), Library(), []
  for kind, names in sorted(agents.kinds(found).items()):
    for name in names:
      definition = found[name]
      role = definition.get("model")
      rows.append([escape(kind), escape(name), f"{escape(backend.spec.get("models", {}).get(role, "none").removeprefix("claude-"))}\n[dim]{escape(role)}[/dim]", escape(", ".join(review.globs_of(definition, standards)) or "anything named"), escape((definition.get("description") or "").split(". ", 1)[-1])])   # the model that runs, not only its role

  return table(["kind", "agent", "model", "reads", "looks for"], rows,
               title=f"Review types on {backend.name}",
               note="each sees one file and nothing else, has no tools, and returns {line, issue, fix}\n"
                    "agent sub review <kind | agent | auto> <files>   ·   --backend to run elsewhere",
               wide=("reads", "looks for"))


@command("backends", help="list configured backends", group="sub")
def cmd_backends(args) -> int:
  known, default = backends.load_backends()
  return table(["backend", "kind", "context", "models"],
               [[f"{escape(name)}{' (default)' if name == default else ''}", backend.kind, "resumes" if backend.resumable else "replays",
                 escape(", ".join(f"{role} {model}" for role, model in sorted(backend.spec.get("models", {}).items())))]
                for name, backend in sorted(known.items())], wide=("models",))


def _fan_out(plans, backend, root: Path, jobs: int, want_tier: str | None, found: dict, kind: dict[str, str], libraries: dict, keep: bool = False,
             run: str | None = None, mode: str = "text", effort: str | None = None, fresh: bool = False) -> list:
  """Run each plan in turn, the backend capping how many of its files run at once.

  Models are released in a `finally`, so an interrupted review does not leave the weights resident."""
  results, used = [], []
  total, finished, lock = sum(len(selected) for _, selected in plans), [0], threading.Lock()
  out = sys.stdout if mode == "text" else sys.stderr     # --jsonl keeps stdout for data

  def started(relative): say(f"  [dim]… {escape(relative)}[/dim]", sys.stderr)   # out keeps each line whole

  def tick(outcome):
    with lock:   # a result is several lines, printed together with its count
      finished[0] += 1
      if mode == "jsonl": line(json.dumps(outcome))
      show.result(outcome, f"[{finished[0]}/{total}] ", out)

  try:
    for name, selected in plans:
      definition = agents.definition(name, found)
      tier = want_tier or definition.get("model")
      used.append(tier)

      # print what is about to be slow before it starts, so a long silence does not look like a hang
      note(f"  {kind.get(name, name)} review ({name}) on {backend.name}/{backend.model_for(tier)}, "
           f"started {time.strftime('%H:%M:%S')}, up to {backend.timeout}s a file")
      results += review.run(name, backend, selected, root, definition, libraries, tier=tier, jobs=jobs, on_start=started,
                            on_done=tick, run=run, effort=effort, fresh=fresh)
    return results
  finally:
    if not keep:   # the box is shared with whatever else is running on it
      freed = [tier for tier in dict.fromkeys(used) if backend.release(tier)]
      if freed: note(f"released {', '.join(backend.model_for(tier) for tier in freed)}")


def _report_review(args, root: Path, results: list, run: str, seconds: float) -> int:
  # one bucket each: subtracting overlapping counts could count a result twice or go negative
  by_bucket = {}
  for outcome in results: by_bucket.setdefault(show.outcome(outcome), []).append(outcome)

  failed, finding_count = by_bucket.get("failed", []), sum(len(outcome["findings"]) for outcome in by_bucket.get("found", []))

  say(f"\n[bold]{len(results)} file{'s' if len(results) != 1 else ''} in {took(seconds)}:[/bold] "
            + ", ".join([f"{len(by_bucket[bucket])} {phrase}" for bucket, phrase in {"clean": "clean", "found": f"with {finding_count} finding{'s' if finding_count != 1 else ''}", "asked": "asked", "failed": "failed", "empty": "empty", "unchanged": "unchanged, not asked again (--fresh to)"}.items() if by_bucket.get(bucket)]), sys.stderr)
  say(f"[dim]again: agent sub reviews --run {run}   ·   still open: agent sub reviews --open[/dim]", sys.stderr)

  if os.environ.get("AGENTS_HOOK"):   # started by a git hook that has already returned, so the outcome goes to the hook log
    hooks.log(os.environ["AGENTS_HOOK"], "git",
                f"done   {root.name}: {finding_count} findings in {len(results)} reviews"
                f"{f', {len(failed)} failed' if failed else ''}  (agent sub reviews --run {run})")
  return 1 if failed else 0   # a review that could not run is not a clean one; a script has to see it
