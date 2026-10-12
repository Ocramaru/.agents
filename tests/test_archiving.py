"""A finished task deleted out of `todo.md` instead of moved to `todo.archive.md` is reported, never blocked.

Author: Marco Cassar (@Ocramaru)
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import agent, git

from agentkit import notes

BEFORE = """---
name: todo
kind: todo
---

# TODO

- [ ] Prove the codex backend end to end
- [ ] `agents.py` has no tests, and `review.discover` still has none
"""


@pytest.fixture
def todo(tmp_path) -> Path:
  git(tmp_path)
  (tmp_path / ".agents").mkdir()
  (tmp_path / ".agents" / "todo.md").write_text(BEFORE)
  return tmp_path / ".agents" / "todo.md"


def without(text: str, phrase: str) -> str:
  return "\n".join(line for line in text.splitlines() if phrase not in line) + "\n"


@pytest.mark.parametrize("archive, entry, phrase, reported", [
  ("todo.archive.md", "Wired up the reviewer (see: Prove the codex backend end to end)", "codex", True),   # mentioned is not moved
  ("todo.archive.md", "agents.py has no tests, and review.discover still has none. Done in dad6526.", "agents.py", False),   # backticks normalised away
  ("todo.archive/01-2026.md", "Prove the codex backend end to end. `abc1234`.", "codex", False),   # a split archive counts too
])
def test_a_removed_task_is_reported_until_the_archive_lists_it(todo, archive, entry, phrase, reported):
  """A task removed from todo.md is reported unless an archive, whole or split, has a task starting the same way, markdown aside."""
  (target := todo.parent / archive).parent.mkdir(exist_ok=True)
  target.write_text(f"# Done\n\n- [x] {entry}\n")
  said = notes.abandoned(todo, BEFORE, without(BEFORE, phrase))
  assert ("removes 1 task" in said and "todo.archive.md" in said and phrase in said) == reported


def test_only_todo_and_its_parts_are_held_to_it(tmp_path):
  """A split todo part is held like todo.md; tidying todo.archive.md is not abandoning."""
  git(tmp_path)

  for name, held in (("todo/01-next.md", True), ("todo.archive.md", False)):
    (path := tmp_path / ".agents" / name).parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BEFORE)
    assert bool(notes.abandoned(path, BEFORE, without(BEFORE, "codex"))) == held


def test_the_warning_arrives_every_time_and_the_person_sees_it(todo):
  """The warning is about the edit, so session dedupe never swallows it, and the hook names it in systemMessage."""
  tool_input = {"file_path": str(todo), "old_string": BEFORE, "new_string": without(BEFORE, "codex")}
  session = f"archive-{uuid.uuid4().hex}"        # stamps outlive a run, and tmp dir names repeat
  inject_edit = lambda: agent(["inject", str(todo), "--session", session, "--edit"], cwd=todo.parent.parent, stdin=json.dumps({"tool_input": tool_input}))
  first, again = inject_edit(), inject_edit()
  assert "removes 1 task" in first.stdout and "--- agent-notes" in first.stdout   # notes too, once
  assert "removes 1 task" in again.stdout and "--- agent-notes" not in again.stdout   # said again, while the standards stay deduped

  output = json.loads(subprocess.run(["bash", str(Path(__file__).resolve().parent.parent / "hooks" / "inject.sh")], input=json.dumps({"session_id": f"archive-{uuid.uuid4().hex}", "tool_name": "Edit", "tool_input": tool_input}), capture_output=True, check=True, text=True, cwd=todo.parent.parent).stdout)
  assert "a task leaving todo.md unarchived" in output["systemMessage"] and "removes 1 task" in output["hookSpecificOutput"]["additionalContext"]
