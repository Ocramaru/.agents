"""The generated section table at the top of a note, pure text in and text out.
The block's height depends only on the section count, so it is laid out at full size, then numbered against the finished text in one pass.
Nothing is stored elsewhere: a note is stale exactly when `apply` would change it.

Author: Marco Cassar (@Ocramaru)
"""

import re

# the marker carries its instructions where a hand editor looks, and as a comment it does not render
START = "<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->"
END = "<!-- /map -->"
# any `<!-- map` marker matches, so a block with an older marker is replaced rather than doubled
BLOCK = re.compile(r"\n*<!-- map\b[^>]*-->.*?" + re.escape(END) + r"\n*", re.DOTALL)
HEADING = re.compile(r"^#{2,3}\s+(.+?)\s*$")
MIN_SECTIONS = 2   # one section is not a table of contents


def strip(text: str) -> str:
  """The text with its section map removed."""
  return BLOCK.sub("\n\n", text, count=1)


def headings(lines: list[str]) -> list[tuple[str, int]]:
  """Headings and their line numbers, ignoring anything inside a fenced block."""
  out, fenced = [], False
  for line_number, line in enumerate(lines, 1):
    if line.startswith("```"): fenced = not fenced
    if fenced: continue
    matched = HEADING.match(line)
    if matched: out.append((matched.group(1), line_number))
  return out


def apply(text: str) -> str:
  """Add or refresh the block. Idempotent, and correct in one pass."""
  base = strip(text).splitlines()
  found = headings(base)
  if len(found) < MIN_SECTIONS: return "\n".join(base).rstrip("\n") + "\n"

  # the line after the frontmatter and the title, where a reader looks first
  at = next((index + 1 for index, line in enumerate(base[1:], 1) if line.strip() == "---"), 0) if base and base[0].strip() == "---" else 0
  while at < len(base) and not base[at].startswith("# "): at += 1
  at = min(at + 1, len(base))
  # the block's height follows the row count, not the numbers in it
  assemble = lambda rows: base[:at] + ["", START, "", "| section | line |", "|---|---|",
                                       *[f"| {name} | {line} |" for name, line in rows], "", END, ""] + base[at:]
  return "\n".join(assemble(headings(assemble([(heading, 0) for heading, _ in found])))).rstrip("\n") + "\n"   # the inner one: right height, wrong numbers
