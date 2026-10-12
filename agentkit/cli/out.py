"""How every command outputs: results on stdout, status and failures on stderr, and an exit code.

`rich` is imported only to draw to a terminal, since the CLI loads on every hook call; piped or without
it, the same text prints plain and a table tab-separated. One lock covers every write, so a line prints whole.

Author: Marco Cassar (@Ocramaru)
"""

import json
import re
import sys
import threading

_WRITE = threading.Lock()


def line(text: object) -> None:
  """One result line on stdout, printed immediately, for output a command produces while it runs."""
  with _WRITE: print(text, flush=True)


def done(*lines: object, code: int = 0) -> int:
  """A command's results on stdout, one per line, and its exit code. A `None` line is skipped."""
  for text in lines:
    if text is not None: line(text)
  return code


def dump(data: object, **options) -> int:
  """JSON on stdout, for a script or an agent to read."""
  return done(json.dumps(data, indent=2, **options))


def fail(message: object, code: int = 1) -> int:
  """What went wrong, on stderr in red, and the exit code: 1 nothing to do or it failed, 2 asked wrongly."""
  say(f"[red]{escape(message)}[/red]", sys.stderr)
  return code


def note(message: object) -> None:
  """A status line on stderr, dimmed, so it never mixes into output a script reads."""
  say(f"[dim]{escape(message)}[/dim]", sys.stderr)


def report(code: int, message: object) -> int:
  """A helper's (exit code, message): stdout when it worked, stderr when it did not."""
  return fail(message, code) if code else done(message)


def took(seconds: float) -> str:
  """Seconds as `42s`, or `3m05s` past a minute."""
  minutes, remainder = divmod(round(seconds), 60)
  return f"{minutes}m{remainder:02d}s" if minutes else f"{remainder}s"


def oneline(text: object, width: int) -> str:
  """Text on one line, cut to `width`."""
  flat = " ".join(str(text).split())
  return flat if len(flat) <= width else flat[:width - 1] + "…"


def table(headers: list[str], rows: list[list[str]], title: str = "", note: str = "",
          wide: tuple[str, ...] = (), group: bool = False) -> int:
  """Draw a table and return 0; `wide` columns wrap, and `group` names the first column once per run of equal values.

  Piped, the first column repeats on every row, since a script greps lines. Cells are our markup: a caller escapes text that is not its own.
  """
  try:
    if not sys.stdout.isatty(): raise ImportError
    from rich import box
    from rich.console import Console
    from rich.table import Table
  except ImportError:
    return done(*("\t".join(plain(cell) for cell in row) for row in rows))

  drawn = Table(title=title or None, box=box.ROUNDED, header_style="bold", title_style="bold",
                caption=note or None, caption_style="dim", expand=False, pad_edge=True,
                show_lines=bool(wide) and not group)   # rules between rows once cells wrap

  for header in headers:
    drawn.add_column(header, overflow="fold" if header in wide else "ellipsis", no_wrap=header not in wide,
                     style="cyan" if header == headers[0] else None)

  last = None
  for row in rows:
    if group and last is not None and row[0] != last: drawn.add_section()
    drawn.add_row("" if group and row[0] == last else row[0], *row[1:])
    last = row[0]

  with _WRITE: Console().print(drawn)
  return 0


def say(text: str, to=None) -> None:
  """One line with our markup: styled on a terminal, plain when piped, as `table` treats a table."""
  to = to or sys.stdout

  try:
    if not to.isatty(): raise ImportError
    from rich.console import Console
  except ImportError:
    with _WRITE: print(plain_line(text), file=to, flush=True)
    return

  with _WRITE: Console(file=to, highlight=False, soft_wrap=True).print(text)


def plain_line(line: str) -> str:
  """`plain` for a line that keeps its own spacing, since indentation carries meaning in a report."""
  return re.sub(r"(?<!\\)\[/?[a-z ]+\]", "", line).replace("\\[", "[")


def escape(text: str) -> str:
  """Text from a model or a file, made safe to put in a cell.

  Rich deletes any `[name]` it reads as markup, so every bracket that is not our styling is escaped.
  """
  return str(text).replace("[", "\\[")


def plain(cell: str) -> str:
  """A cell as plain text: our markup removed, escaped brackets restored, no line breaks."""
  return " ".join(plain_line(cell).split())
