"""`CliHelpers.ask` run through a real pseudo-terminal, since whether it asks and what it draws depend on there being one, then the commands that lean on it: `install --changes`, `update` and a review with no backend."""

import argparse
import ast
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import REPO, typed

from agentkit import backends, git, hub, install, profile, words
from agentkit.cli import setup
from agentkit.cli.utilities import CliHelpers

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


LINES = ["hooks", "  copy  2 files into .agents", "  ok    .agents -> /x", "  FAIL  gh said no", "", "Done."]


def test_changes_keeps_the_lines_that_changed_something_or_failed_and_a_failed_step_keeps_all(capsys):
  """Plain, every line prints; under changes only those whose first word is in words.CHANGED or FAIL, unless the step failed."""
  assert setup.show(False, *LINES) == 0
  assert capsys.readouterr().out == "\n".join(LINES) + "\n"
  assert setup.show(True, *LINES) == 0
  assert capsys.readouterr().out == "  copy  2 files into .agents\n  FAIL  gh said no\n"
  assert setup.show(True, *LINES, failed=True) == 0
  assert capsys.readouterr().out == "\n".join(LINES) + "\n"


def test_every_status_word_says_whether_its_line_changed_something():
  """Each word `words.status` is given anywhere in agentkit is a literal, or a choice of literals, in words.CHANGED or words.UNCHANGED, so `install --changes` knows whether to keep its line; no word is in both, and none is wider than the column it is padded to."""
  given = lambda node: [word for branch in (node.body, node.orelse) for word in given(branch)] if isinstance(node, ast.IfExp) else [node.value if isinstance(node, ast.Constant) else ast.unparse(node)]
  used = {(path.name, word) for path in (REPO / "agentkit").rglob("*.py") for call in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
          if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "status" and isinstance(call.func.value, ast.Name) and call.func.value.id == "words"
          for word in given(call.args[0])}
  assert used and {(name, word) for name, word in used if word not in (*words.CHANGED, *words.UNCHANGED)} == set()
  assert set(words.CHANGED).isdisjoint(words.UNCHANGED)
  assert [word for word in (*words.CHANGED, *words.UNCHANGED) if len(word) >= words.STATUS] == []


def test_install_changes_prints_only_what_changed_and_still_does_all_the_work(fresh, machine):
  """The first install under --changes prints its copies, links, writes and pointers and no other line; a second prints nothing, an edited copy the backup and the copy, and --backend the default it set."""
  home = Path(machine["HOME"])
  (home / ".claude").mkdir(parents=True)
  first = {text.split()[0] for text in fresh(["install", "--changes"]).stdout.splitlines()}
  assert first == {"copy", "link", "wrote", "point"}

  everything = fresh(["install"]).stdout   # the lines --changes left out were there to leave out
  assert "  ok    " in everything and "Done. Restart the agent" in everything
  assert fresh(["install", "--changes"]).stdout == ""

  (home / ".agents" / "hooks" / "inject.sh").write_text("stale\n")
  assert fresh(["install", "--changes"]).stdout.splitlines() == ["  saved .agents/hooks/inject.sh.bak, which the last install did not leave there", "  copy  1 file into .agents"]

  assert fresh(["install", "--changes", "--backend", "codex"]).stdout.splitlines() == ["  set   default = codex in .agents/local.toml"]
  assert tomllib.loads((home / ".agents" / "local.toml").read_text())["backends"]["default"] == "codex"


def test_install_changes_prints_the_whole_report_of_an_install_that_fails(fresh, machine):
  """A failing install under --changes still says why, since the caller reads the last line of what it printed."""
  (Path(machine["HOME"]) / ".agents" / "agentkit").mkdir(parents=True)   # ~/.agents looks like a clone, which an install refuses
  failed = fresh(["install", "--changes"], expect=1).stdout
  assert failed.startswith("cannot install: ") and "is a clone of .agents" in failed


def test_install_changes_still_shows_a_publish_that_failed_and_hides_the_hints_after_it(installed, machine, tmp_path):
  """Given a yes at a terminal, a gh that cannot make the repo leaves its FAIL line under --changes, and the push commands, the hints and the closing line are left out."""
  fake = tmp_path / "fake"
  fake.mkdir()
  (fake / "gh").write_text('#!/usr/bin/env bash\ncase "$1 $2" in\n  "api user") echo tester ;;\n  "repo create") echo boom >&2; exit 1 ;;\n  *) exit 1 ;;\nesac\n')
  (fake / "gh").chmod(0o755)
  (Path(machine["HOME"]) / ".claude").mkdir(parents=True)
  machine["PATH"] = f"{fake}{os.pathsep}{machine['PATH']}"
  command = [str(installed / "agent"), "install", "--profile", "new", "--backend", "claude"]

  code, shown = typed(command, "y\n", machine, tmp_path)
  assert code == 0 and "FAIL  boom" in shown and "Push your profile somewhere private" in shown and "Done. Restart the agent" in shown   # plain, the same run says everything

  code, shown = typed([*command, "--changes"], "y\n", machine, tmp_path)
  assert code == 0 and "Make tester/.agents.profile on GitHub" in shown and "FAIL  boom" in shown
  assert "Push your profile somewhere private" not in shown and "Done. Restart the agent" not in shown


@pytest.mark.parametrize("an_install, pulls, code, said", [
  (False, (True, "pulled 2 commits"), 0, ["ok    .agents: pulled 2 commits  (HUB)", "skip  profile: none set"]),
  (False, (True, "already current"), 0, ["ok    .agents: already current  (HUB)", "skip  profile: none set"]),
  (False, (False, "cannot pull"), 1, ["FAIL  .agents: cannot pull  (HUB)", "skip  profile: none set"]),
  (True, None, 1, ["FAIL  .agents: uv said nothing", "skip  profile: none set"]),
], ids=["pulled", "current", "failed", "installed"])
def test_update_prints_what_the_upgrade_and_each_pull_said_and_fails_if_any_did(an_install, pulls, code, said, tmp_path, monkeypatch, capsys):
  """An install is upgraded through install.upgrade and a clone pulled through git.pull; each line reads `ok` or `FAIL`, then the name, what happened and where, and any failure is exit 1."""
  hub_dir = tmp_path / "hub"
  (hub_dir / ".git").mkdir(parents=True)
  monkeypatch.setattr(hub, "INSTALLED", an_install)
  monkeypatch.setattr(hub, "BUNDLED", hub_dir)
  monkeypatch.setattr(profile, "path", lambda: None)
  monkeypatch.setattr(install, "upgrade", lambda: (1, ["FAIL  .agents: uv said nothing"]))
  monkeypatch.setattr(git, "pull", lambda where: pulls)
  monkeypatch.setattr(backends, "load_backends", lambda: ({"alpha": None}, "alpha"))
  assert setup.cmd_update(None) == code
  assert capsys.readouterr().out.splitlines() == [text.replace("HUB", str(hub_dir)) for text in said]


def test_update_skips_a_hub_or_profile_that_is_not_a_git_repo(tmp_path, monkeypatch, capsys):
  """A clone or profile with no .git is skipped by name, and skipping is not failing; with no default backend it says headless reviews cannot run, and how to set one, without failing."""
  (tmp_path / "not-git").mkdir()
  monkeypatch.setattr(hub, "INSTALLED", False)
  monkeypatch.setattr(hub, "BUNDLED", tmp_path / "not-git")
  monkeypatch.setattr(profile, "path", lambda: tmp_path / "also-not")
  monkeypatch.setattr(backends, "load_backends", lambda: ({"alpha": None, "beta": None}, ""))
  assert setup.cmd_update(None) == 0
  assert capsys.readouterr().out.splitlines() == ["skip  .agents: not a git repo", "skip  profile: not a git repo", f"note  {backends.HEADLESS}: `agent install --backend <alpha|beta>`"]


def test_update_says_a_config_that_does_not_parse_leaves_the_default_backend_unknown(tmp_path, monkeypatch, capsys):
  """A hand-edited config that does not parse is a note at the end of update, not a traceback, and the pulls before it still count."""
  (tmp_path / "not-git").mkdir()
  (broken := tmp_path / "config.toml").write_text("[backends\ndefault = ")
  monkeypatch.setattr(hub, "INSTALLED", False)
  monkeypatch.setattr(hub, "BUNDLED", tmp_path / "not-git")
  monkeypatch.setattr(hub, "CONFIG", broken)
  monkeypatch.setattr(profile, "path", lambda: None)
  assert setup.cmd_update(None) == 0
  said = capsys.readouterr().out.splitlines()[-1]
  assert said.startswith("note  a config.toml or local.toml does not parse, so the backends cannot be read: ") and said.endswith("; `agent doctor` names the file")


@pytest.mark.parametrize("backend", ["claude", None], ids=["named", "read after the install"])
def test_install_fails_in_one_line_on_a_config_that_does_not_parse(backend, tmp_path, monkeypatch, capsys):
  """A hand-edited config that does not parse fails install with one line naming it and exit 1, whether the backend is checked before the install or read after it."""
  (broken := tmp_path / "config.toml").write_text("[backends\ndefault = ")
  monkeypatch.setattr(hub, "CONFIG", broken)
  monkeypatch.setattr(install, "keep", lambda profile=None: (0, ""))
  monkeypatch.setattr(install, "run", lambda targets, create=False, profile=None: (0, []))
  monkeypatch.setattr(profile, "unasked", lambda: False)
  assert setup.cmd_install(argparse.Namespace(backend=backend, profile=None, targets=[], all=False, changes=False)) == 1
  said = capsys.readouterr().err.strip().splitlines()
  assert len(said) == 1 and said[0].startswith("a config.toml or local.toml does not parse, so the backends cannot be read: ") and said[0].endswith("; `agent doctor` names the file")


def test_a_review_with_no_default_backend_fails_naming_what_is_unset_and_how_to_set_one(monkeypatch, capsys):
  """Unasked and with no backend named or set, the failure is the library's UNSET, then its advice, and exit 2; a named or default backend passes."""
  monkeypatch.setattr(backends, "load_backends", lambda: ({"alpha": None, "beta": None}, ""))
  assert CliHelpers.ensure_backend(None) == 2
  assert capsys.readouterr().err.strip() == f"{backends.UNSET}: `agent install --backend <alpha|beta>`, or run this at a terminal to be asked"
  assert CliHelpers.ensure_backend("alpha") == 0

  monkeypatch.setattr(backends, "load_backends", lambda: ({"alpha": None}, "alpha"))
  assert CliHelpers.ensure_backend(None) == 0
