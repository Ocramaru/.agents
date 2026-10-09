"""What must not run: the formatters `[guard]` names, where a layout is a decision and one sweep buries a small change.
It parses the command rather than grepping it, since a regex cannot tell a formatter being run from one named in a quoted string.

Author: Marco Cassar (@Ocramaru)
"""

import shlex
from fnmatch import fnmatch
from itertools import dropwhile, groupby
from pathlib import Path

OPERATORS = "();<>|&\n"   # a run of these separates two commands


def covers(entry: str, command: list[str], segment: list[str]) -> int:
  """How many leading words of `command` an entry names, or 0 when it does not match.
  Its words lead `command` as globs and its flags appear anywhere in `segment`: `ruff check --unsafe-fixes`, `python* -m`."""
  names, flags = [word for word in entry.split() if not word.startswith("-")], {word for word in entry.split() if word.startswith("-")}
  return len(names) if len(names) <= len(command) and all(fnmatch(token, name) for token, name in zip([command[0].rsplit("/", 1)[-1], *command[1:]], names)) and flags <= set(segment) else 0


def precommit_formatter(settings: dict, start: Path | None = None) -> str | None:
  """A formatter in the nearest `.pre-commit-config.yaml`, if there is one.
  Read as text, not YAML, so a check on the way to every shell command needs no dependency."""
  here = Path(start or Path.cwd()).resolve()
  if not settings["enabled"]: return None

  for directory in [here, *here.parents]:
    if (config_file := directory / ".pre-commit-config.yaml").is_file():
      text = config_file.read_text(encoding="utf-8", errors="replace")
      return next((hook for name in settings["formatters"] if len(words := name.split()) <= 2 and f"id: {(hook := '-'.join(words))}" in text), None)   # pre-commit spells `ruff format` as ruff-format
    if (directory / ".git").exists(): return None    # stop at the repo, like every other walk here
  return None


def formatter(command: str, settings: dict, root: Path | None = None) -> str | None:
  """The formatter this command would run under the `[guard]` `settings`, or None.
  Unparseable input returns None, since a false block stops work that was fine and costs more than a rare miss."""
  if not settings["enabled"]: return None
  lexer = shlex.shlex(command, posix=True, punctuation_chars=OPERATORS)
  lexer.whitespace, lexer.whitespace_split = " \t\r", True   # a newline separates commands, so it is an operator here, not space
  try: tokens = list(lexer)
  except ValueError: return None

  for is_operator, group in groupby(tokens, lambda token: set(token) <= set(OPERATORS)):
    if is_operator or set(settings["inspect"]) & set(segment := list(group)): continue   # --check and --diff report; they do not rewrite

    words = segment
    while words:
      if found := next((name for name in settings["formatters"] if covers(name, words, segment)), None): return found
      if found := next((" ".join(words[:size + 1]) for entry in settings["scripts"] if (size := covers(entry, words, segment)) and words[size:size + 1] and words[size] in settings["targets"]), None): return found
      if words[0].rsplit("/", 1)[-1] == "pre-commit" and words[1:2] in ([], ["run"]) and (found := precommit_formatter(settings, root)): return f"pre-commit, whose config runs {found}"

      # step past what stands in front of the command: an assignment, or a runner and its flags
      if "=" in words[0] and not words[0].startswith("-"): words = words[1:]
      elif size := next((size for entry in settings["runners"] if (size := covers(entry, words, segment))), 0): words = list(dropwhile(lambda token: token.startswith("-"), words[size:]))
      else: break
  return None
