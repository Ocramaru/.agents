"""The GitHub CLI, when it is installed: running it, who it is logged in as, and the repo a remote address names."""

import functools
import re
import subprocess


def run(*args: str) -> subprocess.CompletedProcess:
  """Run the GitHub CLI and return what it did; a missing gh comes back as exit code 127."""
  try: return subprocess.run(["gh", *args], capture_output=True, check=False, text=True)
  except FileNotFoundError:   # most people cloning .agents will not have it
    return subprocess.CompletedProcess(["gh", *args], 127, "", "gh is not installed: https://cli.github.com")


@functools.cache
def login() -> str:
  """The GitHub account gh is logged in as; empty when gh is missing or not logged in."""
  user = run("api", "user", "--jq", ".login")
  return user.stdout.strip() if user.returncode == 0 else ""


def repository(address: str) -> str | None:
  """owner/name from a remote's URL or scp-style address, or None when it names no repo."""
  match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", address)
  return match.group(1) if match else None      # an empty address, as a failed git call leaves, names nothing
