"""Noticing a finished task deleted out of `todo.md` instead of moved to `todo.archive.md`.

The convention says archive rather than delete, because a closed task is the cheapest record of why
the code looks the way it does. Nothing enforced it, and the session least likely to stop and
archive is the one that just did the work -- so this rides the hook that already runs on every edit.

It advises and never blocks: rewording a task, merging two, and dropping one that turned out to be
wrong are all ordinary, so the test that matters most is that a real move stays quiet.

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
- [ ] Delete `skills/`, once nothing reads it
"""


@pytest.fixture
def todo(tmp_path) -> Path:
  git(tmp_path)
  d = tmp_path / ".agents"
  d.mkdir()
  f = d / "todo.md"
  f.write_text(BEFORE)
  return f


def without(text: str, phrase: str) -> str:
  return "\n".join(line for line in text.splitlines() if phrase not in line) + "\n"


def test_a_deleted_task_is_reported_until_the_archive_holds_it(todo):
  """A task removed from todo.md is reported unless an archive, whole or split, has a task starting the same way, markdown aside."""
  after = BEFORE.replace("- [ ] Delete `skills/`, once nothing reads it",
                         "- [ ] Delete `skills/`, once nothing reads it (2 MB, gitignored)")
  assert notes.abandoned(todo, BEFORE, after) == ""        # annotated in place, still there
  keep = BEFORE.replace("# TODO", "# TODO\n\nSome prose that is not a task.")
  assert notes.abandoned(todo, BEFORE, keep) == ""          # nothing removed, so nothing to say

  said = notes.abandoned(todo, BEFORE, without(BEFORE, "codex"))
  assert "removes 1 task" in said and "todo.archive.md" in said and said.endswith("  - Prove the codex backend end to end")

  archive = todo.parent / "todo.archive.md"
  archive.write_text("# Done\n\n- [x] Wired up the reviewer, which will help prove the codex backend end to end later\n")
  assert notes.abandoned(todo, BEFORE, without(BEFORE, "codex")).endswith("  - Prove the codex backend end to end")   # mentioned is not moved

  archive.write_text("# Done\n\n- [x] Prove the codex backend end to end, through a real resume. `abc1234`.\n"
                     "- [x] agents.py has no tests, and review.discover still has none. Done in dad6526.\n")
  assert notes.abandoned(todo, BEFORE, without(BEFORE, "codex")) == ""
  assert notes.abandoned(todo, BEFORE, without(BEFORE, "agents.py")) == ""   # backticks normalised away

  archive.unlink()
  part = todo.parent / "todo.archive" / "01-2026.md"
  part.parent.mkdir()
  part.write_text("# 2026\n\n- [x] Prove the codex backend end to end. `abc1234`.\n")
  assert notes.abandoned(todo, BEFORE, without(BEFORE, "codex")) == ""


def test_only_todo_and_its_parts_are_held_to_it(tmp_path):
  """Tidying todo.archive.md is not abandoning tasks; a split todo part is held like todo.md."""
  git(tmp_path)
  part = tmp_path / ".agents" / "todo" / "01-next.md"
  part.parent.mkdir(parents=True)
  part.write_text(BEFORE)
  assert notes.abandoned(part, BEFORE, without(BEFORE, "codex")).endswith("  - Prove the codex backend end to end")

  f = tmp_path / ".agents" / "todo.archive.md"
  f.write_text(BEFORE)
  assert notes.abandoned(f, BEFORE, without(BEFORE, "codex")) == ""


def test_the_warning_arrives_every_time_and_the_person_sees_it(todo):
  """The warning is about the edit, so session dedupe never swallows it, and the hook names it in systemMessage."""
  session = f"archive-{uuid.uuid4().hex}"        # stamps outlive a run, and tmp dir names repeat
  tool_input = {"file_path": str(todo), "old_string": BEFORE, "new_string": without(BEFORE, "codex")}
  inject_edit = lambda: agent(["inject", str(todo), "--session", session, "--edit"], cwd=todo.parent.parent,
                              stdin=json.dumps({"tool_input": tool_input}))

  first = inject_edit()
  assert "removes 1 task" in first.stdout and "--- agent-notes" in first.stdout   # notes too, once
  again = inject_edit()
  assert "removes 1 task" in again.stdout           # said again
  assert "--- agent-notes" not in again.stdout      # while the standards stay deduped

  payload = {"session_id": f"archive-{uuid.uuid4().hex}", "tool_name": "Edit", "tool_input": tool_input}
  out = subprocess.run(["bash", str(Path(__file__).resolve().parent.parent / "hooks" / "inject.sh")],
                       input=json.dumps(payload), capture_output=True, check=True, text=True,
                       cwd=todo.parent.parent).stdout
  assert "a task leaving todo.md unarchived" in json.loads(out)["systemMessage"]
