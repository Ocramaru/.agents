"""Commands for your profile: where it is, making a new one, and switching to another."""

from pathlib import Path

from agentkit import git, install, profile
from agentkit.command import GROUPS, arg, command
from agentkit.cli.out import done, line, report

GROUPS["profile"] = "your private standards, kept apart from the public .agents"


@command("status", help="where your profile is, and whether it has work not pushed", group="profile", default=True)
def cmd_profile_status(args) -> int:
  where = profile.path()
  if where is None:
    return done("no profile: the starters in .agents are in use.", "  make, clone or choose one:  agent install --profile new|URL|DIR|none")

  origin = git.run(where, "remote", "get-url", "origin").stdout.strip()
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
