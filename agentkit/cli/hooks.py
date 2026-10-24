"""Commands for hooks: the post-commit review in a repo or everywhere, what the hooks have done, and the formatter guard."""

from pathlib import Path

from agentkit import config, git, guard, hooks, install
from agentkit.command import arg, command
from agentkit.cli.out import done, escape, fail, note, report, table

STYLE = {"ERROR": "bold red", "BLOCKED": "yellow", "sent": "green", "quiet": "dim", "none": "dim",
         "review": "cyan", "done": "green"}   # the Rich colour of each status in the hooks table


@command("hook", help="review commits: in this repo, or in every repo that has a .agents/")
@arg("action", choices=("install", "uninstall", "status"), help="what to do with the post-commit review hook")
@arg("--global", action="store_true", dest="everywhere",
     help="every repo on this machine, through core.hooksPath; only repos with a .agents/ are reviewed")
@arg("--agent", default="auto", help="which agent reviews this repo's commits (default: auto, routed by standards; --global always routes)")
@arg("--backend", default="", help="which backend this repo's reviews run on (default: the configured one, which --global always uses)")
@arg("--repo", default=".", help="the repo to act on (default: here)")
def cmd_hook(args) -> int:
  if args.everywhere:
    if args.action == "status":
      current = install.global_hooks_path()
      ours = current and install.ours(current)
      return done(f"{'on' if ours else 'off'}  core.hooksPath = {current or '(unset)'}", code=0 if ours else 1)
    return report(*(install.global_install if args.action == "install" else install.global_uninstall)())

  root = git.root(Path(args.repo).resolve())
  if root is None: return fail(f"{Path(args.repo).resolve()} is not a git repo", 2)

  if args.action == "install" and install.global_hooks_path():   # git reads hooksPath instead of the repo's hooks, so this would never run
    note("the global hook is on, so this repo is already reviewed if it has a .agents/; nothing to install here")
    return 0

  if args.action == "status":
    ours = install.repo_hook_ours(root)
    return done(f"{'installed' if ours else 'not installed'}  {install.repo_hook(root)}", code=0 if ours else 1)
  if args.action == "uninstall": return report(*install.repo_uninstall(root))
  code, lines = install.repo_install(root, args.agent, args.backend)
  return report(code, "\n".join(lines))


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

  return table(["time", "hook", "session", "status", "detail"], [[row[0][5:19].replace("T", " "), row[1], row[2], f"[{style}]{row[3]}[/{style}]" if (style := STYLE.get(row[3])) else row[3], escape(row[4])] for row in rows], title=f"Hooks{' · ' + args.session if args.session else ''}",
               note="--verbose for routine lines  ·  --all for every line", wide=("detail",))


@command("guard", help="name the whole-file rewriter a shell command would run, if any")
@arg("command", help="the shell command to check, quoted as one argument")
def cmd_guard(args) -> int:
  if not (found := guard.formatter(args.command, settings := config.section("guard", git.root(Path.cwd())))): return 0
  return done(f"{found}: {settings['advice']}" if settings["advice"] else found, code=2)   # 2 is the code the hook turns into a block
