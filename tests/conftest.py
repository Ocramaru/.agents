"""What every test file needs: the repo on the path, no profile, a git repo, a note in it, a standard.

The path insert and the profile switch-off live here because pytest imports this before any test module, and agentkit is not installed.

Author: Marco Cassar (@Ocramaru)
"""

import atexit, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "bin" / "agent"

sys.path.insert(0, str(REPO))

from agentkit import agents, review, reviews
from agentkit.backends import Reply
from agentkit.session import Message, Session

# The suite tests agentkit, not whoever runs it. Empty means no profile, and the CLI subprocesses
# inherit it; a test about profiles sets its own.
os.environ["AGENTS_PROFILE"] = ""
hook_logs = Path(tempfile.mkdtemp(prefix="agents-hooks-"))
atexit.register(shutil.rmtree, hook_logs, ignore_errors=True)
os.environ["AGENTS_HOOK_LOG"] = str(hook_logs / "hooks.log")   # never this machine's log
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull   # every git a test runs, so this machine's core.hooksPath never fires a real review


def git(directory: Path) -> Path:
  """An initialised repo at `directory`. The chain stops at a repo root, so a test tree needs a real one."""
  directory.mkdir(parents=True, exist_ok=True)
  subprocess.run(["git", "init", "-q"], cwd=directory, check=True)
  return directory


def note(directory: Path, text: str = "notes", name: str = "context") -> Path:
  """A note of `name` in `directory/.agents`, with the frontmatter the convention expects."""
  agents_dir = directory / ".agents"
  agents_dir.mkdir(parents=True, exist_ok=True)
  (agents_dir / f"{name}.md").write_text(f"---\nname: {name}\nkind: {name}\n---\n\n{text}\n")
  return agents_dir


def standard(directory: Path, name: str, applies: str = "", related: str = "", body: str = "x") -> Path:
  """A standard named `name` in `directory`, with the frontmatter the library reads."""
  directory.mkdir(parents=True, exist_ok=True)
  file = directory / f"{name}.md"
  file.write_text(f"---\nname: {name}\napplies: {applies}\nrelated: {related}\n---\n\n{body}\n")
  return file


def agent(args: list[str], cwd: Path, expect: int | None = 0, env: dict | None = None, stdin: str | None = None):
  """The CLI as a subprocess, which is the only way to test where someone is standing."""
  result = subprocess.run([str(AGENT), *args], cwd=cwd, capture_output=True, check=False, text=True, input=stdin, env={**os.environ, **(env or {})})
  if expect is not None: assert result.returncode == expect, f"{args} in {cwd}\nout: {result.stdout}\nerr: {result.stderr}"
  return result


@pytest.fixture
def repo(tmp_path) -> Path:
  """A git repo with a note at the root and a module to edit: what an injection test needs."""
  git(tmp_path)
  note(tmp_path, "# r\n\nCTX")
  (tmp_path / "mod.py").write_text("x = 1\n")
  return tmp_path


@pytest.fixture
def ledger(tmp_path) -> Path:
  """A repo with no notes, for the review ledger, which only needs a root to be relative to."""
  pytest.importorskip("duckdb")
  return git(tmp_path)


# -- review fixtures: a backend that answers from a list, and the ledger records a review leaves --
CLEAN = {"kind": "findings", "state": "completed", "body": "looked", "data": {"findings": []}}


class Stub:
  """A backend giving the replies it was handed, then clean ones; it remembers what it was asked."""
  name, resumable, parallel, spec = "stub", False, 4, {}

  def __init__(self, *replies): self.replies, self.shown, self.asked = list(replies), [], []

  def model_for(self, role): return role

  def run(self, prompt, tier="text", session=None, effort=None):
    self.shown.append(prompt)
    self.asked.append((tier, effort))
    time.sleep(0.4 if "SLOW" in prompt else 0.0)
    reply = self.replies.pop(0) if self.replies else CLEAN
    if isinstance(reply, Exception): raise reply
    return Reply(json.dumps(reply))


def findings(*items) -> dict:
  return {"kind": "findings", "state": "completed", "body": "found", "data": {"findings": list(items)}}


def put(root: Path, *paths: str, text: str = "x = 1\n") -> list[Path]:
  """Files at `paths` under `root`, parents made, each holding `text`."""
  for path in paths:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text)
  return [root / path for path in paths]


def record(root, task, file, found, body="verdict"):
  conversation = Session(task)
  conversation.post(Message("caller", "note", "working", "review this"))
  message = Message("file-review", "findings", "completed", body)
  conversation.post(message)
  return reviews.record(conversation, "file-review", "ollama", root, file, message, found, "large")


def run_review(name, backend, paths, root, **kwargs): return review.run(name, backend, paths, root, agents.definition(name, agents.definitions()), {}, **kwargs)
