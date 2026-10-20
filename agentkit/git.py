"""git, run in the hub's checkout, a profile, or any repo the hub reads, never raising.

Author: Marco Cassar (@Ocramaru)
"""

import subprocess
from pathlib import Path


def run(where: Path, *args: str) -> subprocess.CompletedProcess:
  """Run git in `where` and return what it did, whatever its exit code."""
  return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, check=False)
