"""`agent status`, which describes this machine and never fails, run as a subprocess from a checkout and as installed.
The backend and a missing duckdb are read in-process, where the profile's config and the import can be pinned.

Author: Marco Cassar (@Ocramaru)
"""

import json, sys
from pathlib import Path
from types import SimpleNamespace

from conftest import REPO, agent, git, note, put, record, standard

import agentkit.git
from agentkit import hooks, hub, reviews, status
from agentkit.cli import setup


def described(output: str) -> dict[str, list[str]]:
  """What `agent status` printed, as part -> each of its states in order."""
  parts: dict[str, list[str]] = {}
  for line in output.splitlines():
    part, _, state = line.partition("  ")
    parts.setdefault(part, []).append(state.strip())
  return parts


def test_a_checkout_is_a_clone_and_the_wheel_an_install(tmp_path, fresh, machine):
  """The first line says which this is, and an install on an empty machine describes what it lacks, counts only the hook errors since it was installed, and exits 0."""
  assert described(agent(["status"], cwd=tmp_path).stdout)["agentkit"][0].endswith(f", a clone at {status.short(REPO)}")

  installed = described(fresh(["status"]).stdout)
  assert ", an install at " in installed["agentkit"][0] and "(its state in " in installed["agentkit"][0]
  assert installed["profile"] == ["none (the starters in .agents are in use)"] and installed["findings"] == ["none (not in a git repo)"]
  assert installed["claude hooks"][0].startswith("not in place (there is no ") and installed["backend"][0].startswith("none set (of claude, codex, ollama)")

  (log := Path(machine["HOME"]) / ".agents" / ".hooks.log").parent.mkdir(parents=True, exist_ok=True)
  log.write_text("2000-01-01T09:00:00+0000\tinject    \tabc12345\tERROR  before the install\n2100-01-01T09:00:00+0000\tinject    \tabc12345\tERROR  after it\n")
  assert described(fresh(["status"]).stdout)["hook errors"][0] == "1 since .agents last changed (the latest from inject at 2100-01-01 09:00)"


def test_the_profile_its_remote_and_where_each_standard_comes_from(tmp_path, monkeypatch):
  """A profile names its remote and what is unpushed; each layer of a standard counts where it comes from, a replaced starter not at all; notes count from here up."""
  repo, bare, mine = git(tmp_path / "repo"), tmp_path / "mine.git", tmp_path / "mine"
  note(repo)
  note(repo / "pkg")
  standard(repo / ".agents" / "standards", "local", applies="*.zz")
  standard(repo / ".agents" / "standards", "commits")   # layers on the starter, which still counts

  agentkit.git.run(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
  agentkit.git.run(tmp_path, "clone", "-q", str(bare), str(mine))
  standard(mine / "standards", "python")   # replaces the starter of its name
  standard(mine / "standards", "extra")
  agentkit.git.run(mine, "add", "-A")
  agentkit.git.run(mine, "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "-qm", "pushed")
  agentkit.git.run(mine, "push", "-q", "-u", "origin", "main")
  agentkit.git.run(mine, "-c", "user.name=T", "-c", "user.email=t@t.io", "commit", "--allow-empty", "-qm", "not pushed")

  shown = described(agent(["status"], cwd=repo / "pkg", env={"AGENTS_PROFILE": str(mine)}).stdout)
  assert shown["profile"] == [f"{mine} ({bare})", "1 commit not pushed"]
  assert shown["standards"] == [f"{len(list((REPO / 'standards').glob('*.md'))) - 1} bundled, 2 profile, 2 repo"]
  assert shown["notes"] == ["2 on the path from here (., pkg)"]
  assert shown["findings"] == [f"none (no reviews in {repo.resolve()})"]
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  assert [level for *_, level in status.profile()] == ["", "warn"]   # what another machine would miss wants a look


def test_the_default_backend_its_models_and_the_role_each_reviewer_asks_for(tmp_path, monkeypatch):
  """The backend is the profile's default, its models are listed by role, and reviewers are counted and grouped by the role they ask for."""
  mine = tmp_path / "mine"
  put(mine, "config.toml", text='[backends]\ndefault = "local"\n\n[backends.local]\nkind = "http"\nmodels = { text = "small-one", code-large = "big-one" }\n')
  put(mine, "agents/mine.md", text="---\nname: mine\nmodel: code\n---\n\nreview\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setattr(hub, "LOCAL", tmp_path / "local.toml")   # never this machine's
  monkeypatch.chdir(tmp_path)

  (_, backend, _), (_, models, _), (_, reviewers, _) = status.backend()
  assert backend.startswith("local (of ") and "claude" in backend
  assert models == "small-one (text)  ·  big-one (code-large)"
  assert reviewers.startswith(f"{len(list((REPO / 'agents').glob('*.md'))) + 1}, asking for code (mine)  ·  code-large (")


def test_the_hooks_claude_and_git_run_and_the_errors_they_logged_since_agents_changed(tmp_path):
  """The bundled hooks block reads as in place, a core.hooksPath at this hub as this hub's, and only errors newer than the last commit count."""
  put(tmp_path, "claude/settings.json", text=json.dumps({"model": "x", "hooks": json.loads((REPO / "settings.hooks.json").read_text())}))
  put(tmp_path, "gitconfig", text=f"[core]\n  hooksPath = {REPO / 'githooks'}\n")
  put(tmp_path, "hooks.log", text="2000-01-01T09:00:00+0000\tinject    \tabc12345\tERROR stale\n2100-01-01T09:00:00+0000\tinject    \tabc12345\tsent 2 standards\n2100-01-02T09:00:00+0000\tno-reformat\tabc12345\tERROR jq: parse error\nnot a row\n")

  shown = described(agent(["status"], cwd=tmp_path, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "claude"), "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "AGENTS_HOOK_LOG": str(tmp_path / "hooks.log")}).stdout)
  assert shown["claude hooks"] == [f"in place ({tmp_path / 'claude' / 'settings.json'})"]
  assert shown["git hooks"] == [f"this hub's (core.hooksPath {status.short(REPO / 'githooks')})"]
  assert shown["hook errors"] == ["1 since .agents last changed (the latest from no-reformat at 2100-01-02 09:00)", "jq: parse error"]
  assert described(agent(["status"], cwd=tmp_path).stdout)["git hooks"] == ["unset (each repo runs only its own .git/hooks)"]


def test_open_findings_are_counted_in_the_repo_here(reviewable_repo):
  """Every open finding in the reviews of the repo holding the working directory, and how many files they are in."""
  put(reviewable_repo, "mod.py")
  reviews.write(record(reviewable_repo, "t", "mod.py", [{"line": 1, "issue": "first"}, {"line": 2, "issue": "second"}]), reviewable_repo)
  assert described(agent(["status"], cwd=reviewable_repo).stdout)["findings"] == [f"2 open in 1 file of {reviewable_repo.resolve()} (`agent sub reviews --open` lists them)"]


def test_a_broken_part_is_described_and_the_rest_still_show(tmp_path, monkeypatch):
  """Unparseable settings.json or agents.toml, and reviews with no duckdb to read them, each describe themselves; status still exits 0."""
  repo = git(tmp_path / "repo")
  (note(repo) / "agents.toml").write_text("inject = \n")
  put(repo, ".agents/.reviews/reviews.duckdb", text="")
  put(tmp_path, "claude/settings.json", text='{"hooks": {},}')

  shown = described(agent(["status"], cwd=repo, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "claude")}).stdout)
  assert shown["claude hooks"][0].startswith(f"unknown ({tmp_path / 'claude' / 'settings.json'} is not valid JSON")
  assert shown["standards"][0].startswith("cannot be read, TOMLDecodeError: ") and shown["agentkit"] and shown["hook errors"]
  assert shown["findings"][0].startswith("cannot be read, ")   # an empty file where the reviews go

  monkeypatch.setitem(sys.modules, "duckdb", None)   # what importing it does where it is not installed
  monkeypatch.chdir(repo)
  assert [(state, level) for part, state, level in status.rows() if part == "findings"] == [("cannot be read, RuntimeError: reviews need duckdb: `uv sync` in ~/.agents, or install it yourself", "fail")]


def test_each_part_says_whether_it_wants_a_look_or_is_broken(tmp_path, monkeypatch):
  """A part that is fine has no level, one to look at is `warn`, and one that is broken is `fail`."""
  monkeypatch.setattr(status.install, "config_dir", lambda target: tmp_path / "claude")
  assert status.claude()[0][2] == "fail"   # no settings.json
  put(tmp_path, "claude/settings.json", text=json.dumps({"hooks": json.loads((REPO / "settings.hooks.json").read_text())}))
  assert status.claude()[0][2] == ""
  put(tmp_path, "claude/settings.json", text=json.dumps({"hooks": {}}))
  assert status.claude()[0][2] == "warn"

  monkeypatch.setattr(status.backends, "load_backends", lambda: ({}, "gone"))
  assert status.backend()[0] == ("backend", "gone, which [backends] does not define", "fail")
  monkeypatch.setattr(status.install, "global_hooks_path", lambda: str(tmp_path / "elsewhere"))
  assert status.githooks()[0][2] == "warn"
  monkeypatch.setattr(status.hooks, "errors", lambda: [["2100-01-02T09:00:00+0000", "inject", "abc12345", "ERROR", "boom"]])
  assert [level for *_, level in status.errors()] == ["warn", ""]


def test_a_path_under_home_starts_at_a_tilde(tmp_path, monkeypatch):
  """Under home a path is shown from ~, and anywhere else as it is."""
  monkeypatch.setattr(status.Path, "home", lambda: tmp_path)
  assert [status.short(tmp_path / ".agents" / "profile"), status.short("/etc/x")] == ["~/.agents/profile", "/etc/x"]


def test_at_a_terminal_a_part_is_named_once_its_detail_dimmed_and_its_level_coloured(monkeypatch, capsys):
  """Piped, every line names its part and is plain; at a terminal a run of one part is named once in bold cyan, parentheses are dim, `warn` is yellow and `fail` red."""
  monkeypatch.setattr(status, "rows", lambda: [("profile", "~/p (git@x:p.git)", ""), ("profile", "1 commit not pushed", "warn"), ("claude hooks", "not in place ([a] b)", "fail")])
  assert setup.cmd_status(None) == 0
  assert capsys.readouterr().out == "profile       ~/p (git@x:p.git)\nprofile       1 commit not pushed\nclaude hooks  not in place ([a] b)\n"

  said = []
  monkeypatch.setattr(setup, "say", said.append)
  monkeypatch.setattr(setup.sys, "stdout", SimpleNamespace(isatty=lambda: True))
  assert setup.cmd_status(None) == 0
  assert said == ["[bold cyan]profile     [/bold cyan]  ~/p [dim](git@x:p.git)[/dim]", "[bold cyan]            [/bold cyan]  [yellow]1 commit not pushed[/yellow]", "[bold cyan]claude hooks[/bold cyan]  [red]not in place [dim](\\[a] b)[/dim][/red]"]


def test_an_install_with_no_record_to_date_it_by_counts_every_error_rather_than_failing(tmp_path, monkeypatch):
  """When the install's RECORD is gone, every logged error counts, and the window doctor and status share does not raise."""
  monkeypatch.setattr(hooks.hub, "INSTALLED", True)
  monkeypatch.setattr(hooks.importlib.metadata, "distribution", lambda name: SimpleNamespace(files=[SimpleNamespace(name="RECORD", locate=lambda: tmp_path / "gone" / "RECORD")]))
  monkeypatch.setattr(hooks, "entries", lambda: [["2000-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "old"]])
  assert [row[4] for row in hooks.errors()] == ["old"]
