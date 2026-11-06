"""The gate remembers an empty `inject` answer per session and path, and never gates an answer that can still change."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import checkout_home, git, note

from agentkit import reviews

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
    self.environment = checkout_home(tmp_path, AGENTS_HOOK_LOG=str(self.log))

  def run(self, path: Path, old: str = "a", new: str = "b") -> subprocess.CompletedProcess:
    payload = {"session_id": self.session, "tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}
    return subprocess.run(["bash", str(HOOKS / "inject.sh")], input=json.dumps(payload), text=True, capture_output=True, check=False, env=self.environment)

  def fire(self, path: Path, old: str = "a", new: str = "b") -> str:
    """Run the hook once and return the status it logged."""
    logged = len(self.statuses())
    assert self.run(path, old, new).returncode == 0
    assert len(self.statuses()) == logged + 1, "the hook did not log exactly one row for this call"
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
  """The gate reopens when the reviews file it names changes, and when forget.sh clears the session."""
  pytest.importorskip("duckdb")
  hook, mod, reviews_file = Hook(tmp_path), repo / "mod.py", reviews.path(repo)
  reviews.connect(repo).close()   # empty, but readable: the hook reads findings from it, and the gate its time

  assert [hook.fire(mod) for _ in range(3)] == ["sent", "quiet", "gated"]
  reviews_file.touch()
  assert hook.fire(mod) == "quiet"

  subprocess.run(["bash", str(HOOKS / "forget.sh")], input=json.dumps({"session_id": hook.session}), text=True, capture_output=True, check=True, env=hook.environment)
  assert hook.fire(mod) == "sent"   # the standards go back in


def test_the_notes_a_session_starts_with_are_not_sent_again_by_an_edit_until_compaction_clears_them(repo, tmp_path):
  """The real SessionStart hook stamps where inject.sh looks, so the first edit carries standards and no notes; forget.sh clears both, and the next start sends the notes again."""
  hook = Hook(tmp_path)
  start = lambda source="startup": json.loads(subprocess.run(["bash", str(HOOKS / "session-start.sh")], input=json.dumps({"session_id": hook.session, "cwd": str(repo), "source": source}), text=True, capture_output=True, check=True, env=hook.environment).stdout or "{}")
  assert "--- ./context.md ---" in start()["hookSpecificOutput"]["additionalContext"]
  edit = json.loads(hook.run(repo / "mod.py").stdout)["hookSpecificOutput"]["additionalContext"]
  assert "--- python" in edit and "Notes from .agents" not in edit
  assert start("resume") == {}   # a resume: everything is in context already

  subprocess.run(["bash", str(HOOKS / "forget.sh")], input=json.dumps({"session_id": hook.session}), text=True, capture_output=True, check=True, env=hook.environment)
  assert "--- ./context.md ---" in start()["hookSpecificOutput"]["additionalContext"]


def test_a_note_or_a_standard_added_mid_session_reopens_the_gate(tmp_path):
  """An empty answer stays gated only until a `.agents` appears on the file's path or a standard lands in a folder the library reads."""
  hook, loose, data = Hook(tmp_path), git(tmp_path / "bare") / "src" / "notes.txt", tmp_path / "bare" / "data.zz"
  loose.parent.mkdir()
  loose.write_text("x\n")
  data.write_text("x\n")
  assert [hook.fire(loose) for _ in range(2)] == ["none", "gated"]
  note(tmp_path / "bare", "# bare")   # a .agents at the repo root, two directories above the file
  assert hook.fire(loose) == "sent"

  (tmp_path / "bare" / ".agents" / "standards").mkdir()   # before the answer, so only a file landing in it can reopen it, not the .agents it is made in
  assert [hook.fire(data) for _ in range(2)] == ["quiet", "gated"]   # the notes went with notes.txt, and nothing governs *.zz
  (tmp_path / "bare" / ".agents" / "standards" / "zz.md").write_text("---\nname: zz\napplies: *.zz\n---\n\nzz rules\n")
  assert hook.fire(data) == "sent"

  profile, other = tmp_path / "profile" / "standards", git(tmp_path / "other") / "data.yy"   # a library folder, off every file's path
  profile.mkdir(parents=True)
  other.write_text("x\n")
  hook.environment["AGENTS_PROFILE"] = str(profile.parent)
  assert [hook.fire(other) for _ in range(2)] == ["none", "gated"]
  (profile / "yy.md").write_text("---\nname: yy\napplies: *.yy\n---\n\nyy rules\n")
  assert hook.fire(other) == "sent"


def test_the_gate_reopens_on_the_reviews_at_the_repo_root_under_a_package_level_agents(tmp_path):
  """Reviews live at the git root's .agents wherever the nearest notes are, so a review landing there reopens a file in a package with its own .agents."""
  pytest.importorskip("duckdb")
  hook, mod = Hook(tmp_path), git(tmp_path / "mono") / "pkg" / "mod.py"
  note(tmp_path / "mono" / "pkg", "# pkg")
  mod.write_text("x = 1\n")
  reviews.connect(tmp_path / "mono").close()
  assert reviews.path(tmp_path / "mono").parent.parent == tmp_path / "mono" / ".agents"

  assert [hook.fire(mod) for _ in range(3)] == ["sent", "quiet", "gated"]
  reviews.path(tmp_path / "mono").touch()
  assert hook.fire(mod) == "quiet"


def test_two_paths_differing_only_by_a_slash_and_an_underscore_keep_separate_gates(tmp_path):
  """An answer gated for /r/a/b says nothing about /r/a_b, so each path gets a stamp of its own, and the same path stays gated."""
  script = f'. "{HOOKS / "gate.sh"}"; gate_mark inject /r/a/b session; gate_skip inject /r/a_b session && echo shared || echo separate; gate_skip inject /r/a/b session && echo gated'
  assert subprocess.run(["bash", "-c", script], capture_output=True, check=True, text=True, env={**os.environ, "TMPDIR": str(tmp_path)}).stdout.split() == ["separate", "gated"]


def test_a_dependency_as_old_as_the_stamp_reopens_and_a_note_named_from_its_repo_is_never_gated(tmp_path):
  """A dependency changed in the stamp's own second is not older than it, which is all a bash that compares whole seconds can tell; a note's path relative to its repo is a note too."""
  (dependency := tmp_path / "dependency").write_text("x\n")
  os.utime(dependency, (0, 0))   # long before the stamp
  skip = "gate_skip inject /r/x session && echo gated || echo reopened"
  script = f'. "{HOOKS / "gate.sh"}"; gate_mark inject /r/x session "$1"; {skip}; touch -r "$GATE_STAMP" "$1"; {skip}; gate_mark inject .agents/todo.md session; gate_skip inject .agents/todo.md session && echo gated || echo note'
  assert subprocess.run(["bash", "-c", script, "gate", str(dependency)], capture_output=True, check=True, text=True, env={**os.environ, "TMPDIR": str(tmp_path)}).stdout.split() == ["gated", "reopened", "note"]
