"""What every test file needs: the repo on the path, a git repo, a note in it, a standard.

The path insert lives here because pytest imports this before any test module and agentkit is not
installed. So does the profile switch-off, for the same reason: it has to be in place first.

Author: Marco Cassar (@Ocramaru)
"""

import os
import tempfile
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "bin" / "agent"

sys.path.insert(0, str(REPO))

# The suite tests agentkit, not whoever runs it. Empty means no profile, and the CLI subprocesses
# inherit it; a test about profiles sets its own.
os.environ["AGENTS_PROFILE"] = ""
os.environ["AGENTS_HOOK_LOG"] = str(Path(tempfile.mkdtemp(prefix="agents-hooks-")) / "hooks.log")   # never this machine's log


def git(d: Path) -> Path:
  """An initialised repo at `d`. The chain stops at a repo root, so a test tree needs a real one."""
  d.mkdir(parents=True, exist_ok=True)
  subprocess.run(["git", "init", "-q"], cwd=d, check=True)
  return d


def note(d: Path, text: str = "notes", name: str = "context") -> Path:
  """A note of `name` in `d/.agents`, with the frontmatter the convention expects."""
  a = d / ".agents"
  a.mkdir(parents=True, exist_ok=True)
  (a / f"{name}.md").write_text(f"---\nname: {name}\nkind: {name}\n---\n\n{text}\n")
  return a


def standard(d: Path, name: str, applies: str = "", related: str = "", body: str = "x") -> Path:
  """A standard named `name` in `d`, with the frontmatter the library reads."""
  d.mkdir(parents=True, exist_ok=True)
  f = d / f"{name}.md"
  f.write_text(f"---\nname: {name}\napplies: {applies}\nrelated: {related}\n---\n\n{body}\n")
  return f


def agent(args: list[str], cwd: Path, expect: int | None = 0, env: dict | None = None,
          stdin: str | None = None):
  """The CLI as a subprocess, which is the only way to test where someone is standing.

  `GIT_CONFIG_GLOBAL` is pinned empty so no test depends on whether the global hook is installed here.
  """
  r = subprocess.run([str(AGENT), *args], cwd=cwd, capture_output=True, check=False, text=True,
                     input=stdin, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, **(env or {})})
  if expect is not None:
    assert r.returncode == expect, f"{args} in {cwd}\nout: {r.stdout}\nerr: {r.stderr}"
  return r


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
