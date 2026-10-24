"""Friction with the hub, drafted as an issue on it from any repo, since another repo's notes are never read here.
A draft carries the .agents commit and platform; the repo and hostname only with `--context`, as issues are public.
Nothing is filed: the draft opens as a prefilled GitHub page for the person to read, edit and submit.
"""

import importlib.metadata
import json
import platform
import re
import socket
import urllib.parse
import webbrowser
from pathlib import Path

from agentkit import gh, git, hub

LINK_LIMIT = 8000   # characters a browser will take in a link


def slug(checkout: Path = hub.BUNDLED) -> str | None:
  """owner/name of the hub on GitHub: a clone's origin remote, or the Repository URL an install carries in its metadata."""
  return gh.repository(dict(entry.split(", ", 1) for entry in importlib.metadata.metadata("agentkit").get_all("Project-URL") or []).get("Repository", "") if hub.INSTALLED else git.run(checkout, "remote", "get-url", "origin").stdout.strip())


def open_issues(repository: str) -> list[dict] | None:
  """The open issues, or None when they could not be read.
  None is not an empty list: read as one, a duplicate check passes whenever gh is down."""
  result = gh.run("issue", "list", "--repo", repository, "--state", "open", "--limit", "1000",
              "--json", "number,title,url,comments")
  if result.returncode: return None
  try: return json.loads(result.stdout)
  except json.JSONDecodeError: return None


def filed(repository: str) -> list[str]:
  """What is already filed, so a session reads the answer instead of filing the question again.
  Dedupe points at the first copy but does not show that it has a reply waiting."""
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


def draft(title: str, body: str, working_directory: Path, repository: str, dry: bool = False,
          context: bool = False) -> str:
  """Open a prefilled new-issue page, or the open issue that already says it, and return what to show the person. Nothing is filed."""
  foot = f"agentkit {hub.version()} · {platform.system()}"

  if context:   # issues on .agents are public, and a hostname or a private repo's name is not theirs
    root = git.root(working_directory)
    foot += f" · met in {(root or working_directory).name} · {socket.gethostname()}"   # a folder's name only: its full path names the person's home
  full = f"{body.strip()}\n\n---\n{foot}" if body.strip() else foot

  found = open_issues(repository)
  notes = ["The duplicate check was skipped: gh could not read the open issues (is it installed and logged in?)."] if found is None else []

  # the same title ignoring case and punctuation; a title with nothing left to compare matches nothing
  normalise = lambda text: " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())
  wanted = normalise(title)
  existing = next((issue for issue in found or [] if wanted and normalise(issue["title"]) == wanted), None)

  if existing:
    target = existing["url"]
    shown = [f"#{existing['number']} on {repository} already says this: {existing['title']}", "Paste this under it as a comment:", "", full]
  else:
    lines = full.split("\n")
    kept = len(lines)
    while len(target := f"https://github.com/{repository}/issues/new?" + urllib.parse.urlencode({"title": title, "body": "\n".join(lines[:kept])}, quote_via=urllib.parse.quote)) > LINK_LIMIT and kept: kept -= 1
    if kept < len(lines): notes.append(f"A browser caps the length of a link, so it carries {kept} of the {len(lines)} lines; paste the whole body above.")
    shown = [f"Draft issue for {repository}; nothing is filed until you submit it:", "", f"# {title}", "", full]

  return "\n".join([*shown, "", *notes, f"{'Dry run, nothing opened' if dry else 'Opened in your browser' if webbrowser.open(target) else 'No browser opened'}: {target}"])
