"""The gate remembers an empty `inject` answer per session and path, and never gates an answer that can still change.

Author: Marco Cassar (@Ocramaru)
"""

import json, os, subprocess, uuid
from pathlib import Path

import pytest
from conftest import git, note

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
TODO = "---\nname: todo\nkind: todo\n---\n\n# TODO\n\n- [ ] Something still open\n- [ ] And another\n"


@pytest.fixture
def repo(tmp_path):
  """A repo with notes, so files in it are governed and the chain resolves."""
  note(git(tmp_path), "# r")
  (tmp_path / ".agents" / "todo.md").write_text(TODO)
  (tmp_path / "mod.py").write_text("x = 1\n")
  return tmp_path


class Hook:
  """The real hook, fired as Claude Code fires it, with ~/.agents pointing at this checkout and every stamp and log under tmp_path."""

  def __init__(self, tmp_path: Path):
    self.session, self.log = f"gate-{uuid.uuid4().hex}", tmp_path / "hooks.log"

    (tmp_path / "home").mkdir(exist_ok=True)
    if not (tmp_path / "home" / ".agents").exists(): (tmp_path / "home" / ".agents").symlink_to(HOOKS.parent)

    self.environment = {**os.environ, "AGENTS_HOOK_LOG": str(self.log), "TMPDIR": str(tmp_path), "HOME": str(tmp_path / "home"), "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv")}

  def run(self, path: Path, old: str = "a", new: str = "b") -> subprocess.CompletedProcess:
    payload = {"session_id": self.session, "tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}
    return subprocess.run(["bash", str(HOOKS / "inject.sh")], input=json.dumps(payload), text=True, capture_output=True, check=False, env=self.environment)

  def fire(self, path: Path, old: str = "a", new: str = "b") -> str:
    """Run the hook once and return the status it logged."""
    logged = len(self.statuses())
    assert self.run(path, old, new).returncode == 0
    assert len(self.statuses()) == logged + 1, "the hook logged nothing for this call"
    return self.statuses()[-1]

  def statuses(self) -> list[str]:
    rows = self.log.read_text(errors="replace").splitlines() if self.log.is_file() else []
    return [row.split("\t")[3].split()[0] for row in rows if len(row.split("\t")) > 3]


def test_only_an_answer_that_cannot_change_is_gated(repo, tmp_path, tmp_path_factory):
  """An empty answer is asked once and then gated, per session; a note, or an answer whose stamp cannot be written, is not."""
  hook, mod, todo = Hook(tmp_path), repo / "mod.py", repo / ".agents" / "todo.md"
  loose = tmp_path_factory.mktemp("loose") / "loose.txt"   # no .agents above it, so nothing governs it
  loose.write_text("x\n")
  assert [hook.fire(loose) for _ in range(3)] == ["none", "gated", "gated"]

  notice = json.loads((ran := hook.run(mod)).stdout)
  assert ran.returncode == 0
  assert notice["systemMessage"].startswith(".agents loaded") and "standards, 1 note for mod.py (" in notice["systemMessage"]
  assert notice["hookSpecificOutput"]["additionalContext"]
  assert [hook.statuses()[-1], *(hook.fire(mod) for _ in range(2))] == ["sent", "quiet", "gated"]
  assert Hook(tmp_path).fire(mod) == "sent"   # a different session knows nothing

  assert [hook.fire(todo) for _ in range(3)] == ["sent", "quiet", "quiet"]   # a note is never gated,
  assert hook.fire(todo, TODO, TODO.replace("- [ ] Something still open\n", "")) == "sent"   # so a task it drops is still named

  stuck = Hook(tmp_path)
  (tmp_path / f"agents-{stuck.session}").mkdir()
  (tmp_path / f"agents-{stuck.session}" / "gate").write_text("a file where the gate's directory goes\n")
  assert [stuck.fire(mod) for _ in range(3)] == ["sent", "quiet", "quiet"]   # a gate that cannot write is only a slow hook


def test_a_review_landing_or_compaction_reopens_the_gate(repo, tmp_path):
  """The gate reopens when the ledger it names changes, and when forget.sh clears the session."""
  hook, mod, ledger = Hook(tmp_path), repo / "mod.py", repo / ".agents" / ".reviews" / "reviews.duckdb"
  ledger.parent.mkdir(parents=True)
  ledger.write_text("")   # only its mtime is read

  assert [hook.fire(mod) for _ in range(3)] == ["sent", "quiet", "gated"]
  ledger.touch()
  assert hook.fire(mod) == "quiet"

  subprocess.run(["bash", str(HOOKS / "forget.sh")], input=json.dumps({"session_id": hook.session}), text=True, capture_output=True, check=True, env=hook.environment)
  assert hook.fire(mod) == "sent"   # the standards go back in
