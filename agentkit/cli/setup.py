"""Commands that set a machine up and keep it right: install, hooks, the profile, updating, reporting friction, and checking.

Author: Marco Cassar (@Ocramaru)
"""

import shlex
from pathlib import Path

from agentkit import doctor, guard, hooks, install, issue, profile, reviews, tree
from agentkit.command import GROUPS, arg, command
from agentkit.cli.out import done, escape, fail, line, note, report, table

HOOK_MARK = "# installed by `agent hook install`"
HOOK = f"""#!/usr/bin/env bash
{HOOK_MARK} -- review each commit into this repo's ledger.
exec "$HOME/.agents/hooks/post-commit.sh" {{agent}} {{backend}}
"""


@command("install", help="wire this repo into the agents on this machine")
@arg("targets", nargs="*", help="claude, codex, gemini, or any name (default: whichever exist)")
@arg("--all", action="store_true", help="create config directories that do not exist yet")
@arg("--profile", metavar="URL|DIR", help="your private profile: cloned to ~/.agents/profile, or used where it is")
def cmd_install(args) -> int:
  code, lines = install.run(args.targets, create=args.all, profile=args.profile)
  if code == 0 and not install.global_hooks_path():
    lines += ["", "Optional: review every commit in repos that have a .agents/", "  agent hook install --global"]
  if code == 0: lines += ["", "Done. Restart the agent to pick up the changes."]
  return done(*lines, code=code)


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
  if not args.all_: rows = rows[-args.tail:]

  if not rows:
    return fail(f"{'nothing worth reporting' if hooks.LOG.is_file() else 'no log yet'} in {hooks.LOG}{'' if args.verbose else ' (--verbose for the routine lines)'}")

  return table(["time", "hook", "session", "status", "detail"], [[row[0][5:19].replace("T", " "), row[1], row[2], f"[{style}]{row[3]}[/{style}]" if (style := hooks.STYLE.get(row[3])) else row[3], escape(row[4])] for row in rows], title=f"Hooks{' · ' + args.session if args.session else ''}",
               note="--verbose for routine lines  ·  --all for every line", wide=("detail",))


@command("guard", help="name the whole-file rewriter a shell command would run, if any")
@arg("command", help="the shell command to check, quoted as one argument")
def cmd_guard(args) -> int:
  if not (found := guard.formatter(args.command, settings := profile.section("guard", tree.git_root(Path.cwd())))): return 0
  return done(f"{found}: {settings['advice']}" if settings["advice"] else found, code=2)   # 2 is the code the hook turns into a block


@command("update", help="pull .agents and your profile")
def cmd_update(args) -> int:
  """Pull the hub and the profile, fast-forward only, so a pull that needs a merge fails instead of merging."""
  bad = 0
  for name, where in ((".agents", profile.HUB), ("profile", profile.path())):
    if where is None or not (where / ".git").exists():
      line(f"skip   {name}: {'not a git repo' if where else 'none set'}")
      continue

    pulled = profile.git(where, "pull", "--ff-only", "-q")
    bad += pulled.returncode != 0
    said = (pulled.stderr or pulled.stdout).strip().splitlines()
    line(f"{'ok' if pulled.returncode == 0 else 'FAIL':<6} {name}: {said[-1] if said else 'up to date' if pulled.returncode == 0 else 'no output'}  ({where})")
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
              *(f"  !  {drift}" for drift in profile.drift(where)))


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


@command("issue", help="report friction with the hub itself, from whatever repo you met it in")
@arg("title", nargs="?", help="one line: what was awkward, wrong or missing")
@arg("--body", default="", help="what you were doing and what you expected")
@arg("--list", action="store_true", dest="list_", help="what is already filed, and what has a reply")
@arg("--dry-run", action="store_true", dest="dry", help="print what would be filed and stop")
@arg("--context", action="store_true", help="also say which repo it was met in, and this machine's name")
def cmd_issue(args) -> int:
  repo = issue.slug()
  if not repo: return fail("no origin remote on the hub, so there is nowhere to file", 2)

  if args.list_:
    return done(*(issue.filed(repo) or ["nothing filed against the hub"]))
  if not args.title: return fail("say what was awkward, or pass --list to read what already is", 2)
  return report(*issue.file(args.title, args.body, Path.cwd(), repo, dry=args.dry, context=args.context))


@command("doctor", help="check this machine's install and the standards graph")
def cmd_doctor(args) -> int:
  results = doctor.checks()
  bad = sum(not ok for ok, _, _ in results)
  return done(*(f"  ok    {what}" if ok else f"  FAIL  {what}\n        -> {fix}" for ok, what, fix in results), "", f"{len(results) - bad}/{len(results)} ok" + (f", {bad} to fix" if bad else ""), code=1 if bad else 0)
