"""Not asking a question whose answer has not changed.

Most `inject` calls answer "already in context" or "nothing governs this file", and each paid a
`uv run` to say so; the numbers are in learned.md. The gate remembers the empty answer per session and per path, in shell, with no fork: `-nt` is a
builtin. What it must never do is gate something whose answer can still change, so that is most of
what is tested here.

Author: Marco Cassar (@Ocramaru)
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import git


HOOKS = Path(__file__).resolve().parent.parent / "hooks"
TODO = "---\nname: todo\nkind: todo\n---\n\n# TODO\n\n- [ ] Something still open\n- [ ] And another\n"


@pytest.fixture
def repo(tmp_path):
  """A repo with a note, so files in it are governed and the chain resolves."""
  git(tmp_path)
  (tmp_path / ".agents").mkdir()
  (tmp_path / ".agents" / "context.md").write_text("---\nname: context\nkind: context\n---\n\n# r\n")
  (tmp_path / ".agents" / "todo.md").write_text(TODO)
  (tmp_path / "mod.py").write_text("x = 1\n")
  return tmp_path


class Hook:
  """The real hook, fired the way Claude Code fires it, its log and every stamp kept under tmp_path."""

  def __init__(self, tmp_path: Path):
    self.session = f"gate-{uuid.uuid4().hex}"
    self.log = tmp_path / "hooks.log"
    self.env = {**os.environ, "AGENTS_HOOK_LOG": str(self.log), "TMPDIR": str(tmp_path)}

  def run(self, path: Path, old: str = "a", new: str = "b", **env) -> subprocess.CompletedProcess:
    payload = {"session_id": self.session, "tool_name": "Edit",
               "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}
    return subprocess.run(["bash", str(HOOKS / "inject.sh")], input=json.dumps(payload), text=True,
                          capture_output=True, check=False, env={**self.env, **env})

  def fire(self, path: Path, old: str = "a", new: str = "b") -> str:
    assert self.run(path, old, new).returncode == 0
    return self.statuses()[-1]

  def warm(self, path: Path) -> None:
    """Fire until the answer is remembered: the state every test of reopening starts from."""
    self.fire(path)
    self.fire(path)
    assert self.fire(path) == "gated"

  def statuses(self) -> list[str]:
    rows = self.log.read_text(errors="replace").splitlines() if self.log.is_file() else []
    return [r.split("\t")[3].split()[0] for r in rows if len(r.split("\t")) > 3]


def test_only_an_answer_that_cannot_change_is_gated(repo, tmp_path, tmp_path_factory):
  """An empty answer is asked once and then gated, per session; a note is never gated."""
  h = Hook(tmp_path)
  loose = tmp_path_factory.mktemp("loose") / "loose.txt"   # no .agents above it, so nothing governs it
  loose.write_text("x\n")
  assert [h.fire(loose) for _ in range(3)] == ["none", "gated", "gated"]
  assert [h.fire(repo / "mod.py") for _ in range(3)] == ["sent", "quiet", "gated"]
  assert Hook(tmp_path).fire(repo / "mod.py") == "sent"   # a different session knows nothing

  todo = repo / ".agents" / "todo.md"
  dropped = TODO.replace("- [ ] Something still open\n", "")
  assert [h.fire(todo, TODO, dropped) for _ in range(4)] == ["sent"] * 4


def test_a_review_landing_or_compaction_reopens_the_gate(repo, tmp_path):
  """The gate reopens when the ledger it names changes, and when forget.sh clears the session."""
  h = Hook(tmp_path)
  ledger = repo / ".agents" / ".reviews" / "reviews.duckdb"
  ledger.parent.mkdir(parents=True)
  ledger.write_text("")                           # only its mtime is read, never its contents
  h.warm(repo / "mod.py")
  subprocess.run(["touch", str(ledger)], check=True)
  assert h.fire(repo / "mod.py") != "gated"

  h.warm(repo / "mod.py")
  subprocess.run(["bash", str(HOOKS / "forget.sh")], input=json.dumps({"session_id": h.session}),
                 text=True, capture_output=True, check=True, env=h.env)
  assert h.fire(repo / "mod.py") == "sent"        # the standards go back in


def test_a_gate_that_cannot_write_is_only_a_slow_hook(repo, tmp_path):
  """A gate that fails to write its stamp never fails the edit."""
  h = Hook(tmp_path)
  blocker = tmp_path / f"agents-{h.session}" / "gate"     # a file where the gate's directory goes
  blocker.parent.mkdir(parents=True)
  blocker.write_text("not a directory\n")
  assert h.run(repo / "mod.py").returncode == 0
  assert h.run(repo / "mod.py").returncode == 0 and h.statuses() == ["sent", "quiet"]
