"""What every command shares, as static methods on one class, so a call site reads `CliHelpers.ask(...)`.

`rich` is imported inside the method that draws, since the CLI loads on every hook call and a hook never asks.

Author: Marco Cassar (@Ocramaru)
"""

import sys

from agentkit import backends, install
from agentkit.cli.out import fail, line


class CliHelpers:
  """The helpers; none of them holds state."""

  # -- ask: one way to put a question to the person, routed by what it is given -------------------

  @staticmethod
  def at_terminal() -> bool:
    """Whether stdin and stdout are both terminals, which is when a person can be asked."""
    return sys.stdin.isatty() and sys.stdout.isatty()

  @staticmethod
  def ask(question: str, options: dict[str, str] | None = None, default: bool | str | None = None, free: bool = False) -> bool | str | None:
    """Ask at a terminal and return the answer, or `default` anywhere else and at end of input: yes or no for a bool `default`, else one of `options` (name to description) by name or number, with any other answer returned as typed when `free`, else text."""
    if not CliHelpers.at_terminal(): return default

    from rich.console import Console
    from rich.prompt import Confirm, Prompt
    from rich.text import Text

    console = Console(highlight=False, soft_wrap=True)
    console.print()

    try:
      if isinstance(default, bool): return Confirm.ask(Text(question), default=default, console=console)
      if not options: return Prompt.ask(Text(question), default=default, show_default=bool(default), console=console) or default

      numbered = {str(number): name for number, name in enumerate(options, 1)}
      console.print(Text(question))
      for number, name in numbered.items(): console.print(Text.assemble((f"  {number:>{len(str(len(options)))}}", "dim"), "  ", (name.ljust(max(map(len, options))), "bold cyan"), "  ", options[name]))

      while True:
        answer = Prompt.ask("Answer", default=default, show_default=bool(default), console=console)
        if not answer: return default
        if answer in options: return answer
        if answer in numbered: return numbered[answer]
        if free: return answer
        console.print("Please choose a name or a number from the list.", style="red")
    except EOFError:
      console.print()
      return default

  @staticmethod
  def ask_backend() -> str:
    """Ask which backend this machine has, each listed as here or how to install it, and record the answer; `""` when none is chosen or there is no terminal."""
    if not CliHelpers.at_terminal(): return ""   # the default below is the first one found, which only a person's answer may record
    known = backends.load_backends()[0]
    found = {name: backend.here() for name, backend in known.items()}
    answer = CliHelpers.ask("Reviews run on a model. Which of these does this machine have?", {name: f"{known[name].spec.get('label', name)} ({said})" for name, (_, said) in found.items()}, default=next((name for name, (here, _) in found.items() if here), None))
    if not answer: return ""
    line(f"  set   default = {answer} in {install.home(backends.choose(answer))}")
    return answer

  @staticmethod
  def ensure_backend(named: str | None) -> int:
    """0 when a review has a backend: one named, the default, or one chosen now at a terminal; otherwise say how to set one and return 2."""
    if named or backends.load_backends()[1]: return 0
    if CliHelpers.ask("No default backend is set, so a review has nowhere to run. Set one now?", default=True) and CliHelpers.ask_backend(): return 0   # with no terminal the first answers yes and the second chooses nothing
    return fail(f"{backends.UNSET}: {backends.unset()}", 2)
