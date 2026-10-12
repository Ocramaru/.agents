"""Commands declare themselves, and the parser is built from what registered.

A command is one decorated function, and `run()` is the only code that touches argparse, so
adding one cannot half-happen.

Author: Marco Cassar (@Ocramaru)
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from agentkit import version

GROUPS: dict[str, str] = {}   # group -> its line in `agent --help`, set by the module that holds its commands
COMMANDS: list["Command"] = []
DEFAULTS: dict[str, Callable] = {}   # group -> what bare `agent <group>` and `--list` run


@dataclass
class Command:
  """One registered command."""
  name: str
  function: Callable
  help: str = ""
  group: str | None = None
  variadic: str | None = None   # dest that absorbs positionals argparse could not place
  args: list = field(default_factory=list)


def arg(*names, **options) -> Callable:
  """Add an argument to the command below; takes `add_argument`'s parameters."""
  def wrap(function):
    function._args = [*getattr(function, "_args", []), (names, options)]
    return function
  return wrap


def command(name: str, *, help: str = "", group: str | None = None, variadic: str | None = None,
            default: bool = False) -> Callable:
  """Register the function below as `agent [group] <name>`, and as what bare `agent <group>` runs when `default`."""
  def wrap(function):
    if any(registered.name == name and registered.group == group for registered in COMMANDS):
      raise ValueError(f"command {'/'.join(filter(None, (group, name)))} is already registered")

    COMMANDS.append(Command(name, function, help, group, variadic,
                            list(reversed(getattr(function, "_args", [])))))
    if default and group: DEFAULTS[group] = function
    return function
  return wrap


def run(arguments: list[str] | None = None) -> int:
  """Build the parser for every registered command, parse `arguments` and run the command they name.

  A command typed alone that needs arguments prints its help. Positionals stranded after a flag go to its `variadic` list.
  """
  if tuple(sys.argv[1:] if arguments is None else arguments) == ("--version",):   # before the parser, which every hook call would otherwise pay for
    print(f"agentkit {version()}")
    return 0

  parser = argparse.ArgumentParser(prog="agent")
  parser.add_argument("--version", action="store_true", help="the version and commit this checkout is at")
  top = parser.add_subparsers(dest="cmd", required=True)
  nested, needs_arguments = {}, {}

  for name, description in GROUPS.items():
    group_parser = top.add_parser(name, help=description)
    if name in DEFAULTS:   # bare `agent <group>` and `agent <group> --list` both show what is there
      group_parser.add_argument("--list", action="store_true", help="what this group holds (the default)")
      group_parser.set_defaults(function=DEFAULTS[name], _variadic=None)
    nested[name] = group_parser.add_subparsers(dest=f"{name}_cmd", required=name not in DEFAULTS)

  for registered in COMMANDS:
    if registered.group and registered.group not in nested: raise KeyError(f"command {registered.name!r} wants unknown group {registered.group!r}")
    subparser = (nested[registered.group] if registered.group else top).add_parser(registered.name, help=registered.help)
    for names, options in registered.args: subparser.add_argument(*names, **options)
    subparser.set_defaults(function=registered.function, _variadic=registered.variadic)

    if any(options.get("required") or not names[0].startswith("-") and options.get("nargs") not in ("?", "*")
           for names, options in registered.args):
      needs_arguments[tuple(filter(None, (registered.group, registered.name)))] = subparser

  typed = tuple(sys.argv[1:] if arguments is None else arguments)
  if typed in needs_arguments:
    needs_arguments[typed].print_help(sys.stderr)
    return 2

  args, extra = parser.parse_known_args(arguments)
  if extra:
    destination = getattr(args, "_variadic", None)
    if not destination or any(argument.startswith("-") for argument in extra):
      parser.error(f"unrecognized arguments: {' '.join(extra)}")
    setattr(args, destination, [*getattr(args, destination, []), *extra])
  return args.function(args)
