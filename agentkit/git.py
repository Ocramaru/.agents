"""git, run in the hub's checkout, a profile, or any repo the hub reads, never raising: what it printed, why it failed, the latest pulled, the root of the repo a directory is in, and the main checkout of a linked worktree."""

import os
import subprocess
from pathlib import Path

from agentkit import words


def run(where: Path, *args: str) -> subprocess.CompletedProcess:
  """Run git in `where` and return what it did, whatever its exit code; a git that cannot start is exit 127.
  Never a prompt: its output is captured, so a credential prompt would wait unseen, and a pull fails instead."""
  try: return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL, env=os.environ | {"GIT_TERMINAL_PROMPT": "0"})
  except OSError as error: return subprocess.CompletedProcess(["git", *args], 127, "", str(error))


def last_line(result: subprocess.CompletedProcess, quiet: str) -> str:
  """The reason a finished command gives: the last line of its stderr, else of its stdout, else `quiet`."""
  return next((lines[-1] for text in (result.stderr, result.stdout) if (lines := (text or "").strip().splitlines())), quiet)


def pull(where: Path) -> tuple[bool, str]:
  """Pull `where` without ever merging; whether it worked and what moved ("pulled N commits" or "already current"), or git's reason when it did not."""
  before = run(where, "rev-parse", "--verify", "-q", "HEAD").stdout.strip()   # empty in a repo with no commits, where plain rev-parse prints "HEAD"
  if (pulled := run(where, "pull", "--ff-only", "-q")).returncode: return False, last_line(pulled, "git said nothing")
  count = int(run(where, "rev-list", "--count", f"{before}..HEAD" if before else "HEAD").stdout.strip() or 0)
  return True, f"pulled {words.count(count, 'commit')}" if count else "already current"


_ROOTS: dict[Path, Path | None] = {}   # the root found for each directory asked about, kept for the process


def root(directory: Path) -> Path | None:
  """The repository root containing `directory`, or None; cached."""
  directory = Path(directory)
  if directory not in _ROOTS:
    result = run(directory, "rev-parse", "--show-toplevel")
    _ROOTS[directory] = Path(result.stdout.strip()) if result.returncode == 0 else None
  return _ROOTS[directory]


def main_checkout(directory: Path) -> Path | None:
  """The main checkout of the linked worktree holding `directory`, or None anywhere else.
  A bare repo's worktrees and a submodule's have no main checkout: the common dir is not a `.git`, or one with no work tree."""
  result = run(directory, "rev-parse", "--git-dir", "--git-common-dir")
  if result.returncode: return None
  git_dir, common = ((Path(directory) / line).resolve() for line in result.stdout.splitlines())   # relative to `directory` when git does not print them absolute
  if git_dir == common or common.name != ".git": return None
  return common.parent if root(common.parent) == common.parent else None
