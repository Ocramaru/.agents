"""A profile holds your own standards, reviewers and config apart from the public .agents, which reads them.

`local.toml`, the default profile path and git's global config are all pointed at temporary ones.
"""

import argparse
import re
import tomllib
from pathlib import Path

import pytest
from conftest import Stub, agent, fake, git as repository, note, put, standard

from agentkit import agents, backends, cli, config, doctor, git, hub, install, profile, reviews
from agentkit.standards import Library


@pytest.fixture
def isolated(tmp_path, monkeypatch):
  """Every path the profile code writes to, moved somewhere it can do no harm."""
  monkeypatch.setattr(hub, "LOCAL", tmp_path / "local.toml")
  monkeypatch.setattr(profile, "DEFAULT", tmp_path / "hub" / "profile")
  monkeypatch.delenv("AGENTS_PROFILE", raising=False)
  monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
  (tmp_path / "gitconfig").write_text("[user]\n  name = T\n  email = t@t.io\n[pull]\n  rebase = false\n")   # an identity, merging pulls, and no hooksPath so no review runs
  return tmp_path


def commit(repository: Path, message: str) -> None:
  """An empty commit: history is all these tests need."""
  git.run(repository, "commit", "--allow-empty", "-qm", message)


def published(parent: Path, name: str) -> tuple[Path, Path]:
  """A bare remote and a clone of it with one commit pushed: what a profile on GitHub looks like."""
  bare, clone = parent / f"{name}.git", parent / name
  git.run(parent, "init", "-q", "--bare", "-b", "main", str(bare))
  git.run(parent, "clone", "-q", str(bare), str(clone))
  commit(clone, "first")
  git.run(clone, "push", "-q", "-u", "origin", "main")
  return bare, clone


def fake_gh(parent: Path, monkeypatch, body: str) -> Path:
  """A gh first on PATH that logs its arguments, then runs `body`; returns the log."""
  return fake(parent, monkeypatch, "gh", body)


def test_the_profile_is_found_from_the_environment_then_local_toml_then_the_default(isolated, monkeypatch):
  """The environment wins over local.toml, which wins over the default; empty means none, and a broken local.toml is none."""
  hub.LOCAL.write_text("[profile\npath = ")
  assert profile.path() is None
  for wrong in ('profile = "/saved"\n',   # parses, but `profile` is a string, not a [profile] table
                "[profile]\npath = 3\n"):   # a [profile] table, but its path is an int, not a string
    hub.LOCAL.write_text(wrong)
    assert profile.chosen() is None and profile.path() is None

  profile.DEFAULT.mkdir(parents=True)
  assert profile.path() == profile.DEFAULT

  hub.LOCAL.write_text('[profile]\npath = "/saved"\n')
  assert profile.path() == Path("/saved")

  for value, expected in ((str(isolated / "env"), isolated / "env"), ("", None)):
    monkeypatch.setenv("AGENTS_PROFILE", value)
    assert profile.path() == expected


def test_a_profile_is_unasked_only_with_none_in_force_and_no_choice_recorded(isolated, monkeypatch):
  """Install may still ask only when no profile is found and local.toml has recorded neither a path nor a choice of none."""
  assert profile.unasked()

  profile.DEFAULT.mkdir(parents=True)   # one in force, found by default
  assert not profile.unasked()
  profile.DEFAULT.rmdir()
  assert profile.unasked()

  monkeypatch.setenv("AGENTS_PROFILE", str(isolated / "env"))   # one in force, named by the environment
  assert not profile.unasked()
  monkeypatch.delenv("AGENTS_PROFILE")

  profile.save(None)   # a choice of none: nothing in force, and nothing left to ask
  assert profile.path() is None and not profile.unasked()


def test_a_repo_is_published_when_it_has_a_remote_and_by_default_the_profile_is_the_one_asked_about(isolated, monkeypatch):
  """published is about the repo it is given: a plain directory and a repo with no remote are not, a clone is."""
  (nowhere := isolated / "nowhere").mkdir()
  git.run(isolated, "init", "-q", "-b", "main", str(lone := isolated / "lone"))
  _, clone = published(isolated, "theirs")
  assert [profile.published(where) for where in (nowhere, lone, clone)] == [False, False, True]
  assert not profile.published()   # isolated's default profile, which does not exist
  monkeypatch.setattr(profile, "DEFAULT", clone)   # read when asked, so a test's default is the one checked
  assert profile.published()


def test_publishing_the_profile_makes_a_private_repo_through_gh_and_reports_why_it_could_not(isolated, monkeypatch):
  """publish asks gh for a private repo from the default profile, pushed, and returns one line: made, or FAIL with the last line gh gave."""
  log = fake_gh(isolated, monkeypatch, "exit 0")
  assert profile.publish("tester") == ["  made  tester/.agents.profile, private, and pushed"]
  assert log.read_text() == f"gh repo create tester/.agents.profile --private --source {profile.DEFAULT} --remote origin --push\n"

  for body, said in (('echo "GraphQL: name already exists" >&2; echo "gh: try another name" >&2; exit 1', "gh: try another name"), ('echo "only stdout"; exit 1', "only stdout"), ("exit 1", "gh said nothing")):
    fake_gh(isolated, monkeypatch, body)
    assert profile.publish("tester") == [f"  FAIL  {said}"]

  (isolated / "bare").mkdir()
  monkeypatch.setenv("PATH", str(isolated / "bare"))   # no gh at all
  assert profile.publish("tester") == ["  FAIL  gh is not installed: https://cli.github.com"]


def test_a_missing_default_backend_is_told_as_a_reason_and_as_advice_naming_the_backends(isolated, monkeypatch):
  """unset is only the advice, naming each backend; get exits with UNSET and then the advice, and a named backend needs no default."""
  (isolated / "config.toml").write_text('[backends.claude]\nkind = "cli"\nargv = ["claude"]\n[backends.ollama]\nkind = "http"\nurl = "x"\n')
  monkeypatch.setattr(hub, "CONFIG", isolated / "config.toml")
  assert backends.UNSET == "no default backend is set, so a review has nowhere to run"
  assert backends.unset() == "`agent install --backend <claude|ollama>`, or run this at a terminal to be asked"

  with pytest.raises(SystemExit) as stopped: backends.get()
  assert stopped.value.code == "no default backend is set, so a review has nowhere to run: `agent install --backend <claude|ollama>`, or run this at a terminal to be asked"
  assert backends.get("ollama").name == "ollama"


@pytest.mark.parametrize("before", ['# mine\n[profile]\npath = "/old"\nnote = "keep"\n\n[mine]\nkept = true\n', '[profile]  # mine\n  path = "/old"\nnote = "keep"\n', '[mine]\nkept = true\n', ""])
def test_saving_rewrites_only_the_path(isolated, before):
  """Save changes the `path` line and keeps the file's other tables, keys and comments, whatever characters the path holds."""
  if before: hub.LOCAL.write_text(before)
  saved = isolated / 'odd "quoted" \\ dir'
  saved.mkdir()
  profile.save(saved)

  expected = {**(old := tomllib.loads(before)), "profile": {**old.get("profile", {}), "path": str(saved.resolve())}}
  text = hub.LOCAL.read_text()
  assert tomllib.loads(text) == expected
  assert text.startswith(before.split("path")[0].rstrip(" "))


def test_a_profile_replaces_the_hubs_standards_reviewers_and_backends_by_name_and_layers_its_config(isolated, monkeypatch):
  """A profile's standard, reviewer and backend replace the hub's of the same name, its own are added, and its config sits between the hub's and the repo's."""
  bundled, mine, repo = isolated / "bundled", isolated / "mine", isolated / "repo"
  for directory, name, body in ((bundled, "python", "STARTER"), (mine, "python", "MINE"), (repo, "python", "REPO"), (bundled / "agents", "file-review", "HUB"), (mine / "agents", "file-review", "MINE"), (mine / "agents", "my-check", "MINE TOO")):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(f"---\nname: {name}\ndescription: {name}\napplies: *.py\nkind: logic\n---\n\n{body}\n")
  assert [(layer.origin, layer.doc.body.strip()) for layer in Library(bundled, [repo], profile=mine).layers["python"]] == [("profile", "MINE"), ("repo", "REPO")]
  assert [(layer.origin, layer.header) for layer in Library(bundled, [repo], profile=None).layers["python"]] == [("bundled", "--- python (bundled) ---"), ("repo", "--- python (repo) ---")]

  monkeypatch.setattr(hub, "REVIEWERS", bundled / "agents")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  definitions = agents.definitions(bundled / "agents")
  assert sorted(definitions) == ["file-review", "my-check"]
  assert agents.definition("file-review", definitions).body.strip() == "MINE"

  (bundled / "config.toml").write_text('[review]\nexclude = ["**/vendor/**"]\njobs = 4\n[backends]\ndefault = "claude"\n[backends.claude]\nkind = "cli"\nargv = ["claude"]\nmodels = { text = "hub-model" }\n[backends.ollama]\nkind = "http"\nurl = "x"\n')
  (mine / "config.toml").write_text('[review]\nexclude = "**/data/**"\njobs = 2\n[backends]\ndefault = "ollama"\n[backends.claude]\nkind = "cli"\nargv = ["claude"]\nmodels = { text = "my-model" }\n')
  monkeypatch.setattr(hub, "CONFIG", bundled / "config.toml")
  known, default = backends.load_backends()
  assert default == "ollama" and set(known) == {"claude", "ollama"}
  assert known["claude"].spec["models"]["text"] == "my-model"

  settings = config.section("review", add=("exclude",))
  assert settings["exclude"] == ["**/vendor/**", "**/data/**"] and settings["jobs"] == 2   # a lone string accumulates as a list of one


def test_a_backend_chosen_with_a_profile_takes_effect_over_an_older_local_default(isolated, monkeypatch):
  """With a profile the default goes to its config.toml, and a default local.toml set before there was one, which is read after it, is dropped with the rest of the file kept."""
  (mine := isolated / "mine").mkdir()
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  hub.LOCAL.write_text('[profile]\npath = "x"\n\n[backends]\ndefault = "ollama"\n\n[backends.mine]\nkind = "cli"\n')   # a machine's, from before it had a profile
  assert backends.choose("claude") == mine / "config.toml" and backends.load_backends()[1] == "claude"
  assert hub.LOCAL.read_text() == '[profile]\npath = "x"\n\n[backends]\n\n[backends.mine]\nkind = "cli"\n'
  assert backends.choose("codex") == mine / "config.toml" and backends.load_backends()[1] == "codex" and "default" not in hub.LOCAL.read_text()


def test_a_profile_review_reads_the_profile_the_starters_it_replaces_each_repo_standard_once_and_the_memory_waiting(isolated, monkeypatch):
  """Each file comes with what it is: a starter only when the profile replaces it or layers on it, a repo standard once though two checkouts hold it and once more for another repo holding the same text, and a memory under the directory its project ran in."""
  mine, repo, other, projects = isolated / "mine", repository(isolated / "work" / "my_repo"), repository(isolated / "work" / "other"), isolated / "claude" / "projects"
  commit(repo, "first")
  git.run(repo, "worktree", "add", "-q", str(copy := isolated / "work" / "my_repo-copy"))   # a second checkout of the same repo
  put(mine, "AGENTS.md", text="how I work\n")
  for name in ("python", "markdown.site", "own"): standard(mine / "standards", name)
  for checkout in (repo, copy, other):
    note(checkout)   # a .agents holding only standards is not in the chain, for inject or for this
    standard(checkout / ".agents" / "standards", "python", body="the same override in both")
    (projects / re.sub(r"[^A-Za-z0-9]", "-", str(checkout))).mkdir(parents=True)   # Claude Code's project-folder name for that path
  folder = projects / re.sub(r"[^A-Za-z0-9]", "-", str(repo))
  put(folder, "memory/MEMORY.md", "memory/fact.md")
  put(projects, "-gone/memory/old.md")
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(isolated / "claude"))
  monkeypatch.chdir(isolated)

  found = profile.subject()
  assert found[mine / "AGENTS.md"].startswith("the profile's AGENTS.md") and found[mine / "standards" / "python.md"] == "a profile standard, python, replacing the starter of its name"
  assert found[hub.STANDARDS / "python.md"] == "the starter python, which the profile's replaces whole" and found[hub.STANDARDS / "markdown.md"] == "the starter markdown, which the profile's markdown.site layers on"
  assert hub.STANDARDS / "commits.md" not in found   # a starter the profile leaves alone
  assert found[mine / "standards" / "own.md"] == "a profile standard, own"   # one the hub has no starter for
  assert {path: what for path, what in found.items() if "repo standard" in what} == {checkout / ".agents" / "standards" / "python.md": f"a repo standard, python, for files in {checkout}, layered on the profile's of its name" for checkout in (repo, other)}
  assert found[folder / "memory" / "fact.md"] == f"a memory Claude Code saved for sessions in {repo}" and "no longer exists (-gone)" in found[projects / "-gone" / "memory" / "old.md"]
  assert folder / "memory" / "MEMORY.md" not in found


def test_reviewing_a_fresh_profile_leaves_nothing_in_it_to_commit(isolated, monkeypatch):
  """A new profile's first commit already ignores the reviews `agent profile review` keeps in it, so doctor finds nothing uncommitted after one."""
  mine = isolated / "mine"
  assert ".agents/.gitignore" in profile.init(mine) and profile.drift(mine) == ["no upstream to push to"]
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(isolated / "claude"))   # no memory but the test's
  (stub := Stub()).timeout = 300
  monkeypatch.setattr(backends, "get", lambda *args, **kwargs: stub)
  monkeypatch.chdir(isolated)
  assert cli.main(["profile", "review", "--backend", "stub"]) == 0
  assert reviews.conversations(mine) and profile.drift(mine) == ["no upstream to push to"]


def test_the_pointer_to_your_profile_follows_the_hubs_and_moves_with_the_profile(isolated, monkeypatch):
  """A pointer to the profile's AGENTS.md is appended once after the hub's, and repointing swaps it for the new profile's."""
  monkeypatch.setenv("HOME", str(isolated / "home"))
  first, second = isolated / "first", isolated / "second"
  for directory in (first, second):
    directory.mkdir()
    (directory / "AGENTS.md").write_text("# how I work\n")
  monkeypatch.setenv("AGENTS_PROFILE", str(first))
  claude = isolated / "home" / ".claude" / "CLAUDE.md"
  claude.parent.mkdir(parents=True)

  for start in ("my notes", f"my notes\n\n@{hub.HOME}/AGENTS.md"):
    claude.write_text(start)
    assert "your profile" in install.point_at(claude)[0]
    text = claude.read_text()
    assert text.startswith(start) and text.endswith(f"@{hub.HOME}/AGENTS.md\n@{first}/AGENTS.md\n")
    assert install.point_at(claude)[0].startswith("ok") and claude.read_text() == text

  monkeypatch.setenv("AGENTS_PROFILE", str(second))
  assert install.repoint(first / "AGENTS.md") == ["point .claude/CLAUDE.md at " + install.home(second / "AGENTS.md")]
  assert claude.read_text() == text.replace(f"@{first}/", f"@{second}/")


def test_dropping_the_profile_drops_its_pointers_whole_line(isolated, monkeypatch):
  """With no profile left, repointing removes each line that is only the old pointer, whatever whitespace surrounds it, and nothing else."""
  monkeypatch.setenv("HOME", str(isolated / "home"))
  monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
  monkeypatch.setenv("AGENTS_PROFILE", "")
  (claude := isolated / "home" / ".claude" / "CLAUDE.md").parent.mkdir(parents=True)
  claude.write_text(f"my notes\n@{hub.HOME}/AGENTS.md\n  @{isolated}/old/AGENTS.md \nsee @{isolated}/old/AGENTS.md for why\nafter\n")
  assert install.repoint(isolated / "old" / "AGENTS.md") == ["point .claude/CLAUDE.md at no profile"]
  assert claude.read_text() == f"my notes\n@{hub.HOME}/AGENTS.md\nsee @{isolated}/old/AGENTS.md for why\nafter\n"   # a line that only mentions it is left whole


def test_a_profile_is_adopted_checked_for_drift_updated_and_made(isolated, monkeypatch, capsys):
  """A directory is used in place and a blank name refused, a remote is cloned once and never over a different one, drift names what is unpushed, update fails rather than merge, and init reports only what it made."""
  mine = isolated / "dotfiles"
  mine.mkdir()
  assert profile.adopt(str(mine))[0] == 0 and profile.path() == mine.resolve() and not profile.DEFAULT.exists()
  assert profile.adopt(str(isolated / "nowhere"))[0] == 1
  assert all(profile.adopt(blank)[0] == 1 for blank in ("", "  ")) and profile.path() == mine.resolve()   # a blank name is refused, not taken for the current directory
  assert profile.adopt(" none\n")[0] == 0 and profile.path() is None   # an answer is read without the space around it
  assert profile.adopt(f"  {mine}\n")[0] == 0 and profile.path() == mine.resolve()

  bare, clone = published(isolated, "theirs")   # a path ending .git reads as a remote, as a URL would
  code, said = profile.adopt(str(bare))
  assert code == 0 and "clone" in said and (profile.DEFAULT / ".git").is_dir()
  assert profile.path() == profile.DEFAULT.resolve()
  assert profile.adopt(str(bare))[1].startswith("ok")
  assert "already holds" in profile.adopt(str(published(isolated, "other")[0]))[1]

  commit(clone, "second")
  (clone / "voice.md").write_text("new\n")
  assert profile.drift(clone) == ["1 uncommitted change", "1 commit not pushed"]
  git.run(clone, "update-ref", "-d", "refs/remotes/origin/main")   # an upstream set but not fetched is not no upstream
  assert profile.drift(clone) == ["1 uncommitted change", "its upstream origin/main is gone, or was never fetched"]

  monkeypatch.setattr(hub, "BUNDLED", published(isolated, "agents")[1])
  git.run(clone, "push", "-q")
  assert cli.setup.cmd_update(argparse.Namespace()) == 0
  assert git.run(profile.DEFAULT, "log", "-1", "--format=%s").stdout == "second\n"
  said = capsys.readouterr().out
  assert ".agents: already current" in said and "profile: pulled 1 commit  (" in said

  commit(profile.DEFAULT, "here")
  commit(clone, "there")
  git.run(clone, "push", "-q")
  assert cli.setup.cmd_update(argparse.Namespace()) == 1
  assert "FAIL" in capsys.readouterr().out

  assert ".git" in profile.init(isolated / "new")
  assert (isolated / "new" / "standards").is_dir() and profile.init(isolated / "new") == []
  assert profile.drift(isolated / "new")[-1] == "no upstream to push to"

  fake(isolated, monkeypatch, "git", "exit 1")   # a git that fails whatever it is asked
  assert ".git" not in profile.init(isolated / "failed")


def test_a_default_profile_folder_that_is_no_repo_is_never_read_as_the_repo_around_it(isolated):
  """A clone's profile/ with no .git of its own reports the clone's origin to git; neither the reachability check nor adopt takes that for the profile's."""
  hub_clone, unreachable = repository(isolated / "hub"), str(isolated / "nowhere.git")
  git.run(hub_clone, "remote", "add", "origin", unreachable)   # the hub's origin is the very profile asked for
  profile.DEFAULT.mkdir()
  assert any(problem.startswith(f"cannot reach {unreachable}: ") for problem in install.preflight(unreachable))
  code, said = profile.adopt(unreachable)
  assert code == 1 and said == f"{profile.DEFAULT} already holds something else, not {unreachable}"


def test_doctor_fails_a_public_profile_remote_and_profile_names_a_missing_one(isolated, monkeypatch):
  """doctor asks gh whether a profile's GitHub remote is private and fails it when public; `agent profile` says when there is no remote at all."""
  mine = isolated / "mine"
  git.run(isolated, "init", "-q", "-b", "main", str(mine))
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.chdir(isolated)
  said = agent(["profile"], cwd=isolated).stdout
  assert "no remote, so no other machine gets it" in said and "no upstream" not in said

  log = fake_gh(isolated, monkeypatch, '[[ "$1 $2" == "repo view" ]] && { echo "$GH_PRIVATE"; exit 0; }\nexit 1')
  git.run(mine, "remote", "add", "origin", "git@github.com:someone/.agents.profile.git")
  assert "no remote" not in agent(["profile"], cwd=isolated).stdout
  for private in ("true", "false"):
    monkeypatch.setenv("GH_PRIVATE", private)
    assert [passed for passed, label, _ in doctor.checks() if label == "profile remote someone/.agents.profile is private"] == [private == "true"]
  assert "gh repo view someone/.agents.profile --json isPrivate" in log.read_text()


def test_a_key_is_written_into_its_table_even_when_the_header_ends_the_file(tmp_path):
  """A [table] header on the last line with no newline is found and filled, never added a second time, which TOML refuses."""
  config_file = tmp_path / "config.toml"
  config_file.write_text("[review]\njobs = 2\n\n[backends]")
  config.write(config_file, "backends", "default", "claude")
  assert tomllib.loads(config_file.read_text()) == {"review": {"jobs": 2}, "backends": {"default": "claude"}}


def test_a_key_whose_value_spans_lines_is_replaced_or_dropped_whole(tmp_path):
  """A multi-line array is replaced through its closing bracket, and dropped the same way, leaving the keys after it as they were."""
  config_file = tmp_path / "config.toml"
  config_file.write_text('[walk]\nskip = [\n  "node_modules",  # theirs\n  ".venv",\n]\nafter = 1\n\n[other]\nkept = true\n')
  config.write(config_file, "walk", "skip", "build")
  assert config_file.read_text() == '[walk]\nskip = "build"\nafter = 1\n\n[other]\nkept = true\n'

  config_file.write_text('[walk]\nskip = [\n  "node_modules",\n]\nafter = 1\n')
  config.write(config_file, "walk", "skip", None)
  assert config_file.read_text() == "[walk]\nafter = 1\n"


def test_a_write_replaces_the_file_whole_or_leaves_it_as_it_was(tmp_path, monkeypatch):
  """The new text lands beside the file and is renamed over it, through a link that stays a link; a write that fails first leaves the file and nothing else."""
  (real := tmp_path / "dotfiles" / "config.toml").parent.mkdir()
  real.write_text("[review]\njobs = 2\n")
  real.chmod(0o640)
  (linked := tmp_path / "config.toml").symlink_to(real)
  config.write(linked, "backends", "default", "claude")
  assert linked.is_symlink() and tomllib.loads(real.read_text())["backends"] == {"default": "claude"} and real.stat().st_mode & 0o777 == 0o640

  monkeypatch.setattr(config.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
  with pytest.raises(OSError, match="disk full"): config.write(linked, "backends", "default", "codex")
  assert tomllib.loads(real.read_text())["backends"] == {"default": "claude"} and sorted(path.name for path in real.parent.iterdir()) == ["config.toml"]
