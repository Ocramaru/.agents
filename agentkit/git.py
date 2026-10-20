"""git, run in the hub's checkout, a profile, or any repo the hub reads, never raising: what it printed, the root of the repo a directory is in, and the main checkout of a linked worktree.

Author: Marco Cassar (@Ocramaru)
"""

import subprocess
from pathlib import Path


def run(where: Path, *args: str) -> subprocess.CompletedProcess:
  """Run git in `where` and return what it did, whatever its exit code."""
  return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, check=False)


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
