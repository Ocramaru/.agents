"""Commands for your profile: where it is, making a new one, switching to another, and reviewing it whole."""

import time
from pathlib import Path

from agentkit import agents, backends, git, hub, install, profile, review, standards, words
from agentkit.command import GROUPS, arg, command
from agentkit.cli import show
from agentkit.cli.out import done, fail, line, note, report
from agentkit.cli.utilities import CliHelpers

GROUPS["profile"] = "your private standards, kept apart from the public .agents"


@command("status", help="where your profile is, and whether it has work not pushed", group="profile", default=True)
def cmd_profile_status(args) -> int:
  where = profile.path()
  if where is None:
    return done("no profile: the starters in .agents are in use.", words.indented("make, clone or choose one:  agent install --profile new|URL|DIR|none"))

  origin = git.run(where, "remote", "get-url", "origin").stdout.strip()
  parts = [(part, where / part) for part in ("standards", "agents", "config.toml", "AGENTS.md") if (where / part).exists()]
  width = max((len(part) for part, _ in parts), default=0)
  return done(f"profile  {where}" + (f"  ({origin})" if origin else ""),
              *(words.indented(f"{part:<{width}}  {words.count(len(standards.files(path)), 'file')}" if path.is_dir() else part) for part, path in parts),
              *([] if origin else [words.indented(f"!  no remote, so no other machine gets it: git -C {where} remote add origin <a private repo>, then push")]),
              *(words.indented(f"!  {drift}") for drift in profile.drift(where) if origin or not drift.startswith("no upstream")))   # with no remote at all, that says it


@command("init", help="make a new, empty profile to put your own standards in", group="profile")
@arg("spec", nargs="?", metavar="dir", default=str(profile.DEFAULT), help="where to make it (default: ~/.agents/profile)")
@arg("--use", action="store_true", help="also make it this machine's profile")
def cmd_profile_init(args) -> int:
  made = profile.init(Path(args.spec))
  line(f"made {args.spec}: {', '.join(made)}" if made else f"{args.spec} is already a profile; nothing made")
  if args.use and (code := cmd_profile_use(args)): return code
  return done("next: add standards, then push it somewhere private and `agent install --profile <url>` elsewhere")


@command("review", help="one reviewer over the whole profile, the starters and repo overrides beside it, and the memory waiting to move in", group="profile")
@arg("--backend", help="where to run it, as `agent sub backends` lists them (default: the configured one)")
@arg("--effort", choices=("low", "medium", "high"), help="how hard the review thinks")
@arg("--fresh", action="store_true", help="ask again even when nothing it reads has changed")
@arg("--dry-run", action="store_true", dest="dry", help="list what it would read, and stop")
def cmd_profile_review(args) -> int:
  """Findings go into the profile's reviews, or the hub's with no profile, where `agent sub reviews` and `agent sub close` read them."""
  files, root = profile.subject(), profile.path() or hub.HOME
  if not files: return fail("nothing to review: no profile, no repo overrides and no memory waiting", 2)
  if args.dry: return done(*(f"{install.home(path)}\n{words.indented(what)}" for path, what in files.items()), f"\n{len(files)} files, {sum(path.stat().st_size for path in files) // 1000}k, into the reviews of {install.home(root)}")

  if (code := CliHelpers.ensure_backend(args.backend)): return code
  backend, definition = backends.get(args.backend), agents.definition("profile-review", agents.definitions())
  try: model = backend.model_for(definition.get("model"))
  except ValueError as error: return fail(error, 2)
  note(f"profile review on {backend.name}/{model}: {len(files)} files in one conversation, started {time.strftime('%H:%M:%S')}, up to {backend.timeout}s")

  result = review.whole("profile-review", backend, files, definition, root, "review-profile-review", effort=args.effort, run=review.new_run(), fresh=args.fresh)
  show.result(result | {"again": "agent profile review"})
  if result["findings"]: note(f"open: agent sub reviews --open --root {root}   ·   close: agent sub close <id> --as fixed|wrong|wontfix --reason '…' --root {root}")
  return 1 if result["state"] == "failed" else 0


@command("use", help="make a profile this machine's: a directory, or a URL to clone", group="profile")
@arg("spec", help="a directory or a git URL")
def cmd_profile_use(args) -> int:
  """Switch this machine's profile, and every agent's pointer to its AGENTS.md with it."""
  was = profile.file("AGENTS.md")
  code, said = profile.adopt(args.spec)
  return report(code, "\n".join([said, *install.repoint(was)]) if code == 0 else said)
