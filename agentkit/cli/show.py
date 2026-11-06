"""How results read: what a review's result was, one review as it lands, the open findings as a table.

Kept apart from the commands because a run prints a result live and `agent sub reviews` prints it again later, and both print it the same way.
"""

import re
import sys

from agentkit import review, reviews, session, words
from agentkit.cli.out import escape, note, oneline, say, table, took

MARKS = {"failed": ("✗", "red"), "asked": ("?", "cyan"), "clean": ("✓", "green"), "found": ("●", "yellow")}   # a result's glyph and color
INDENT = 4   # a result's lines under its heading
COLUMN = 6   # the width a finding's line is right-aligned to, so the findings' text starts in one column


def outcome(reviewed: dict) -> str:
  """Which one thing a result was, for the tally and for how it prints."""
  if reviewed["state"] == "failed": return "failed"
  if reviewed["state"] == "input-required": return "asked"
  if reviewed.get("reused"): return "unchanged"
  if reviewed["body"] == review.EMPTY: return "empty"
  return "found" if reviewed["findings"] else "clean"


def result(reviewed: dict, at: str = "", out=None) -> None:
  """One review: what it returned, and the command that acts on it, printed as a run lands and when read back."""
  put = lambda text, indent=0: say(" " * indent + text, out)
  hang = lambda text, indent: escape(str(text)).replace("\n", "\n" + " " * indent)
  where = lambda finding: str(finding.get("line", "?")) if finding.get("file", reviewed["file"]) == reviewed["file"] else f"{finding['file']}:{finding.get('line', '?')}"   # a review over several files names each finding's file

  count, kind = len(reviewed["findings"]), outcome(reviewed)
  glyph, color = MARKS.get(kind, ("", ""))
  timing = f" · {took(reviewed['seconds'])}" if reviewed.get("seconds") else ""
  head = f"{at}{escape(reviewed['file'])}  [dim]{escape(reviewed['agent'])}{timing}[/dim]"
  status = lambda label, after="": put(f"[{color}]{glyph}[/{color}] {head}  [{color}]{label}[/{color}]{after}")

  if kind == "failed":
    status("failed")
    put(f"{'answered without the JSON it was asked for' if reviewed.get('kind') == session.UNREADABLE else 'error'}: [dim]{escape(oneline(reviewed['body'], 240))}[/dim]", INDENT)
    if reviewed.get("task"): put(f"[dim]its whole reply: agent sub reviews {reviewed['task']}[/dim]", INDENT)
  elif kind == "asked":
    status("asked a question")
    put(escape(reviewed["body"]), INDENT)
    put(f"[dim]answer: agent sub reply {reviewed['task']} '<answer>'[/dim]", INDENT)
  elif kind == "unchanged":   # not asked again: its verdict still stands
    put(f"[dim]= {at}{escape(reviewed['file'])}  {escape(reviewed['agent'])}  unchanged since run {reviewed['reused']} · {f'{count} still open' if count else 'nothing open'}[/dim]")
    for finding in reviewed["findings"]: put(f"[dim]{escape(where(finding)):>{COLUMN}}  {escape(oneline(finding.get('issue', ''), 120))}[/dim]", INDENT)
  elif kind == "empty":
    put(f"[dim]– {at}{escape(reviewed['file'])}  empty, nothing to review[/dim]")
  elif kind == "clean":
    status("clean", f"  [dim]{escape(oneline(reviewed['body'], 120))}[/dim]" if reviewed["body"] else "")
  else:
    status(words.count(count, "finding"))
    if reviewed["body"]: put(escape(reviewed["body"]), INDENT)
    for finding in reviewed["findings"]:
      label = where(finding)
      width = max(COLUMN, len(label))   # a file:line label pushes its text right
      text = INDENT + width + 2   # where the finding's text starts, past the label and its gap
      put(f"[bold]{escape(label):>{width}}[/bold]  {hang(finding.get('issue', ''), text)}", INDENT)
      if finding.get("fix"): put(f"[dim]→ {hang(finding['fix'], text + 2)}[/dim]", text)
    again = reviewed.get("again") or f"agent sub review --recheck {reviewed['file']}"
    put(f"[dim]fixed it? {escape(again)}[/dim]", INDENT)


def findings(found: list[dict], full: bool = False) -> int:
  """Open findings as a table grouped by file, one row per problem; repeats list their lines."""
  if not found:
    note("nothing open")
    return 0

  shorten = not full and sys.stdout.isatty()   # a script reading the pipe gets every word
  files = list(dict.fromkeys(finding["file"] for finding in found))

  rows = []
  for file in files:
    groups: dict[tuple[str, str], dict] = {}   # (issue, reviewer) -> its lines, ids and fix: one row per reviewer
    for finding in (finding for finding in found if finding["file"] == file):
      issue = " ".join(str(finding["issue"]).split())
      if shorten: issue = re.split(r"\.\s+(?=[A-Z`])", issue, maxsplit=1)[0].rstrip(".")   # its first sentence
      group = groups.setdefault((issue, finding.get("agent") or "?"), {"lines": [], "ids": [], "fix": finding["fix"]})
      group["lines"].append(reviews.first_line(finding["line"]))
      group["ids"].append(reviews.short_id(finding["id"]))

    for (issue, reviewer), group in groups.items():
      if shorten and len(issue) > 140: issue = issue[:139] + "…"   # --full has the rest
      row = [escape(file), reviewer, ", ".join(str(number) for number in sorted(set(group["lines"])) if number) or "-", escape(issue), " ".join(group["ids"])]
      if full: row.append(escape(" ".join(str(group["fix"]).split())))
      rows.append(row)

  return table(["file", "reviewer", "line", "finding", "id"] + (["fix"] if full else []), rows, title=f"{len(found)} open in {words.count(len(files), 'file')}",
               note="agent sub close <id ...> --as fixed|wrong|wontfix --reason '…'   ·   agent sub review --recheck"
                    + ("" if full else "   ·   --full for each fix"),
               wide=("finding", "fix", "line"), group=True)
