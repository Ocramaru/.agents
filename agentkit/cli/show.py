"""How results read: one review as it lands, a run's tally, the open findings as a table.

Kept apart from the commands because a run prints a result live and `agent sub reviews` prints it
again later, and both print it the same way.

Author: Marco Cassar (@Ocramaru)
"""

import re
import sys

from agentkit import review, reviews, session
from agentkit.cli.out import escape, note, oneline, say, table, took


def outcome(reviewed: dict) -> str:
  """Which one thing a result was, for the tally and for how it prints."""
  if reviewed["state"] == "failed": return "failed"
  if reviewed["state"] == "input-required": return "asked"
  if reviewed.get("reused"): return "unchanged"
  if reviewed["body"] == review.EMPTY: return "empty"
  return "found" if reviewed["findings"] else "clean"


def result(reviewed: dict, at: str = "", out=None) -> None:
  """One review: what it returned, and the command that acts on it, printed as a run lands and when read back."""
  put = lambda text: say(text, out)

  head = f"{at}{escape(reviewed['file'])}  [dim]{reviewed['agent']}{f" · {took(reviewed['seconds'])}" if reviewed.get("seconds") else ""}[/dim]"
  count, kind = len(reviewed["findings"]), outcome(reviewed)

  if kind == "failed":
    put(f"[red]✗[/red] {head}  [red]failed[/red]")
    put(f"    {'answered without the JSON it was asked for' if reviewed.get('kind') == session.UNREADABLE else 'error'}: [dim]{escape(oneline(reviewed['body'], 240))}[/dim]")
    if reviewed.get("task"): put(f"    [dim]its whole reply: agent sub reviews {reviewed['task']}[/dim]")
  elif kind == "asked":
    put(f"[cyan]?[/cyan] {head}  [cyan]asked a question[/cyan]")
    put(f"    {escape(reviewed['body'])}")
    put(f"    [dim]answer: agent sub reply {reviewed['task']} '<answer>'[/dim]")
  elif kind == "unchanged":   # not asked again: its verdict still stands
    put(f"[dim]= {at}{escape(reviewed['file'])}  {reviewed['agent']}  unchanged since run {reviewed['reused']} · {f'{count} still open' if count else 'nothing open'}[/dim]")
    for finding in reviewed["findings"]: put(f"    [dim]{escape(str(finding.get('line', '?'))):>6}  {escape(oneline(finding.get('issue', ''), 120))}[/dim]")
  elif kind == "empty":
    put(f"[dim]– {at}{escape(reviewed['file'])}  empty, nothing to review[/dim]")
  elif kind == "clean":
    put(f"[green]✓[/green] {head}  [green]clean[/green]{f"  [dim]{escape(oneline(reviewed['body'], 120))}[/dim]" if reviewed["body"] else ""}")
  else:
    put(f"[yellow]●[/yellow] {head}  [yellow]{count} finding{'s' if count != 1 else ''}[/yellow]")
    if reviewed["body"]: put(f"    {escape(reviewed['body'])}")
    for finding in reviewed["findings"]:
      put(f"    [bold]{escape(str(finding.get('line', '?'))):>6}[/bold]  " + escape(finding.get("issue", "")).replace("\n", "\n            "))
      if finding.get("fix"): put("            [dim]→ " + escape(str(finding["fix"])).replace("\n", "\n              ") + "[/dim]")
    put(f"    [dim]fixed it? agent sub review --recheck {escape(reviewed['file'])}[/dim]")


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

  return table(["file", "reviewer", "line", "finding", "id"] + (["fix"] if full else []), rows, title=f"{len(found)} open in {len(files)} file{'' if len(files) == 1 else 's'}",
               note="agent sub close <id ...> --as fixed|wrong|wontfix --reason '…'   ·   agent sub review --recheck"
                    + ("" if full else "   ·   --full for each fix"),
               wide=("finding", "fix", "line"), group=True)
