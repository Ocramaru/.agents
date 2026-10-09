"""What the formatter guard must catch, and what it must never catch: naming a formatter is not running one.

Author: Marco Cassar (@Ocramaru)
"""

import pytest

from agentkit import profile
from agentkit.guard import formatter
from conftest import git

# the shipped runners over a list of our own, so the cases hold whichever formatters ship, on or off
SETTINGS = {**profile.section("guard"), "enabled": True, "formatters": ["black", "prettier", "ruff format", "ruff check --unsafe-fixes"], "targets": ["fmt", "format"]}


@pytest.mark.parametrize("command,blocked", [
  ("black src/", True),
  ("/usr/bin/black .", True),                       # an absolute path is the same command
  ("uv run ruff format .", True),                   # a runner, its word, then a pair
  ("python -m black .", True),
  ("FOO=1 sudo yarn prettier -w .", True),          # an assignment and runners stacked in front
  ("cd x && uvx ruff format", True),
  ("ruff check --fix --unsafe-fixes .", True),
  ("make fmt", True), ("npm run format", True), ("yarn format", True),
  ("ls&&black .", True), ("(black .)", True), ("ls\nblack .", True),     # an operator with no space around it still separates
  ("black --check . && black .", True),            # --check spares its own command, not the next
  ("pipx run black .", True), ("if true; then black .; fi", True), ("python3.12 -m black .", True),
  ("ruff check --fix .", False),                    # the standard says this one is fine
  ("git commit -m 'fix && black stuff'", False),    # naming one is not running one
  ("grep -r prettier .", False),
  ("black --check src/", False),                    # asking what it would do writes nothing
  ("echo 'unbalanced", False),                      # unreadable is not evidence, and a false block stops work
  ("make build", False), ("npm run test", False)])
def test_a_command_is_blocked_only_when_it_runs_a_rewriter(command, blocked, tmp_path):
  """A whole-file rewriter is blocked however it is spelled, and a command that only names one runs."""
  assert bool(formatter(command, SETTINGS, tmp_path)) is blocked, command


def precommit(tmp_path, hook_id):
  tmp_path.mkdir(parents=True, exist_ok=True)
  (tmp_path / ".git").mkdir()
  (tmp_path / ".pre-commit-config.yaml").write_text(f"repos:\n- repo: x\n  hooks:\n    - id: {hook_id}\n")
  return tmp_path


def test_pre_commit_is_judged_by_what_its_config_runs(tmp_path):
  """A pre-commit config that only lints is not a formatter."""
  lint, fmt = precommit(tmp_path / "a", "ruff-check"), precommit(tmp_path / "b", "ruff-format")
  assert formatter("pre-commit run --all-files", SETTINGS, lint) is None
  assert "ruff-format" in formatter("pre-commit run --all-files", SETTINGS, fmt)


def test_local_toml_and_then_a_repo_turn_it_off(tmp_path, monkeypatch):
  """A machine with no profile turns it on in local.toml; a fork whose upstream runs a formatter turns it off in its agents.toml."""
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")
  monkeypatch.setattr(profile, "DEFAULT", tmp_path / "no-profile")
  monkeypatch.delenv("AGENTS_PROFILE")
  (tmp_path / "local.toml").write_text('[guard]\nenabled = true\nformatters = ["mine"]\n')
  repo = git(tmp_path / "fork")
  assert formatter("mine .", profile.section("guard", repo), repo) == "mine"

  (repo / ".agents").mkdir()
  (repo / ".agents" / "agents.toml").write_text('[guard]\nenabled = false\n')
  assert formatter("mine .", settings := profile.section("guard", repo), repo) is None and settings["formatters"] == ["mine"]
