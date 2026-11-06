"""What must not run: the formatters `[guard]` names, where a layout is a decision and one sweep buries a small change.
It parses the command rather than grepping it, since a regex cannot tell a formatter being run from one named in a quoted string.
"""

import re
import shlex
from fnmatch import fnmatch
from itertools import dropwhile, groupby
from pathlib import Path

OPERATORS = "();<>|&\n"   # a run of these separates two commands
HOOK_ID = re.compile(r"^\s*(?:-\s*)?id:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)   # a hook's `id:` in .pre-commit-config.yaml


def covers(entry: str, command: list[str], segment: list[str]) -> int:
  """How many leading words of `command` an entry names, or 0 when it does not match.
  Its words lead `command` as globs and its flags appear anywhere in `segment`: `ruff check --unsafe-fixes`, `python* -m`."""
  names, flags = [word for word in entry.split() if not word.startswith("-")], {word for word in entry.split() if word.startswith("-")}
  return len(names) if len(names) <= len(command) and all(fnmatch(token, name) for token, name in zip([command[0].rsplit("/", 1)[-1], *command[1:]], names)) and flags <= set(segment) else 0


def precommit_formatter(settings: dict, start: Path | None = None, named: list[str] | tuple = ()) -> str | None:
  """A formatter in the nearest `.pre-commit-config.yaml`, if there is one. `named` is the words after `pre-commit run`: one that is a hook id in the config means only that hook runs.
  Read as text, not YAML, so a check on the way to every shell command needs no dependency; asking the config, not pre-commit's flags, which word is a hook."""
  here = Path(start or Path.cwd()).resolve()
  if not settings["enabled"]: return None

  for directory in [here, *here.parents]:
    if (config_file := directory / ".pre-commit-config.yaml").is_file():
      ids = set(HOOK_ID.findall(config_file.read_text(encoding="utf-8", errors="replace")))
      chosen = ids & set(named)
      return next((hook for name in settings["formatters"] if len(words := name.split()) <= 2 and (hook := '-'.join(words)) in ids and (not chosen or hook in chosen)), None)   # pre-commit spells `ruff format` as ruff-format
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

    pending = [segment]   # what may be the command, one reading per way a runner's flags can be read
    while pending:
      if not (words := pending.pop()): continue
      if found := next((name for name in settings["formatters"] if covers(name, words, segment)), None): return found
      # a script runner names its target anywhere after its flags: `make -j4 fmt`, `make build fmt`
      if found := next((f"{' '.join(words[:size])} {target}" for entry in settings["scripts"] if (size := covers(entry, words, segment)) for target in words[size:] if target in settings["targets"]), None):
        return found
      if words[0].rsplit("/", 1)[-1] == "pre-commit" and words[1:2] in ([], ["run"]) and (found := precommit_formatter(settings, root, words[2:])):
        return f"pre-commit, whose config runs {found}"

      # step past what stands in front of the command: an assignment, or a runner and its flags
      if "=" in words[0] and not words[0].startswith("-"): pending.append(words[1:])
      elif size := next((size for entry in settings["runners"] if (size := covers(entry, words, segment))), 0):
        pending += past_flags(words[size:], settings["valued"])
  return None


def past_flags(words: list[str], valued: list[str]) -> list[list[str]]:
  """`words` from the first one that is not a runner's flag, read both ways a flag in `valued` can go.
  `-n` stands alone in `sudo -n black` and takes a value in `nice -n 10 black`, and only the runner knows which, so both readings are checked."""
  alone, taking = list(dropwhile(lambda token: token.startswith("-"), words)), words
  while taking and taking[0].startswith("-"): taking = taking[2:] if taking[0] in valued else taking[1:]
  return [alone] if taking == alone else [alone, taking]
