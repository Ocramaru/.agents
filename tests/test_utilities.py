"""`CliHelpers.ask` run through a real pseudo-terminal, since whether it asks and what it draws depend on there being one.

Author: Marco Cassar (@Ocramaru)
"""

import ast, os, re, shlex, sys

import pytest
from conftest import REPO, typed

ENVIRONMENT = os.environ | {"PYTHONPATH": str(REPO)}   # the checkout's code, whatever directory the test runs in
YES = 'CliHelpers.ask("Go on?", default=True)'
NO = 'CliHelpers.ask("Go on?", default=False)'
CHOICE = 'CliHelpers.ask("Which?", {"a": "first", "long": "second"}, default="a")'
FREE = 'CliHelpers.ask("Which?", {"a": "first", "b": "second"}, default="a", free=True)'
TEXT = 'CliHelpers.ask("Name?", default="dflt")'
EVERY_ROUTE = [(YES, True), (NO, False), (CHOICE, "a"), (FREE, "a"), (TEXT, "dflt"), ('CliHelpers.ask("Name?")', None)]
ROUTE_IDS = ["yes", "no", "choice", "free", "text", "no default"]


def program(call: str) -> list[str]:
  """A command that runs one `ask` and prints `RESULT` and what it returned."""
  return [sys.executable, "-c", f"from agentkit.cli.utilities import CliHelpers\nprint('RESULT', repr({call}))"]


def answered(call: str, answers: str, directory) -> tuple[object, str]:
  """What `call` returned with `answers` typed ahead on a terminal, and everything the terminal showed."""
  code, shown = typed(program(call), answers, ENVIRONMENT, directory)
  found = re.search(r"RESULT (.*?)\r?\n", shown)
  assert found, f"the question never finished (exit {code}):\n{shown}"
  return ast.literal_eval(found.group(1)), shown


@pytest.mark.parametrize("call, expected", EVERY_ROUTE, ids=ROUTE_IDS)
def test_with_no_terminal_ask_returns_the_default_and_prints_nothing(call, expected, tmp_path):
  """Neither end a terminal: the default comes back, and the only output is the line that prints it."""
  code, shown = typed(["sh", "-c", f"{shlex.join(program(call))} < /dev/null | cat"], "", ENVIRONMENT, tmp_path)
  assert code == 0 and shown == f"RESULT {expected!r}\r\n"


@pytest.mark.parametrize("redirects", ["| cat", "< /dev/null"], ids=["stdout piped", "stdin closed"])
def test_with_only_one_end_a_terminal_ask_still_returns_the_default_unasked(redirects, tmp_path):
  """Both ends must be terminals: a person at only one of them is not asked, and nothing waits for them."""
  code, shown = typed(["sh", "-c", f"{shlex.join(program(YES))} {redirects}"], "", ENVIRONMENT, tmp_path)
  assert code == 0 and shown == "RESULT True\r\n"


@pytest.mark.parametrize("default, answers, expected", [(True, "\n", True), (False, "\n", False), (True, "n\n", False), (False, "y\n", True), (False, "Y\n", True), (True, "N\n", False)],
                         ids=["enter keeps yes", "enter keeps no", "n over yes", "y over no", "capital y", "capital n"])
def test_a_bool_default_asks_yes_or_no_and_an_empty_answer_takes_the_default(default, answers, expected, tmp_path):
  result, shown = answered(f'CliHelpers.ask("Go on?", default={default})', answers, tmp_path)
  assert result is expected and f"Go on? [y/n] ({'y' if default else 'n'}):" in shown


def test_yes_or_no_asks_again_on_any_other_answer(tmp_path):
  result, shown = answered(NO, "maybe\n?\ny\n", tmp_path)
  assert result is True and shown.count("Please enter Y or N") == 2


@pytest.mark.parametrize("answers, expected", [("long\n", "long"), ("2\n", "long"), ("1\n", "a"), ("\n", "a"), ("  \n", "a"), ("a\n", "a")], ids=["name", "number", "first number", "enter", "spaces", "default name"])
def test_options_ask_for_one_by_name_or_number_and_an_empty_answer_takes_the_default(answers, expected, tmp_path):
  result, shown = answered(CHOICE, answers, tmp_path)
  assert result == expected and "Answer (a):" in shown


def test_options_are_listed_numbered_and_aligned_after_a_blank_line_and_before_the_prompt(tmp_path):
  _, shown = answered(CHOICE, "\x04", tmp_path)
  assert shown.startswith("\r\nWhich?\r\n  1  a     first\r\n  2  long  second\r\nAnswer (a): ")


def test_option_numbers_line_up_past_nine(tmp_path):
  _, shown = answered(f"CliHelpers.ask('Which?', {dict.fromkeys('abcdefghij', 'x')!r})", "\x04", tmp_path)
  assert "\r\n   1  a  x\r\n   2  b  x\r\n" in shown and "\r\n  10  j  x\r\n" in shown


def test_options_ask_again_on_an_unknown_name_or_number_and_stop_at_a_valid_one(tmp_path):
  result, shown = answered(CHOICE, "zzz\n3\n0\nlong\n", tmp_path)
  assert result == "long" and shown.count("Please choose a name or a number from the list.") == 3


def test_options_with_no_default_return_none_on_an_empty_answer(tmp_path):
  result, shown = answered('CliHelpers.ask("Which?", {"a": "first"})', "\n", tmp_path)
  assert result is None and "Answer:" in shown


@pytest.mark.parametrize("answers, expected", [("/some/dir\n", "/some/dir"), ("git@host:me/repo.git\n", "git@host:me/repo.git"), ("b\n", "b"), ("2\n", "b"), ("\n", "a")], ids=["a path", "a url", "a name", "a number", "enter"])
def test_free_options_return_any_other_answer_as_typed(answers, expected, tmp_path):
  result, _ = answered(FREE, answers, tmp_path)
  assert result == expected


@pytest.mark.parametrize("answers, expected", [("bob\n", "bob"), ("  bob  \n", "bob"), ("\n", "dflt"), ("  \n", "dflt")], ids=["typed", "trimmed", "enter", "spaces"])
def test_text_returns_what_was_typed_or_the_default(answers, expected, tmp_path):
  result, shown = answered(TEXT, answers, tmp_path)
  assert result == expected and "Name? (dflt):" in shown


def test_text_with_no_default_returns_none_on_an_empty_answer(tmp_path):
  result, shown = answered('CliHelpers.ask("Name?")', "\n", tmp_path)
  assert result is None and "Name?:" in shown


@pytest.mark.parametrize("call, expected", EVERY_ROUTE, ids=ROUTE_IDS)
def test_end_of_input_returns_the_default_and_ends_the_line(call, expected, tmp_path):
  result, shown = answered(call, "\x04", tmp_path)
  assert result == expected and ": \r\nRESULT" in shown


@pytest.mark.parametrize("call, expected", [(NO, False), (CHOICE, "a")], ids=["yes or no", "options"])
def test_end_of_input_after_an_answer_that_asked_again_still_returns_the_default(call, expected, tmp_path):
  result, _ = answered(call, "zzz\n\x04", tmp_path)
  assert result == expected


@pytest.mark.parametrize("call, shown_as", [
  ('CliHelpers.ask("Is [red]this[/red] :smile: ok?", default=True)', "Is [red]this[/red] :smile: ok? [y/n]"),
  ('CliHelpers.ask("Is [red]this[/red] :smile: ok?", default="[bold]")', "Is [red]this[/red] :smile: ok? ([bold]):"),
  ('CliHelpers.ask("Is [red]this[/red] :smile: ok?", {"[bold]": "see [link=x]there[/link] :smile:"}, default="[bold]")', "Is [red]this[/red] :smile: ok?\r\n  1  [bold]  see [link=x]there[/link] :smile:\r\n"),
], ids=["yes or no", "text", "options"])
def test_text_that_looks_like_markup_is_shown_as_it_is(call, shown_as, tmp_path):
  _, shown = answered(call, "\n", tmp_path)
  assert shown_as in shown
