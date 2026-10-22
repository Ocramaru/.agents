"""git.last_line gives the reason a finished command failed, and git.pull moves a clone to its upstream or says why it cannot.

The pulls run in real repositories in a temporary directory, with an identity and no hooksPath so no review runs.

Author: Marco Cassar (@Ocramaru)
"""

import subprocess
from pathlib import Path

import pytest

from agentkit import git


@pytest.fixture(autouse=True)
def identity(tmp_path, monkeypatch):
  """An identity for commits, and nothing else from this machine's git config."""
  (tmp_path / "gitconfig").write_text("[user]\n  name = T\n  email = t@t.io\n")
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))


def ok(where: Path, *args: str) -> subprocess.CompletedProcess:
  """Run git and fail the test if git fails, so a setup that did nothing cannot pass for one that worked."""
  result = git.run(where, *args)
  assert result.returncode == 0, result.stderr
  return result


def clone(parent: Path, bare: Path, name: str) -> Path:
  """A second checkout of `bare`, so one side pushes while the other pulls."""
  ok(parent, "clone", "-q", str(bare), str(parent / name))
  return parent / name


def push(repository: Path, message: str) -> None:
  """An empty commit pushed: history is all these tests need."""
  ok(repository, "commit", "--allow-empty", "-qm", message)
  ok(repository, "push", "-q", "-u", "origin", "main")


def finished(stderr: str | None = "", stdout: str | None = "") -> subprocess.CompletedProcess:
  """What a command that failed left behind."""
  return subprocess.CompletedProcess([], 1, stdout, stderr)


def test_the_reason_is_the_last_line_of_stderr_then_of_stdout_then_the_quiet_text():
  """stderr wins over stdout, the last line wins over the first, and a stream with nothing in it gives way to the next."""
  assert git.last_line(finished(stderr="warning: x\nfatal: no\n", stdout="out\n"), "quiet") == "fatal: no"
  assert git.last_line(finished(stdout="first\nsecond\n\n"), "quiet") == "second"
  assert git.last_line(finished(stderr="  \n\n", stdout="said this\n"), "quiet") == "said this"
  assert git.last_line(finished(), "quiet") == "quiet"
  assert git.last_line(finished(stderr=None, stdout=None), "quiet") == "quiet"


def test_pull_says_how_many_commits_came_and_when_none_did(tmp_path):
  """A pull reports each commit it brought, counted from HEAD before and after, and a pull of nothing is already current."""
  ok(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare := tmp_path / "remote.git"))
  push(theirs := clone(tmp_path, bare, "theirs"), "first")
  mine = clone(tmp_path, bare, "mine")
  assert git.pull(mine) == (True, "already current")

  push(theirs, "second")
  push(theirs, "third")
  assert git.pull(mine) == (True, "pulled 2 commits")
  assert ok(mine, "log", "-1", "--format=%s").stdout == "third\n"

  push(theirs, "fourth")
  assert git.pull(mine) == (True, "pulled 1 commit")
  assert git.pull(mine) == (True, "already current")


def test_pull_counts_every_commit_into_a_clone_that_had_none(tmp_path):
  """A clone of an empty repo has no HEAD to count from, so what arrives is counted from the start."""
  ok(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare := tmp_path / "remote.git"))
  mine, theirs = clone(tmp_path, bare, "mine"), clone(tmp_path, bare, "theirs")
  push(theirs, "first")
  push(theirs, "second")
  assert git.pull(mine) == (True, "pulled 2 commits")


def test_a_pull_that_would_have_to_merge_fails_with_gits_reason_and_changes_nothing(tmp_path):
  """Diverged histories are not merged: pull returns False with the last line git printed, and HEAD stays."""
  ok(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare := tmp_path / "remote.git"))
  push(theirs := clone(tmp_path, bare, "theirs"), "first")
  mine = clone(tmp_path, bare, "mine")
  ok(mine, "commit", "--allow-empty", "-qm", "here")
  push(theirs, "there")
  head = ok(mine, "rev-parse", "HEAD").stdout

  worked, reason = git.pull(mine)
  assert worked is False and reason == git.last_line(git.run(mine, "pull", "--ff-only", "-q"), "") and reason
  assert ok(mine, "rev-parse", "HEAD").stdout == head


def test_a_pull_outside_a_repo_fails_with_gits_reason(tmp_path):
  """Where git has nothing to pull it still says why, not a count."""
  (nowhere := tmp_path / "nowhere").mkdir()
  worked, reason = git.pull(nowhere)
  assert worked is False and "not a git repository" in reason
