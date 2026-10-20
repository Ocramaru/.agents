"""Commands that set a machine up and keep it right: install, hooks, the profile, updating, reporting friction, describing and checking.

Author: Marco Cassar (@Ocramaru)
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from agentkit import backends, doctor, guard, hooks, install, issue, profile, reviews, status, tree, version
from agentkit.command import GROUPS, arg, command
from agentkit.cli.out import done, escape, fail, line, note, report, table

HOOK_MARK = "# installed by `agent hook install`"
HOOK = f"""#!/usr/bin/env bash
{HOOK_MARK} -- review each commit into this repo's ledger.
exec "$HOME/.agents/hooks/post-commit.sh" {{agent}} {{backend}}
"""


PROFILE_QUESTION = """No profile on this machine. A profile is your own private repo of standards and settings, layered over the starters.
  new   make one at {default}
  URL   clone yours, made on another machine
  DIR   use a directory where it is
  none  use the starters, and stop asking"""


def ask(question: str) -> str:
  """One line typed at the terminal, stripped; empty when there is nothing to read."""
  try: return input(question).strip()
  except EOFError: return ""


def pick() -> str:
  """Ask which backend this machine has, showing each with whether it is here or how to install it, and record the answer; `""` when none is chosen."""
  known = backends.load_backends()[0]
  found = {name: backend.here() for name, backend in known.items()}
  present = [name for name, (here, _) in found.items() if here]
  done("", "Reviews run on a model. Which of these does this machine have?", *(f"  {name:<8} {known[name].spec.get('label', name):<22} {said}" for name, (_, said) in found.items()))
  answer = ask(f"backend [{present[0] if present else 'none for now'}]: ") or (present[0] if present else "")
  if answer not in known:
    if answer: line(f"  skip  there is no backend called {answer}; `agent install --backend <name>` sets one later")
    return ""
  line(f"  set   default = {answer} in {install.home(backends.choose(answer))}")
  return answer


def settle(named: str | None) -> int:
  """0 when a review has a backend: one named, the default, or one chosen now at a terminal; otherwise say how to set one and return 2."""
  if named or backends.load_backends()[1]: return 0
  if sys.stdin.isatty() and ask("No default backend is set, so a review has nowhere to run. Set one now? [Y/n] ").lower() in ("", "y", "yes") and pick(): return 0
  return fail(backends.unset(), 2)


@command("install", help="wire .agents into the agents on this machine")
@arg("targets", nargs="*", help="claude, codex, gemini, or any name (default: whichever exist)")
@arg("--all", action="store_true", help="create config directories that do not exist yet")
@arg("--profile", metavar="new|URL|DIR|none", help="your private profile: make one, clone yours, use a directory, or none (default: ask, given a terminal)")
@arg("--backend", metavar="NAME", help="what reviews run on, as `agent sub backends` lists them (default: ask, given a terminal, when none is set)")
def cmd_install(args) -> int:
  if args.backend and args.backend not in (known := backends.load_backends()[0]): return fail(f"there is no backend called {args.backend}; known: {', '.join(known)}", 2)
  code, kept = install.keep(args.profile)
  if code: return fail(kept)
  if kept:   # the tool does the install, so the hooks copied are the ones it will keep
    line(f"keep  agentkit as a uv tool: {kept}")
    os.execve(kept, [kept, *sys.argv[1:]], os.environ | {"PATH": os.pathsep.join(entry for entry in os.environ.get("PATH", "").split(os.pathsep) if Path(entry).resolve() != (Path(sys.prefix) / "bin").resolve())})   # without uvx's own environment, which leads PATH

  answer = args.profile
  if answer is None and profile.path() is None and profile.chosen() is None and sys.stdin.isatty() and issue.login():   # once, as every answer is recorded; a profile wants a private GitHub repo, so the question waits for gh
    line(PROFILE_QUESTION.format(default=install.home(profile.DEFAULT)))
    answer = ask("profile [new]: ") or "new"

  code, lines = install.run(args.targets, create=args.all, profile=answer)
  done(*lines)
  if code: return code

  if answer == "new" and not profile.git(profile.DEFAULT, "remote").stdout.strip():   # a profile reaches other machines only once pushed
    login = issue.login()
    if login and sys.stdin.isatty() and ask(f"\nMake {login}/.agents.profile on GitHub, private, and push your profile there? [y/N] ").lower() in ("y", "yes"):   # it publishes, so it asks
      made = issue.gh("repo", "create", f"{login}/.agents.profile", "--private", "--source", str(profile.DEFAULT), "--remote", "origin", "--push")
      line(f"  made  {login}/.agents.profile, private, and pushed" if made.returncode == 0 else f"  FAIL  {(made.stderr.strip().splitlines() or ['gh said nothing'])[-1]}")
    if not profile.git(profile.DEFAULT, "remote").stdout.strip():
      done("", "Push your profile somewhere private, so your other machines get it:", f"  git -C {profile.DEFAULT} remote add origin git@github.com:{login or '<you>'}/.agents.profile.git", f"  git -C {profile.DEFAULT} push -u origin main")

  if args.backend: done("", "backend", f"  set   default = {args.backend} in {install.home(backends.choose(args.backend))}")
  elif not backends.load_backends()[1] and sys.stdin.isatty(): pick()

  return done(*(["", "No profile chosen: `agent install --profile new|URL|DIR|none`, or run it at a terminal with gh logged in to be asked."] if profile.path() is None and profile.chosen() is None else []),
              *(["", f"No backend: {backends.unset().partition(': ')[2]}."] if not backends.load_backends()[1] else []),
              *(["", "Optional: review every commit in repos that have a .agents/", "  agent hook install --global"] if not install.global_hooks_path() else []),
              "", "Done. Restart the agent to pick up the changes.")


@command("hook", help="review commits: in this repo, or in every repo that has a .agents/")
@arg("action", choices=("install", "uninstall", "status"), help="what to do with the post-commit review hook")
@arg("--global", action="store_true", dest="everywhere",
     help="every repo on this machine, through core.hooksPath; only repos with a .agents/ are reviewed")
@arg("--agent", default="auto", help="which agent reviews (default: auto, routed by standards)")
@arg("--backend", default="", help="which backend it runs on (default: the configured one)")
@arg("--repo", default=".", help="the repo to act on (default: here)")
def cmd_hook(args) -> int:
  if args.everywhere:
    if args.action == "status":
      current = install.global_hooks_path()
      ours = current and install.ours(current)
      return done(f"{'on' if ours else 'off'}  core.hooksPath = {current or '(unset)'}", code=0 if ours else 1)
    return report(*(install.global_install if args.action == "install" else install.global_uninstall)())

  root = tree.git_root(Path(args.repo).resolve())
  if root is None: return fail(f"{Path(args.repo).resolve()} is not a git repo", 2)
  destination = root / ".git" / "hooks" / "post-commit"

  if args.action == "install" and install.global_hooks_path():   # git reads hooksPath instead of .git/hooks, so this would never run
    note("the global hook is on, so this repo is already reviewed if it has a .agents/; nothing to install here")
    return 0

  ours = destination.is_file() and HOOK_MARK in destination.read_text(encoding="utf-8", errors="replace")

  if args.action == "status":
    return done(f"{'installed' if ours else 'not installed'}  {destination}", code=0 if ours else 1)

  if args.action == "uninstall":
    if not destination.exists(): return fail(f"nothing installed at {destination}")
    if not ours: return fail(f"not ours, leaving it alone: {destination}")
    destination.unlink()
    return done(f"removed {destination}")

  # never overwrite a hook, nor an earlier .bak of one
  moved = f"moved the hook already there aside to {destination.rename(install.backup(destination)).name}" if destination.exists() and not ours else None
  destination.parent.mkdir(parents=True, exist_ok=True)
  # quoted: these land in a bash script run on every commit, where a space or a ; would be code
  destination.write_text(HOOK.format(agent=shlex.quote(args.agent), backend=shlex.quote(args.backend)), encoding="utf-8")
  destination.chmod(0o755)
  return done(moved, f"installed {destination}", f"  {args.agent} reviews each commit into {reviews.path(root, create=False)}")


@command("hooks", help="what the hooks have done, newest last")
@arg("--tail", type=int, default=20, help="how many lines to show")
@arg("--session", default="", help="only this session, by id or its first characters")
@arg("--all", action="store_true", dest="all_", help="every line, not just the tail")
@arg("--verbose", action="store_true", help="include the routine lines: every Bash command allowed")
@arg("--hook", default="", help="only one hook: inject for edits, post-commit for commits, no-reformat")
def cmd_hooks(args) -> int:
  rows = hooks.entries(args.session, verbose=args.verbose, hook=args.hook)
  if not args.all_: rows = rows[-args.tail:] if args.tail > 0 else []   # [-0:] is everything

  if not rows:
    return fail(f"{'nothing worth reporting' if hooks.LOG.is_file() else 'no log yet'} in {hooks.LOG}{'' if args.verbose else ' (--verbose for the routine lines)'}")

  return table(["time", "hook", "session", "status", "detail"], [[row[0][5:19].replace("T", " "), row[1], row[2], f"[{style}]{row[3]}[/{style}]" if (style := hooks.STYLE.get(row[3])) else row[3], escape(row[4])] for row in rows], title=f"Hooks{' · ' + args.session if args.session else ''}",
               note="--verbose for routine lines  ·  --all for every line", wide=("detail",))


@command("guard", help="name the whole-file rewriter a shell command would run, if any")
@arg("command", help="the shell command to check, quoted as one argument")
def cmd_guard(args) -> int:
  if not (found := guard.formatter(args.command, settings := profile.section("guard", tree.git_root(Path.cwd())))): return 0
  return done(f"{found}: {settings['advice']}" if settings["advice"] else found, code=2)   # 2 is the code the hook turns into a block


@command("update", help="upgrade .agents and pull your profile")
def cmd_update(args) -> int:
  """Upgrade the hub, through uv for an install and by pulling a clone, then pull the profile, saying what each moved.

  Pulls are fast-forward only, so one that needs a merge fails instead of merging.
  """
  bad, was = 0, version()
  if profile.INSTALLED:   # uv replaces the package, and the new one copies its own hooks into ~/.agents
    try: upgraded = subprocess.run(["uv", "tool", "upgrade", "agentkit"], capture_output=True, check=False, text=True)
    except FileNotFoundError: upgraded = subprocess.CompletedProcess(["uv"], 127, "", "uv is not on PATH")
    bad += upgraded.returncode != 0
    if upgraded.returncode: line(f"FAIL   .agents: {((upgraded.stderr or upgraded.stdout).strip().splitlines() or ['uv said nothing'])[-1]}")
    elif (now := subprocess.run([str(install.CLI), "--version"], capture_output=True, check=False, text=True).stdout.strip().removeprefix("agentkit ")) == was: line(f"ok     .agents: already current at {now}")   # the new code says its version
    else:
      copied = subprocess.run([str(install.CLI), "install"], capture_output=True, check=False, stdin=subprocess.DEVNULL, text=True)   # no terminal, so it never asks
      bad += copied.returncode != 0
      done(f"ok     .agents: upgraded {was} -> {now}" if copied.returncode == 0 else f"FAIL   .agents: upgraded {was} -> {now}, but its install did not finish; run `agent install`", *(f"       {said.strip()}" for said in copied.stdout.splitlines() if (said.split() or [""])[0] in ("copy", "wrote", "link", "point", "saved", "cannot")))

  for name, where in ((".agents", None if profile.INSTALLED else profile.SHIPPED), ("profile", profile.path())):
    if name == ".agents" and where is None: continue
    if where is None or not (where / ".git").exists():
      line(f"skip   {name}: {'not a git repo' if where else 'none set'}")
      continue

    before = profile.git(where, "rev-parse", "HEAD").stdout.strip()
    pulled = profile.git(where, "pull", "--ff-only", "-q")
    bad += pulled.returncode != 0
    if pulled.returncode: line(f"FAIL   {name}: {((pulled.stderr or pulled.stdout).strip().splitlines() or ['git said nothing'])[-1]}  ({where})")
    else:
      count = int(profile.git(where, "rev-list", "--count", f"{before}..HEAD" if before else "HEAD").stdout.strip() or 0)
      line(f"ok     {name}: {f'pulled {count} commit' + ('s' if count != 1 else '') if count else 'already current'}  ({where})")

  if not profile.INSTALLED and (now := version()) != was: line(f"       agentkit {was} -> {now}")
  return 1 if bad else 0


GROUPS["profile"] = "your private standards, kept apart from the public .agents"


@command("status", help="where your profile is, and whether it has work not pushed", group="profile", default=True)
def cmd_profile_status(args) -> int:
  where = profile.path()
  if where is None:
    return done("no profile: the starters in .agents are in use.", "  make one:  agent profile init ~/.agents/profile",
                "  or clone:  agent install --profile <url>")

  origin = profile.git(where, "remote", "get-url", "origin").stdout.strip()
  return done(f"profile  {where}" + (f"  ({origin})" if origin else ""),
              *(f"  {part:<14} {len(list(path.glob('*.md')))} file(s)" if path.is_dir() else f"  {part}" for part, path in [(part, where / part) for part in ("standards", "agents", "config.toml", "AGENTS.md")] if path.exists()),
              *([] if origin else [f"  !  no remote, so no other machine gets it: git -C {where} remote add origin <a private repo>, then push"]),
              *(f"  !  {drift}" for drift in profile.drift(where) if origin or not drift.startswith("no upstream")))   # with no remote at all, that says it


@command("init", help="make a new, empty profile to put your own standards in", group="profile")
@arg("spec", nargs="?", metavar="dir", default=str(profile.DEFAULT), help="where to make it (default: ~/.agents/profile)")
@arg("--use", action="store_true", help="also make it this machine's profile")
def cmd_profile_init(args) -> int:
  made = profile.init(Path(args.spec))
  line(f"made {args.spec}: {', '.join(made)}" if made else f"{args.spec} is already a profile; nothing made")
  if args.use and (code := cmd_profile_use(args)): return code
  return done("next: add standards, then push it somewhere private and `agent install --profile <url>` elsewhere")


@command("use", help="make a profile this machine's: a directory, or a URL to clone", group="profile")
@arg("spec", help="a directory or a git URL")
def cmd_profile_use(args) -> int:
  """Switch this machine's profile, and every agent's pointer to its AGENTS.md with it."""
  was = profile.file("AGENTS.md")
  code, said = profile.adopt(args.spec)
  return report(code, "\n".join([said, *install.repoint(was)]) if code == 0 else said)


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
  return done(*(f"{part:<12}  {state}" for part, state in status.rows()))


@command("doctor", help="check this machine's install and the standards graph")
def cmd_doctor(args) -> int:
  results = doctor.checks()
  bad = sum(not ok for ok, _, _ in results)
  return done(*(f"  ok    {what}" if ok else f"  FAIL  {what}\n        -> {fix}" for ok, what, fix in results), "", f"{len(results) - bad}/{len(results)} ok" + (f", {bad} to fix" if bad else ""), code=1 if bad else 0)
