"""Friction with the hub, filed as an issue on it from any repo, since another repo's notes are never read here.
A report carries the .agents commit and platform; the repo and hostname only with `--context`, as issues are public.
A title already open gets a comment rather than a second issue.

Author: Marco Cassar (@Ocramaru)
"""

import json
import platform
import re
import socket
import subprocess
from pathlib import Path

from agentkit import tree
from agentkit.profile import HUB, git


def gh(*args: str) -> subprocess.CompletedProcess:
  """Run the GitHub CLI; exit 127 when it is missing."""
  try: return subprocess.run(["gh", *args], capture_output=True, check=False, text=True)
  except FileNotFoundError:   # most people cloning .agents will not have it
    return subprocess.CompletedProcess(["gh", *args], 127, "", "gh is not installed: https://cli.github.com")


def slug(hub: Path = HUB) -> str | None:
  """owner/name for the hub's remote, from git rather than written down anywhere."""
  match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", git(hub, "remote", "get-url", "origin").stdout.strip())
  return match.group(1) if match else None      # a failed call prints nothing, so it cannot match


def open_issues(repository: str) -> list[dict] | None:
  """The open issues, or None when they could not be read.
  None is not an empty list: read as one, dedupe files a duplicate whenever gh is down."""
  result = gh("issue", "list", "--repo", repository, "--state", "open", "--limit", "1000",
              "--json", "number,title,url,comments")
  if result.returncode: return None
  try: return json.loads(result.stdout)
  except json.JSONDecodeError: return None


def filed(repository: str) -> list[str]:
  """What is already filed, so a session reads the answer instead of filing the question again.
  Dedupe stops a second copy but does not show that the first has a reply waiting."""
  found = open_issues(repository)
  if found is None: return ["could not read the issues: is gh installed and logged in? (gh auth status)"]

  out = []
  for issue in found:
    count = issue.get("comments") or 0
    count = len(count) if isinstance(count, list) else count     # gh returns the comments themselves, older ones a count
    # comments, not replies: a repeat report from another machine lands as a comment too
    out.append(f"#{issue['number']}  {issue['title']}" + (f", {count} comment{'' if count == 1 else 's'}" if count else "")
               + f"\n    {issue['url']}")
  return out


def file(title: str, body: str, working_directory: Path, repository: str, dry: bool = False,
           context: bool = False) -> tuple[int, str]:
  """File it, or add to the open issue that already says it. Returns (exit code, what happened)."""
  foot = f".agents at {git(HUB, "rev-parse", "--short", "HEAD").stdout.strip() or 'unknown'} · {platform.system()}"

  if context:   # issues on .agents are public, and a hostname or a private repo's name is not theirs
    root = tree.git_root(working_directory)
    foot += f" · met in {root.name if root else working_directory} · {socket.gethostname()}"
  full = f"{body.strip()}\n\n---\n{foot}" if body.strip() else foot

  found = open_issues(repository)
  if found is None: return 1, "could not read the open issues, so not filing blind: gh auth status"

  # the same title ignoring case and punctuation; a title with nothing left to compare matches nothing
  normalise = lambda text: " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())
  wanted = normalise(title)
  existing = next((issue for issue in found if wanted and normalise(issue["title"]) == wanted), None)

  if dry:
    return 0, (f"would comment on {existing['url']}:\n\n{full}" if existing
               else f"would open on {repository}:\n\n# {title}\n\n{full}")

  if existing:
    result = gh("issue", "comment", str(existing["number"]), "--repo", repository, "--body", full)
    return (0, f"added to {existing['url']}") if result.returncode == 0 else (1, result.stderr.strip())
  result = gh("issue", "create", "--repo", repository, "--title", title, "--body", full)
  return (0, result.stdout.strip()) if result.returncode == 0 else (1, result.stderr.strip())
