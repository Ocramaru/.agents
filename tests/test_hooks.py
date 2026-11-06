"""Each hook logs one row per firing, and a hook that could not do its job logs an ERROR saying why.

The hooks run from this checkout against a fake `agent`, so what the CLI prints and how it exits is the test's to choose.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from conftest import REPO, UV_CACHE, agent, git

from agentkit import hooks
from agentkit.cli.notes import ALREADY_SENT, NOTHING_GOVERNS, SENT

FAKE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_CALLS"
printf '%s' "${FAKE_STDOUT:-}"
printf '%s' "${FAKE_STDERR:-}" >&2
exit "${FAKE_STATUS:-0}"
"""


@pytest.fixture
def environment(tmp_path) -> dict:
  """A HOME whose .agents holds this checkout's hooks and a fake `agent`, which records each call and prints and exits as FAKE_* say."""
  (hub := tmp_path / "home" / ".agents" / "bin").mkdir(parents=True)
  (hub.parent / "hooks").symlink_to(REPO / "hooks")
  (hub / "agent").write_text(FAKE)
  (hub / "agent").chmod(0o755)
  return {**os.environ, "HOME": str(tmp_path / "home"), "TMPDIR": str(tmp_path), "AGENTS_HOOK_LOG": str(tmp_path / "hooks.log"), "FAKE_CALLS": str(tmp_path / "calls"), "UV_CACHE_DIR": UV_CACHE}


def fire(environment: dict, hook: str, payload: dict, cwd: Path | None = None, **fake: str) -> tuple[subprocess.CompletedProcess, list[str]]:
  """Run one hook as Claude Code does, with FAKE_<key> set from `fake`; return what it did and the one row it logged."""
  rows = len(hooks.entries(log=Path(environment["AGENTS_HOOK_LOG"]), verbose=True))
  ran = subprocess.run(["bash", str(REPO / "hooks" / hook)], input=json.dumps(payload), text=True, capture_output=True, check=False, cwd=cwd, env=environment | {f"FAKE_{key.upper()}": value for key, value in fake.items()})
  logged = hooks.entries(log=Path(environment["AGENTS_HOOK_LOG"]), verbose=True)
  assert len(logged) == rows + 1, f"{hook} logged {len(logged) - rows} rows, not one: {ran.stderr}"
  return ran, logged[-1]


def test_doc_check_reports_every_line_and_logs_why_a_run_failed(environment, tmp_path):
  """doc-check asks `agent sub run` for JSON and counts every line it reports; a run that fails, or prints what is not JSON, is an ERROR naming why."""
  project = git(tmp_path / "project")
  (project / "a.md").write_text("one\n")
  subprocess.run(["git", "add", "a.md"], cwd=project, check=True)
  subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "a"], cwd=project, check=True)
  (project / "a.md").write_text("two\n")   # a diff against HEAD, so the hook runs the check
  environment |= {"AGENTS_DOC_CHECK": "1"}

  ran, row = fire(environment, "doc-check.sh", {"session_id": "s-1"}, project, stdout=json.dumps({"state": "completed", "body": "", "findings": [{"file": "a.md", "line": 1, "issue": "says two"}, {"file": "a.md", "line": 1, "issue": "said one"}]}))
  assert json.loads(ran.stdout)["systemMessage"] == "doc-check:\n  a.md:1  says two\n  a.md:1  said one"
  assert row[1:] == ["doc-check", "s-1", "reported", "3 lines"]
  assert (tmp_path / "calls").read_text() == "sub run doc-check --changed --json\n"

  ran, row = fire(environment, "doc-check.sh", {"session_id": "s-1"}, project, status="2", stderr="Traceback (most recent call last):\nno default backend is set")
  assert ran.returncode == 0 and ran.stdout == "" and row[3:] == ["ERROR", "rc=2 no default backend is set"]

  ran, row = fire(environment, "doc-check.sh", {"session_id": "s-1"}, project, stdout=json.dumps({"state": "failed", "body": "backend timed out", "findings": []}))
  assert ran.returncode == 0 and ran.stdout == "" and row[3:] == ["ERROR", "state=failed backend timed out"]   # not read as clean

  ran, row = fire(environment, "doc-check.sh", {"session_id": "s-1"}, project, stdout="usage: agent ...")
  assert ran.returncode == 0 and row[3] == "ERROR" and "usage: agent" in row[4]

  ran = subprocess.run(["bash", str(REPO / "hooks" / "doc-check.sh")], input="not json", text=True, capture_output=True, check=False, cwd=project, env=environment)   # what jq cannot read, so not through fire, which sends JSON
  assert ran.returncode == 0 and ran.stdout == "" and hooks.entries(log=Path(environment["AGENTS_HOOK_LOG"]), verbose=True)[-1][1:] == ["doc-check", "nosessio", "ERROR", "a payload jq cannot read"]


def test_inject_sends_text_beside_a_warning_and_never_gates_an_exit_it_does_not_know(environment, tmp_path):
  """A warning on stderr beside a zero exit still sends the text; an exit other than 0, 1 or 3 is an ERROR, asked again on the next edit."""
  (module := tmp_path / "mod.py").write_text("x = 1\n")
  edit = {"session_id": "s-5", "tool_name": "Edit", "tool_input": {"file_path": str(module), "old_string": "a", "new_string": "b"}}
  ran, row = fire(environment, "inject.sh", edit, stdout="--- python (profile) ---\nrules", stderr="SyntaxWarning: invalid escape sequence")
  assert json.loads(ran.stdout)["hookSpecificOutput"]["additionalContext"] == "--- python (profile) ---\nrules" and row[3] == "sent"

  for _ in range(2): assert fire(environment, "inject.sh", edit, status="137")[1][3:5] == ["ERROR", f"rc=137   {module}"]
  assert (tmp_path / "calls").read_text().count("inject ") == 3


def test_session_start_asks_inject_for_the_directory_and_says_what_it_loaded(environment, tmp_path):
  """The session's directory goes to `inject --start`, its text back as SessionStart context with a notice counting the notes; no notes, a resume and a failure each log their own status."""
  (project := tmp_path / "project").mkdir()
  start = {"session_id": "s-6", "cwd": str(project), "source": "startup"}
  ran, row = fire(environment, "session-start.sh", start, stdout="Notes\n\n--- ./context.md ---\nrules\n\n--- pkg/context.md ---\nmore")
  said = json.loads(ran.stdout)
  assert said["hookSpecificOutput"] == {"hookEventName": "SessionStart", "additionalContext": "Notes\n\n--- ./context.md ---\nrules\n\n--- pkg/context.md ---\nmore"}
  assert said["systemMessage"].startswith(".agents loaded 2 notes for project (") and row[1:4] == ["start", "s-6", "sent"]
  assert (tmp_path / "calls").read_text() == f"inject {project} --session s-6 --start\n"

  assert [fire(environment, "session-start.sh", start, status=status)[1][3] for status in ("3", "1", "2")] == ["none", "quiet", "ERROR"]
  ran, row = fire(environment, "session-start.sh", {"session_id": "s-6"})
  assert ran.stdout == "" and row[3] == "skip" and len((tmp_path / "calls").read_text().splitlines()) == 4   # no directory, so nothing asked
  ran, _ = fire(environment, "session-start.sh", {"session_id": "s-6", "cwd": "/"}, stdout="--- ./context.md ---\nrules")
  assert json.loads(ran.stdout)["systemMessage"].startswith(".agents loaded 1 note for / (")   # a directory with no last name is named whole


def test_both_inject_hooks_compare_its_exit_against_the_codes_its_constants_name():
  """Shell cannot import SENT, ALREADY_SENT and NOTHING_GOVERNS, so the codes each hook tests `inject`'s exit against are read out of it and held to theirs."""
  for hook in ("inject.sh", "session-start.sh"):
    text = (REPO / "hooks" / hook).read_text()
    assert {int(code) for code in re.findall(r'"\$exit_code" -(?:eq|ne) (\d+)', text)} == {SENT, ALREADY_SENT, NOTHING_GOVERNS}, hook
    assert "agentkit/cli/notes.py" in text, hook   # its comment points at where they are named


def test_the_guard_and_remap_hooks_log_the_reason_they_failed(environment, tmp_path):
  """A guard that cannot run lets the command through and logs the last line it printed; so does a remap that fails."""
  ran, row = fire(environment, "no-reformat.sh", {"session_id": "s-2", "tool_input": {"command": "ls"}}, status="1", stderr="Traceback (most recent call last):\nImportError: no agentkit")
  assert ran.returncode == 0 and row[3:] == ["ERROR", "guard would not run, allowing rc=1 ImportError: no agentkit"]

  (note := tmp_path / "repo" / ".agents" / "context.md").parent.mkdir(parents=True)
  note.write_text("# r\n")
  ran, row = fire(environment, "notes-map.sh", {"session_id": "s-2", "tool_input": {"file_path": str(note)}}, status="1", stderr="Traceback (most recent call last):\nKeyError: 'name'")
  assert ran.returncode == 0 and row[3:] == ["ERROR", "remap failed: KeyError: 'name'"]


def test_the_remap_hook_asks_the_cli_to_skip_what_is_not_a_note(environment, tmp_path):
  """The hub is itself a .agents, so every .md in it matches the hook's glob; the hook passes --if-note, and a file the CLI skips is logged as skipped, not as an ERROR."""
  (readme := tmp_path / "hub" / ".agents" / "README.md").parent.mkdir(parents=True)
  readme.write_text("# hub\n")
  ran, row = fire(environment, "notes-map.sh", {"session_id": "s-4", "tool_input": {"file_path": str(readme)}}, stdout=f"skipped  {readme}, not a note\n")
  assert ran.returncode == 0 and Path(environment["FAKE_CALLS"]).read_text() == f"remap --if-note {readme}\n"
  assert row[3] == "skipped" and "ERROR" not in row


def log(environment: dict, *arguments: str) -> None:
  """hook_log called from bash as a hook calls it."""
  subprocess.run(["bash", "-c", f'set -euo pipefail; . "{REPO}/hooks/log.sh"; hook_log "$@"', "hook_log", *arguments], check=True, env=environment)


def test_hook_log_writes_one_row_per_call_and_a_bad_call_as_an_error(environment):
  """Tabs and newlines in the text never split a row, and a call missing its text logs an ERROR rather than its hook's name as the text."""
  log(environment, "inject", "s-3", "sent\tsplit", "across\nlines")
  log(environment, "inject")
  hooks.log("post-commit", "git", "done   split\tacross\nlines", log=Path(environment["AGENTS_HOOK_LOG"]))   # the same row from Python
  assert [row[1:] for row in hooks.entries(log=Path(environment["AGENTS_HOOK_LOG"]), verbose=True)] == [["inject", "s-3", "sent", "split across lines"], ["inject", "nosessio", "ERROR", "hook_log needs <hook> <session> <what>, and got 1 arguments"], ["post-commit", "git", "done", "split across lines"]]

  assert agent(["hooks", "--tail", "1", "--verbose"], cwd=REPO, env=environment).stdout.count("split across lines") == 1
  assert "split across lines" not in agent(["hooks", "--tail", "0", "--verbose"], cwd=REPO, expect=1, env=environment).stdout   # none, not all


def test_the_log_is_rotated_by_one_hook_at_a_time(environment):
  """Past a megabyte the log keeps its last 500 lines; a hook that finds another rotating only appends, and a lock left by a killed hook is taken over."""
  (lock := Path(environment["AGENTS_HOOK_LOG"] + ".lock")).mkdir()
  Path(environment["AGENTS_HOOK_LOG"]).write_text("".join(f"2026-01-01T00:00:00+0000\tinject    \told     \tsent   {'x' * 2000} {number}\n" for number in range(600)))

  log(environment, "inject", "s-4", "sent   while another rotates")
  assert len(Path(environment["AGENTS_HOOK_LOG"]).read_text().splitlines()) == 601 and lock.is_dir()

  os.utime(lock, (time.time() - 600, time.time() - 600))
  log(environment, "inject", "s-4", "sent   after it was killed")
  lines = Path(environment["AGENTS_HOOK_LOG"]).read_text().splitlines()
  assert len(lines) == 501 and lines[-1].endswith("after it was killed") and not lock.exists()


def test_post_commit_reviews_the_commit_it_fired_for_even_once_head_moves(environment, tmp_path):
  """The review is handed the commit's own id, read when the hook fires, never `HEAD`, which a second commit can move before the detached review starts."""
  repo = git(tmp_path / "repo")
  subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-q", "--allow-empty", "-m", "one"], check=True, env=environment)
  commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, check=True, text=True).stdout.strip()
  subprocess.run(["bash", str(REPO / "hooks" / "post-commit.sh")], cwd=repo, check=True, env=environment)
  calls = Path(environment["FAKE_CALLS"])

  for _ in range(100):   # the review is detached, so its call lands a moment later
    if calls.is_file() and calls.read_text(): break
    time.sleep(0.05)
  assert calls.read_text().split() == ["sub", "review", "auto", "--commit", commit]


def test_forget_clears_a_session_by_its_plain_id_and_refuses_one_that_is_a_path(environment, tmp_path):
  """forget.sh puts the session id into a path it removes, so an id that is not a plain name is refused and nothing outside the stamps goes."""
  (tmp_path / "agents-abc" / "gate").mkdir(parents=True)
  (tmp_path / "keep").mkdir()
  _, row = fire(environment, "forget.sh", {"session_id": "abc/../keep"})
  assert row[3] == "ERROR" and (tmp_path / "keep").is_dir()
  _, row = fire(environment, "forget.sh", {"session_id": "abc"})
  assert row[3:] == ["cleared", "1 stamps, so the next edit re-injects"] and not (tmp_path / "agents-abc").exists()
  ran, row = fire(environment, "forget.sh", {"session_id": "abc"})   # compacted again, with nothing stamped since
  assert ran.returncode == 0 and row[3:] == ["cleared", "0 stamps, so the next edit re-injects"]


def test_a_reviewer_agentkit_started_gets_neither_the_notes_nor_the_standards(environment, tmp_path):
  """The backend marks the `claude -p` it starts, and the start, edit and stop hooks inside it skip without asking `agent`, so a reviewer's Stop never starts another review."""
  (module := (project := git(tmp_path / "project")) / "mod.py").write_text("x = 1\n")
  subprocess.run(["git", "add", "mod.py"], cwd=project, check=True)
  subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "a"], cwd=project, check=True)
  module.write_text("x = 2\n")   # a diff against HEAD, so doc-check would run its check
  environment |= {"AGENTS_REVIEWER": "1", "AGENTS_DOC_CHECK": "1"}
  for hook, payload in (("session-start.sh", {"session_id": "s-9", "cwd": str(project)}), ("inject.sh", {"session_id": "s-9", "tool_input": {"file_path": str(module)}}), ("doc-check.sh", {"session_id": "s-9"})):
    ran, row = fire(environment, hook, payload, project, stdout="--- ./context.md ---\nrules")
    assert ran.returncode == 0 and ran.stdout == "" and row[2:4] == ["reviewer", "skip"]
  assert not (tmp_path / "calls").exists()


def test_a_session_without_an_id_is_never_deduped_and_one_that_is_not_a_plain_name_is_refused(environment, tmp_path):
  """With no id, inject is asked without one, so it stamps nothing, and the gate is not used; an id that would be a path is an ERROR, with nothing asked."""
  (module := tmp_path / "mod.py").write_text("x = 1\n")
  edit = {"tool_input": {"file_path": str(module)}}
  assert [fire(environment, "inject.sh", edit, status="3")[1][2:4] for _ in range(2)] == [["nosessio", "none"]] * 2   # asked twice: nothing was gated
  fire(environment, "session-start.sh", {"cwd": str(tmp_path)}, status="3")
  assert (tmp_path / "calls").read_text().splitlines() == [f"inject {module} --session  --edit --depends"] * 2 + [f"inject {tmp_path} --session  --start"]

  for hook, payload in (("inject.sh", {"session_id": "../x", "tool_input": {"file_path": str(module)}}), ("session-start.sh", {"session_id": "a/b", "cwd": str(tmp_path)})):
    ran, row = fire(environment, hook, payload)
    assert ran.returncode == 0 and row[3:] == ["ERROR", "refused a session id that is not a plain name"]
  assert len((tmp_path / "calls").read_text().splitlines()) == 3
