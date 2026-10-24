"""Commands that set a machine up and keep it right: `install`, `update`, `issue` (report friction with the hub), `status` and `doctor`."""

import re
import sys
from pathlib import Path

from agentkit import backends, doctor, gh, git, hub, install, issue, profile, status
from agentkit.command import arg, command
from agentkit.cli.out import done, escape, fail, line, say
from agentkit.cli.utilities import CliHelpers


def show(changes: bool, *lines: str, failed: bool = False) -> int:
  """Print `lines`; under `changes` only those that changed something or failed, or every one when the step `failed`."""
  return done(*(text for text in lines if failed or not changes or text.strip().partition(" ")[0] in (*install.CHANGED, "FAIL")))


@command("install", help="wire .agents into the agents on this machine")
@arg("targets", nargs="*", help="claude, codex, gemini, or any name (default: whichever exist)")
@arg("--all", action="store_true", help="create config directories that do not exist yet")
@arg("--profile", metavar="new|URL|DIR|none", help="your private profile: make one, clone yours, use a directory, or none (default: ask, given a terminal)")
@arg("--backend", metavar="NAME", help="what reviews run on, as `agent sub backends` lists them (default: ask, given a terminal, when none is set)")
@arg("--changes", action="store_true", help="print only the lines that changed something, and any failure")
def cmd_install(args) -> int:
  if args.backend and args.backend not in (known := backends.load_backends()[0]): return fail(f"there is no backend called {args.backend}; known: {', '.join(known)}", 2)
  code, kept = install.keep(args.profile)
  if code: return fail(kept)
  if kept:   # the tool does the install, so the hooks copied are the ones it will keep
    line(f"keep  agentkit as a uv tool: {kept}")
    install.hand_over(kept)

  answer = args.profile
  if answer is None and profile.unasked() and CliHelpers.at_terminal() and gh.login():   # once, as every answer is recorded; a profile wants a private GitHub repo, so the question waits for gh
    answer = CliHelpers.ask("No profile on this machine. A profile is your own private repo of standards and settings, layered over the starters.", {"new": f"make one at {install.home(profile.DEFAULT)}", "URL": "clone yours, made on another machine", "DIR": "use a directory where it is", "none": "use the starters, and stop asking"}, default="new", free=True)

  code, lines = install.run(args.targets, create=args.all, profile=answer)
  show(args.changes, *lines, failed=code != 0)
  if code: return code

  if answer == "new" and not profile.published():   # a profile reaches other machines only once pushed
    login = gh.login()
    if login and CliHelpers.ask(f"Make {login}/.agents.profile on GitHub, private, and push your profile there?", default=False): show(args.changes, *profile.publish(login))   # it publishes, so it asks
    if not profile.published():
      show(args.changes, "", "Push your profile somewhere private, so your other machines get it:", f"  git -C {profile.DEFAULT} remote add origin git@github.com:{login or '<you>'}/.agents.profile.git", f"  git -C {profile.DEFAULT} push -u origin main")

  if args.backend: show(args.changes, "", "backend", f"  set   default = {args.backend} in {install.home(backends.choose(args.backend))}")
  default = args.backend or backends.load_backends()[1]   # read once, so the closing hint reflects what was just chosen
  if not default: default = CliHelpers.ask_backend()

  return show(args.changes,
              *(["", "No profile chosen: `agent install --profile new|URL|DIR|none`, or run it at a terminal with gh logged in to be asked."] if profile.unasked() else []),
              *(["", f"No backend: {backends.unset()}."] if not default else []),
              *(["", "Optional: review every commit in repos that have a .agents/", "  agent hook install --global"] if not install.global_hooks_path() else []),
              "", "Done. Restart the agent to pick up the changes.")


@command("update", help="upgrade .agents and pull your profile")
def cmd_update(args) -> int:
  """Pull the latest hub, through uv for an install and git for a clone, and the latest profile, saying what each moved.
  A pull that would have to merge stops and says so instead."""
  bad, was = 0, hub.version()
  if hub.INSTALLED:   # uv replaces the package, and the new one copies its own hooks into ~/.agents
    code, lines = install.upgrade()
    bad += code
    done(*lines)

  for name, where in ((".agents", None if hub.INSTALLED else hub.BUNDLED), ("profile", profile.path())):
    if name == ".agents" and where is None: continue
    if where is None or not (where / ".git").exists():
      line(f"skip   {name}: {'not a git repo' if where else 'none set'}")
      continue

    pulled, said = git.pull(where)
    bad += not pulled
    line(f"ok     {name}: {said}  ({where})" if pulled else f"FAIL   {name}: {said}  ({where})")

  if not hub.INSTALLED and (now := hub.version()) != was: line(f"       agentkit {was} -> {now}")
  return 1 if bad else 0


@command("issue", help="draft a report of friction with the hub, from whatever repo you met it in, for you to submit")
@arg("title", nargs="?", help="one line: what was awkward, wrong or missing")
@arg("--body", default="", help="what you were doing and what you expected")
@arg("--list", action="store_true", dest="list_", help="what is already filed, and what has a reply")
@arg("--dry-run", action="store_true", dest="dry", help="print the draft and its link and open nothing")
@arg("--context", action="store_true", help="also say which repo it was met in, and this machine's name")
def cmd_issue(args) -> int:
  repo = issue.slug()
  if not repo: return fail("no origin remote on the hub, so there is nowhere to file", 2)

  if args.list_:
    return done(*(issue.filed(repo) or ["nothing filed against the hub"]))
  if not args.title: return fail("say what was awkward, or pass --list to read what already is", 2)
  return done(issue.draft(args.title, args.body, Path.cwd(), repo, dry=args.dry, context=args.context))


@command("status", help="what this machine has: the install, profile, backend, standards, notes, findings and hooks")
def cmd_status(args) -> int:
  """Each part and what it is, at a terminal with the part named once and coloured, its detail dimmed and its level in yellow or red; piped, plain with the part on every line, for grep."""
  rows = status.rows()
  width = max(len(part) for part, _, _ in rows)
  for index, (part, text, level) in enumerate(rows):
    label = "" if index and rows[index - 1][0] == part and sys.stdout.isatty() else part
    detail = re.sub(r"\(([^()]*)\)", r"[dim](\1)[/dim]", escape(text))   # what is in parentheses says more, so it reads quieter
    say(f"[bold cyan]{label:<{width}}[/bold cyan]  " + (f"[{colour}]{detail}[/{colour}]" if (colour := {"warn": "yellow", "fail": "red"}.get(level)) else detail))
  return 0


@command("doctor", help="check this machine's install and the standards graph")
def cmd_doctor(args) -> int:
  results = doctor.checks()
  bad = sum(not ok for ok, _, _ in results)
  return done(*(f"  ok    {what}" if ok else f"  FAIL  {what}\n        -> {fix}" for ok, what, fix in results), "", f"{len(results) - bad}/{len(results)} ok" + (f", {bad} to fix" if bad else ""), code=1 if bad else 0)
