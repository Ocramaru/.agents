"""The log of hook firings, one line each from `hooks/log.sh`, read back and written from Python.
A hook that injected unseen context, one that sent nothing and one that crashed look alike, so the log is the record.

Author: Marco Cassar (@Ocramaru)
"""

import os
import time
from pathlib import Path

LOG = Path(os.environ.get("AGENTS_HOOK_LOG") or Path.home() / ".agents" / ".hooks.log")   # hooks/log.sh reads the same variable


ROUTINE = ("allow", "off", "skip")   # ran and had nothing to decide; the record keeps them


def entries(session: str = "", log: Path = LOG, verbose: bool = False, hook: str = "") -> list[list[str]]:
  """Log rows as [time, hook, session, status, detail], unpadded, oldest first, for `session` or any prefix of it and for `hook`, with routine rows only when `verbose`.

  `no-reformat` logs every Bash command, which would bury the `inject` lines. A line that is not a row passes through whole as its detail, and matches no `session` or `hook`.
  """
  log = Path(log)
  if not log.is_file(): return []

  kept = []
  for row in log.read_text(encoding="utf-8", errors="replace").splitlines():
    fields = [field.strip() for field in row.split("\t")]
    if len(fields) < 4:
      if not session and not hook: kept.append(["", "", "", "", row])
      continue
    status, *detail = fields[3].split(None, 1) or [""]
    if not verbose and status in ROUTINE: continue   # sent, quiet, ERROR, allow...
    if session and not fields[2].startswith(session[:8]): continue
    if hook and fields[1] != hook: continue
    kept.append([fields[0], fields[1], fields[2], status, "".join(detail)])
  return kept


STYLE = {"ERROR": "bold red", "BLOCKED": "yellow", "sent": "green", "quiet": "dim", "none": "dim",
         "review": "cyan", "done": "green"}


def log(hook: str, session: str, text: str, log: Path = LOG) -> None:
  """One line in the format hooks/log.sh writes, for work such as a review that outlives its hook.

  It never raises, since a log that cannot be written is no reason to fail a review.
  """
  try:
    with Path(log).open("a", encoding="utf-8") as handle:
      handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\t{hook:<10}\t{session[:8]:<8}\t{text}\n")
  except OSError: pass

