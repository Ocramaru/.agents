"""`agent status`, which describes this machine and never fails, run as a subprocess from a checkout and as installed.
The backend and a missing duckdb are read in-process, where the profile's config and the import can be pinned.

Author: Marco Cassar (@Ocramaru)
"""

import json, sys
from pathlib import Path
from types import SimpleNamespace

from conftest import REPO, agent, git, note, put, record, standard

from agentkit import hooks, profile, reviews, status


def described(output: str) -> dict[str, list[str]]:
  """What `agent status` printed, as part -> each of its states in order."""
  parts: dict[str, list[str]] = {}
  for line in output.splitlines():
    part, _, state = line.partition("  ")
    parts.setdefault(part, []).append(state.strip())
  return parts


def test_a_checkout_is_a_clone_and_the_wheel_an_install(tmp_path, fresh, machine):
  """The first line says which this is, and an install on an empty machine describes what it lacks, counts only the hook errors since it was installed, and exits 0."""
  assert described(agent(["status"], cwd=tmp_path).stdout)["agentkit"][0].endswith(f", a clone at {REPO}")

  installed = described(fresh(["status"]).stdout)
  assert ", an install at " in installed["agentkit"][0] and "its state in " in installed["agentkit"][0]
  assert installed["profile"] == ["none, so the starters in .agents are in use"] and installed["findings"] == ["none: not in a git repo"]
  assert installed["claude hooks"][0].startswith("not in place: there is no ") and installed["backend"][0].startswith("none set, of claude, codex, ollama")

  (log := Path(machine["HOME"]) / ".agents" / ".hooks.log").parent.mkdir(parents=True, exist_ok=True)
  log.write_text("2000-01-01T09:00:00+0000\tinject    \tabc12345\tERROR  before the install\n2100-01-01T09:00:00+0000\tinject    \tabc12345\tERROR  after it\n")
  assert described(fresh(["status"]).stdout)["hook errors"][0].startswith("1 since .agents last changed, the latest from inject at 2100")


def test_the_profile_its_remote_and_where_each_standard_comes_from(tmp_path):
  """A profile names its remote and what is unpushed; each layer of a standard counts where it comes from, a replaced starter not at all; notes count from here up."""
  repo, bare, mine = git(tmp_path / "repo"), tmp_path / "mine.git", tmp_path / "mine"
  note(repo)
  note(repo / "pkg")
  standard(repo / ".agents" / "standards", "local", applies="*.zz")
  standard(repo / ".agents" / "standards", "commits")   # layers on the starter, which still counts

  profile.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
  profile.git(tmp_path, "clone", "-q", str(bare), str(mine))
  standard(mine / "standards", "python")   # replaces the starter of its name
  standard(mine / "standards", "extra")
  profile.git(mine, "add", "-A")
  profile.git(mine, "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "pushed")
  profile.git(mine, "push", "-q", "-u", "origin", "main")
  profile.git(mine, "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "--allow-empty", "-qm", "not pushed")

  shown = described(agent(["status"], cwd=repo / "pkg", env={"AGENTS_PROFILE": str(mine)}).stdout)
  assert shown["profile"] == [str(mine), f"remote {bare}", "1 commit not pushed"]
  assert shown["standards"] == [f"{len(list((REPO / 'standards').glob('*.md'))) - 1} hub, 2 profile, 2 repo"]
  assert shown["notes"] == ["2 on the path from here: ., pkg"]
  assert shown["findings"] == [f"none: no review ledger in {repo.resolve()}"]


def test_the_default_backend_its_models_and_the_role_each_reviewer_asks_for(tmp_path, monkeypatch):
  """The backend is the profile's default, its models are listed by role, and reviewers are counted and grouped by the role they ask for."""
  mine = tmp_path / "mine"
  put(mine, "config.toml", text='[backends]\ndefault = "local"\n\n[backends.local]\nkind = "http"\nmodels = { text = "small-one", code-large = "big-one" }\n')
  put(mine, "agents/mine.md", text="---\nname: mine\nmodel: code\n---\n\nreview\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")   # never this machine's
  monkeypatch.chdir(tmp_path)

  (_, backend), (_, models), (_, reviewers) = status.backend()
  assert backend.startswith("local, the default of ") and "claude" in backend
  assert models == "text -> small-one, code-large -> big-one"
  assert reviewers.startswith(f"{len(list((REPO / 'agents').glob('*.md'))) + 1}, asking for code (mine); code-large (")


def test_the_hooks_claude_and_git_run_and_the_errors_they_logged_since_agents_changed(tmp_path):
  """The shipped hooks block reads as in place, a core.hooksPath at this hub as this hub's, and only errors newer than the last commit count."""
  put(tmp_path, "claude/settings.json", text=json.dumps({"model": "x", "hooks": json.loads((REPO / "settings.hooks.json").read_text())}))
  put(tmp_path, "gitconfig", text=f"[core]\n  hooksPath = {REPO / 'githooks'}\n")
  put(tmp_path, "hooks.log", text="2000-01-01T09:00:00+0000\tinject    \tabc12345\tERROR stale\n2100-01-01T09:00:00+0000\tinject    \tabc12345\tsent 2 standards\n2100-01-02T09:00:00+0000\tno-reformat\tabc12345\tERROR jq: parse error\nnot a row\n")

  shown = described(agent(["status"], cwd=tmp_path, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "claude"), "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "AGENTS_HOOK_LOG": str(tmp_path / "hooks.log")}).stdout)
  assert shown["claude hooks"] == [f"in place in {tmp_path / 'claude' / 'settings.json'}"]
  assert shown["git hooks"] == [f"core.hooksPath {REPO / 'githooks'}, this hub's"]
  assert shown["hook errors"] == ["1 since .agents last changed, the latest from no-reformat at 2100-01-02T09:00:00+0000: jq: parse error"]
  assert described(agent(["status"], cwd=tmp_path).stdout)["git hooks"] == ["core.hooksPath unset, so each repo runs only its own .git/hooks"]


def test_open_findings_are_counted_in_the_repo_here(ledger):
  """Every open finding in the ledger of the repo holding the working directory, and how many files they are in."""
  put(ledger, "mod.py")
  reviews.write(record(ledger, "t", "mod.py", [{"line": 1, "issue": "first"}, {"line": 2, "issue": "second"}]), ledger)
  assert described(agent(["status"], cwd=ledger).stdout)["findings"] == [f"2 open in 1 file of {ledger.resolve()}; `agent sub reviews --open` lists them"]


def test_a_broken_part_is_described_and_the_rest_still_show(tmp_path, monkeypatch):
  """Unparseable settings.json or agents.toml, and a ledger with no duckdb to read it, each describe themselves; status still exits 0."""
  repo = git(tmp_path / "repo")
  (note(repo) / "agents.toml").write_text("inject = \n")
  put(repo, ".agents/.reviews/reviews.duckdb", text="")
  put(tmp_path, "claude/settings.json", text='{"hooks": {},}')

  shown = described(agent(["status"], cwd=repo, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "claude")}).stdout)
  assert shown["claude hooks"][0].startswith(f"unknown: {tmp_path / 'claude' / 'settings.json'} is not valid JSON")
  assert shown["standards"][0].startswith("cannot be read, TOMLDecodeError: ") and shown["agentkit"] and shown["hook errors"]

  monkeypatch.setitem(sys.modules, "duckdb", None)   # what importing it does where it is not installed
  monkeypatch.chdir(repo)
  assert [state for part, state in status.rows() if part == "findings"] == ["cannot be read, RuntimeError: reviews need duckdb: `uv sync` in ~/.agents, or install it yourself"]


def test_an_install_with_no_record_to_date_it_by_counts_every_error_rather_than_failing(tmp_path, monkeypatch):
  """When the install's RECORD is gone, every logged error counts, and the window doctor and status share does not raise."""
  monkeypatch.setattr(hooks.profile, "INSTALLED", True)
  monkeypatch.setattr(hooks.importlib.metadata, "distribution", lambda name: SimpleNamespace(files=[SimpleNamespace(name="RECORD", locate=lambda: tmp_path / "gone" / "RECORD")]))
  monkeypatch.setattr(hooks, "entries", lambda: [["2000-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "old"]])
  assert [row[4] for row in hooks.errors()] == ["old"]
