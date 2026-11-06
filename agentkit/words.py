"""How a message is worded and laid out, so every report counts things and lines up its column the same way.
Stdlib only and imports nothing, since the hooks and the CLI both use it.
"""

STATUS = 6   # the width a status word is padded to, so what follows it starts in one column
UNDER = 2   # how far a report's lines sit in under their heading
CHANGED = ("copy", "link", "saved", "wrote", "point", "made", "set", "unset", "clone", "drop", "keep")   # the status words of a line that changed something, which `install --changes` keeps
UNCHANGED = ("ok", "skip", "note", "FAIL")   # the status words of a line that changed nothing, or could not; every word `status` is given is in one of the two


def count(number: int, word: str) -> str:
  """`number` of `word`, plural unless one: `count(3, "file")` is `3 files`."""
  return f"{number} {word}{'' if number == 1 else 's'}"


def status(word: str, text: str, indent: int = 0) -> str:
  """A report line, its status word padded to `STATUS` and any later line hung under the text: `status("ok", "hooks")` is `ok    hooks`."""
  return indented(f"{word:<{STATUS - 1}} " + text.replace("\n", "\n" + " " * STATUS), indent)   # a space after the word, even one as wide as the column


def indented(text: str, by: int = UNDER) -> str:
  """`text` moved in by `by` spaces, every line of it."""
  return "\n".join(" " * by + line for line in text.split("\n"))
