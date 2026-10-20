"""Tests for the stored reviews, the messages the person reads, and a review run as it is watched.

Author: Marco Cassar (@Ocramaru)
"""

import subprocess, threading
from contextlib import nullcontext

import pytest
from conftest import Stub, findings, git, note, put, record, run_review

from agentkit import agents, cli, command, doctor, git as agentkit_git, hooks, inject, review, reviews
from agentkit.cli import out, show


def test_the_reviews_lose_no_record_and_keep_no_half_written_review(reviewable_repo, monkeypatch):
  """Queued records land in order, a failed one costs only itself, a store that cannot open raises, and a review lands with its findings or not at all."""
  duckdb = pytest.importorskip("duckdb")
  with reviews.writer(reviewable_repo) as put_row:
    for index in range(6): put_row(record(reviewable_repo, f"t{index}", f"f{index}.py", [{"line": index, "issue": f"bad {index}"}]))
  rows = reviews.conversations(reviewable_repo)
  assert len(rows) == 6 and [row["id"] for row in rows] == sorted(row["id"] for row in rows)   # uuid7 orders itself
  assert (reviewable_repo / ".agents" / ".gitignore").read_text().splitlines() == [".reviews/", ".local/"]

  held, real_connect, real_insert = threading.Event(), reviews.connect, reviews._insert
  monkeypatch.setattr(reviews, "connect", lambda *args, **kwargs: (held.wait(5), real_connect(*args, **kwargs))[1])   # the writer waits on the first record while the other two queue behind it
  monkeypatch.setattr(reviews, "_insert", lambda connection, row: (_ for _ in ()).throw(ValueError("bad row")) if row["task"] == "u1" else real_insert(connection, row))
  with pytest.raises(ValueError, match="bad row"), reviews.writer(reviewable_repo) as put_row:
    for index in range(3): put_row(record(reviewable_repo, f"u{index}", f"g{index}.py", []))
    held.set()
  assert sorted(row["task"] for row in reviews.conversations(reviewable_repo) if row["task"].startswith("u")) == ["u0", "u2"]

  same = reviews.uuid7()
  monkeypatch.setattr(reviews, "uuid7", lambda: same)   # two findings with one id: the second insert fails
  with pytest.raises(duckdb.ConstraintException): reviews.write(record(reviewable_repo, "half", "mod.py", [{"line": 1, "issue": "first"}, {"line": 2, "issue": "second"}]), reviewable_repo)
  assert "half" not in [row["task"] for row in reviews.conversations(reviewable_repo)]

  monkeypatch.setattr(reviews, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no duckdb")))
  with pytest.raises(RuntimeError, match="no duckdb"), reviews.writer(reviewable_repo) as put_row: put_row({"id": "x"})


def test_open_findings_are_the_newest_verdict_on_a_file_that_still_has_content(reviewable_repo):
  """A newer verdict supersedes, an emptied or deleted file has none, and old rows and old reviews still read."""
  duckdb = pytest.importorskip("duckdb")
  module, second = put(reviewable_repo, "mod.py", "a.py")
  reviews.write(record(reviewable_repo, "t", "mod.py", [{"line": 1, "issue": "backwards"}]), reviewable_repo)
  with duckdb.connect(str(reviews.path(reviewable_repo))) as connection: connection.execute("drop table closures")   # reviews with no closures table
  assert reviews.dismissals(reviewable_repo) == {}
  assert [finding["issue"] for finding in inject.open_findings(module)] == ["backwards"]

  reviews.write(record(reviewable_repo, "t", "mod.py", [], "clean now"), reviewable_repo)
  assert reviews.open_findings(reviewable_repo) == [] and inject.open_findings(module) == []
  assert reviews.conversation(reviews.latest("t", reviewable_repo)).messages   # and still resumable

  stored = record(reviewable_repo, "t-a", "a.py", [{"line": "133, 136 vs 137", "issue": "real"}, {"line": 9, "issue": "   "}])
  stored["findings"][0]["file"] = str(second)   # a model echoes a path as it likes
  stored["findings"][1]["file"] = "a.py"
  reviews.write(stored, reviewable_repo)
  assert [(finding["file"], finding["issue"]) for finding in reviews.open_findings(reviewable_repo)] == [("a.py", "real")]
  assert reviews.first_line("133, 136 vs 137-139") == 133
  second.unlink()
  assert reviews.open_findings(reviewable_repo) == [] and reviews.to_recheck(reviewable_repo) == {}

  backend = Stub(findings({"line": 1, "issue": "x is unused", "fix": "drop it"}))
  for text, opened in (("x = 1\n", True), ("", False)):   # a file emptied since its review has no open findings
    module.write_text(text)
    run_review("file-review", backend, [module], reviewable_repo, role="code")
    assert bool(reviews.open_findings(reviewable_repo)) == opened


def test_a_finding_closes_by_line_range_or_id_and_only_wrong_is_passed_back(reviewable_repo):
  """`wrong` tells the next reviewer and `fixed` stays on the recheck list until a verdict lands after it."""
  put(reviewable_repo, "a.py", "mod.py", "o.py", "c.py", "abcdef")
  reviews.write(record(reviewable_repo, "t-a", "a.py", [{"line": 9, "issue": "backwards"}, {"line": 12, "issue": "stale comment"}]), reviewable_repo)
  assert [closure["issue"] for closure in reviews.close(reviewable_repo, "a.py", 9, "wrong", "lower is better here, the comparison is right")] == ["backwards"]
  assert [finding["issue"] for finding in reviews.open_findings(reviewable_repo)] == ["stale comment"]
  quiet, backend = reviews.dismissals(reviewable_repo)["a.py"], Stub()
  review.file("file-review", backend, reviewable_repo / "a.py", agents.definition("file-review", agents.definitions()), "text", reviewable_repo, quiet, libraries={})
  assert quiet[0]["reason"].startswith("lower is better")
  assert "backwards" in backend.shown[-1] and "closed as wrong" in backend.shown[-1]
  reviews.close(reviewable_repo, "a.py", 0, "fixed")
  assert reviews.open_findings(reviewable_repo) == []
  assert list(reviews.dismissals(reviewable_repo)) == ["a.py"]   # only the one closed as wrong

  reviews.write(record(reviewable_repo, "t-mod", "mod.py", [{"line": "12-14", "issue": "first"}, {"line": 30, "issue": "second"}, {"line": "40-41", "issue": "third"}, {"line": 168, "issue": "fourth"}, {"line": 200, "issue": "fifth"}]), reviewable_repo)
  issues = lambda target, line=0: [finding["issue"] for finding in reviews.close(reviewable_repo, target, line, "fixed")]
  assert issues("mod.py", 12) == ["first"]
  assert issues("mod.py", 30) == ["second"]
  assert issues("mod.py", 40) == ["third"]
  assert issues("mod.py", 163) == []   # where an edit moved it: no match
  assert issues(reviews.short_id(next(finding for finding in reviews.open_findings(reviewable_repo) if finding["issue"] == "fourth")["id"])) == ["fourth"]
  assert issues("mod.py") == ["fifth"]

  for name in ("o.py", "c.py"): reviews.write(record(reviewable_repo, f"t-{name}", name, [{"line": 1, "issue": "x"}]), reviewable_repo)
  reviews.close(reviewable_repo, "c.py", 0, "wrong", "it is right")
  assert cli.main(["sub", "close", "o.py:1-2", "--as", "fixed", "--root", str(reviewable_repo)]) == 0   # the command reads a line the way reviewers write one
  assert reviews.to_recheck(reviewable_repo) == {"file-review": ["a.py", "mod.py", "o.py"]}
  for name in ("a", "mod"): reviews.write(record(reviewable_repo, f"t-{name}", f"{name}.py", [], "clean"), reviewable_repo)
  assert reviews.to_recheck(reviewable_repo) == {"file-review": ["o.py"]}   # the claims have been checked

  reviews.write(record(reviewable_repo, "t-id", "abcdef", [{"line": 1, "issue": "named like an id"}]), reviewable_repo)
  assert issues("abcdef") == ["named like an id"]   # a file named like a finding id is closed by its name


def test_a_dismissal_made_in_a_worktree_reaches_the_main_checkout_and_nothing_else_does(reviewable_repo, tmp_path_factory, monkeypatch, capsys):
  """Wrong and wontfix land in both checkouts' reviews and each review reads them once, open findings and fixed stay put, and an import adds only what is missing."""
  duckdb = pytest.importorskip("duckdb")
  main, elsewhere = reviewable_repo, tmp_path_factory.mktemp("elsewhere")
  run = lambda *args, cwd=main: subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t.io", *args], cwd=cwd, check=True, capture_output=True)
  put(main, "a.py", "mod.py")
  run("add", "-A")
  run("commit", "-qm", "init")
  run("worktree", "add", "-q", ".claude/worktrees/feature")   # where the hub's own worktrees live, inside the main checkout
  run("clone", "-q", "--bare", ".", "bare.git")   # a bare repo inside a checkout is not that checkout's
  run("worktree", "add", "-q", str(elsewhere / "bare-worktree"), cwd=main / "bare.git")
  run("clone", "-q", "--bare", ".", str(elsewhere / "hidden" / ".git"))   # a bare repo kept in .git has no work tree
  run("worktree", "add", "-q", str(elsewhere / "hidden-worktree"), cwd=elsewhere / "hidden" / ".git")
  linked = main / ".claude" / "worktrees" / "feature"
  assert agentkit_git.main_checkout(linked) == main.resolve() and agentkit_git.main_checkout(main) is None
  assert agentkit_git.main_checkout(elsewhere / "bare-worktree") is None and agentkit_git.main_checkout(elsewhere / "hidden-worktree") is None

  with duckdb.connect(str(reviews.path(main))) as connection: connection.execute(reviews.SCHEMA + "alter table closures add column note text;")   # the main checkout's reviews on a newer schema
  reviews.write(record(linked, "t-a", "a.py", [{"line": 1, "issue": "backwards"}, {"line": 2, "issue": "stale comment"}, {"line": 3, "issue": "typo"}]), linked)
  reviews.close(linked, "a.py", 1, "wrong", "lower is better here")
  reviews.close(linked, "a.py", 3, "fixed")
  assert [finding["issue"] for finding in reviews.open_findings(linked)] == ["stale comment"]
  assert reviews.open_findings(main) == [] and [row["verdict"] for row in reviews.query(main, "select verdict from closures")] == ["wrong"]
  backend = Stub()
  run_review("file-review", backend, [main / "a.py"], main, role="code")
  assert "backwards (closed as wrong: lower is better here)" in backend.shown[-1] and "stale comment" not in backend.shown[-1]

  reviews.write(record(main, "t-m", "mod.py", [{"line": 4, "issue": "unused"}]), main)
  reviews.close(main, "mod.py", 0, "wontfix", "kept on purpose")
  assert {file: [row["issue"] for row in rows] for file, rows in reviews.dismissals(linked).items()} == {"a.py": ["backwards"], "mod.py": ["unused"]}   # main's too, and its own once

  with monkeypatch.context() as patch:   # closed as it was before dismissals travelled
    patch.setattr(agentkit_git, "main_checkout", lambda directory: None)
    reviews.close(linked, "a.py", 2, "wontfix", "the comment is current")
  source = str(reviews.path(linked, create=False))
  assert cli.main(["sub", "import", source, "--root", str(main)]) == 0
  printed = capsys.readouterr().out
  assert "added a.py:2 as wontfix  stale comment" in printed and "1 dismissal added" in printed and "1 already there" in printed
  assert cli.main(["sub", "import", source, "--root", str(main)]) == 0 and "0 dismissals added" in capsys.readouterr().out
  assert {file: [row["issue"] for row in rows] for file, rows in reviews.dismissals(main).items()} == {"a.py": ["backwards", "stale comment"], "mod.py": ["unused"]}
  assert sorted(row["verdict"] for row in reviews.query(main, "select verdict from closures")) == ["wontfix", "wontfix", "wrong"]   # never the fix

  with duckdb.connect(str(elsewhere / "old.duckdb")) as connection: connection.execute("create table reviews (id text)")   # reviews from before closures
  assert cli.main(["sub", "import", str(elsewhere / "old.duckdb"), "--root", str(main)]) == 0 and "0 dismissals added" in capsys.readouterr().out
  assert cli.main(["sub", "import", str(elsewhere / "nope.duckdb")]) == 2


def test_what_the_person_is_told_arrives_whole(reviewable_repo, capsys, monkeypatch):
  """The hook log reads back by session and parses into columns, model text survives the table and the pipe, and a duplicate command name is refused."""
  log = reviewable_repo / "h.log"
  log.write_text("t1\tinject\tabc12345\tsent 10 bytes\nt2\tforget\tabc12345\tcleared 2 stamps\nt3\tinject\tzz999999\tsent 20 bytes\n")
  assert len(hooks.entries(log=log)) == 3
  assert [row[1] for row in hooks.entries(session="abc12345", log=log)] == ["inject", "forget"]
  assert hooks.entries(session="abc123", log=log)   # a prefix is enough
  assert [row[0] for row in hooks.entries(hook="forget", log=log)] == ["t2"]
  assert hooks.entries(log=reviewable_repo / "nope.log") == []

  log.write_text("2026-09-21T17:34:37-05:00\tinject\tabc12345\tsent   7445 bytes  /x/y.py\nnot a log line at all\n")
  hooks.log("post-commit", "git", "done   project: 2 findings in 3 reviews", log=log)
  rows = hooks.entries(log=log)
  assert rows[0] == ["2026-09-21T17:34:37-05:00", "inject", "abc12345", "sent", "7445 bytes  /x/y.py"]
  assert rows[1][-1] == "not a log line at all"   # nothing is dropped for being unparseable
  assert rows[2][1:4] == ["post-commit", "git", "done"] and "2 findings" in rows[2][4]

  text = "Uses `[learned.md](learned.md)` instead of wikilink `[[learned]]`"
  assert out.plain(out.escape(text)) == text   # rich reads `[[context]]` as markup
  assert [out.took(seconds) for seconds in (42, 59.6, 185)] == ["42s", "1m00s", "3m05s"]
  assert out.plain("[dim]code-large[/dim]") == "code-large"
  put(reviewable_repo, "mod.py")
  long = "First sentence. " + "word " * 60
  reviews.write(record(reviewable_repo, "t", "mod.py", [{"line": 1, "issue": long}]), reviewable_repo)
  show.findings(reviews.open_findings(reviewable_repo))
  row = capsys.readouterr().out.strip().split("\t")
  assert row[3] == " ".join(long.split()) and row[4] == reviews.short_id(reviews.open_findings(reviewable_repo)[0]["id"])

  monkeypatch.setattr(command, "COMMANDS", list(command.COMMANDS))
  command.command("only-once")(lambda args: 0)
  with pytest.raises(ValueError, match="already registered"): command.command("only-once")(lambda args: 0)


def test_doctor_names_a_bad_setting_and_judges_format_on_save_and_hook_errors(tmp_path, monkeypatch):
  """A typo or a missing standard is named, format-on-save is flagged only when on, and a hook error counts only since agents last changed."""
  repo, plain = git(tmp_path / "repo"), tmp_path / "plain"
  (note(repo) / "agents.toml").write_text('inject = "ful"\n\n[applies]\nnosuch = ["mod.py"]\n')
  monkeypatch.chdir(repo)
  failed = [label for passed, label, _ in doctor.checks() if not passed]
  assert f"{repo.name}/agents.toml inject = 'ful'" in failed and f"{repo.name}/agents.toml applies -> nosuch" in failed
  (repo / ".agents" / "agents.toml").write_text('inject = "full",\n')   # a trailing comma, as a hand edit leaves one
  (passed, label, fix), = [check for check in doctor.checks() if "parses" in check[1]]
  assert not passed and label.endswith("agents.toml parses as TOML") and fix.startswith("fix it: ")
  (repo / ".agents" / "agents.toml").unlink()

  for where, setting, enabled in ((repo, '"editor.formatOnSave": true', True), (repo, '"editor.formatOnSave": false', False), (plain, '// "editor.formatOnSave": true,\n  "a": 1', False)):   # plain is outside any repo
    put(where, ".vscode/settings.json", text=f'{{\n  // mine\n  {setting}\n}}')
    monkeypatch.chdir(where)
    assert [passed for passed, label, _ in doctor.checks() if "format-on-save" in label] == [not enabled], setting

  monkeypatch.setattr(hooks, "entries", lambda: [["2000-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "stale"], ["2100-01-01T09:00:00+0000", "inject", "abc12345", "sent", "2 standards"]])
  assert [passed for passed, label, _ in doctor.checks() if "hook errors" in label] == [True]
  monkeypatch.setattr(hooks, "entries", lambda: [["2100-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "jq: parse error"]])
  (passed, _, fix), = [check for check in doctor.checks() if "hook errors" in check[1]]
  assert not passed and fix.startswith("1 logged, the latest from inject: jq: parse error")


def test_a_run_reports_each_file_as_it_finishes_under_its_own_name(reviewable_repo, monkeypatch):
  """An empty file is never sent, a slow one holds back nothing, and a finding, a failure or a failed write to the reviews keeps the file's report."""
  backend = Stub()
  results = run_review("file-review", backend, put(reviewable_repo, "__init__.py", text="") + put(reviewable_repo, "blank.py", text="\n   \n"), reviewable_repo, role="code")
  assert backend.shown == []
  assert {(row["file"], row["state"], row["body"]) for row in results} == {("__init__.py", "completed", review.EMPTY), ("blank.py", "completed", review.EMPTY)}

  slow, quick = put(reviewable_repo, "slow.py", text="# SLOW\nx = 1\n") + put(reviewable_repo, "quick.py")
  started, landed = [], []
  run_review("file-review", Stub(), [slow, quick], reviewable_repo, role="code", on_start=started.append, on_done=lambda row: landed.append(row["file"]))
  assert sorted(started) == ["quick.py", "slow.py"] and landed == ["quick.py", "slow.py"]

  result, stored = review.file("file-review", Stub(findings({"file": "/somewhere/else.py", "line": 2, "issue": "backwards"})), quick, agents.definition("file-review", agents.definitions()), "text", reviewable_repo, libraries={})
  assert [finding["file"] for finding in result["findings"]] == [finding["file"] for finding in stored["findings"]] == ["quick.py"]
  outside = reviewable_repo.parent / "elsewhere" / "b.py"
  assert review.label(outside, reviewable_repo) == str(outside)   # outside the root keeps a usable name

  landed.clear()
  with monkeypatch.context() as patch:
    patch.setattr(reviews, "writer", lambda root: nullcontext(lambda row: (_ for _ in ()).throw(OSError("disk full"))))
    with pytest.raises(OSError, match="disk full"): run_review("file-review", Stub(), put(reviewable_repo, "mod.py"), reviewable_repo, role="code", on_done=lambda row: landed.append(row["state"]))
  assert landed == ["completed"]   # reported before its record could not be queued

  monkeypatch.setattr(review, "file", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
  row, = run_review("file-review", Stub(), [quick], reviewable_repo, role="code")
  assert row["file"] == "quick.py" and row["state"] == "failed" and "boom" in row["body"]


def test_a_run_is_tagged_so_it_can_be_found_filtered_and_reused(reviewable_repo):
  """A run is found by id, path or kind; only an edited file is asked again, unless the effort differs or --fresh."""
  assert {name: definition.get("effort") for name, definition in agents.definitions().items()} == {name: "medium" for name in agents.definitions()}
  backend, (net, load, readme) = Stub(), put(reviewable_repo, "src/models/net.py", "src/data/load.py", "README.md")
  run_review("file-review", backend, [net], reviewable_repo, role="code", run="1003-0101-aaaa")
  run_review("file-review", backend, [load, readme], reviewable_repo, role="code", run="1003-0102-bbbb")
  assert len(backend.shown) == 3 and {effort for _, effort in backend.asked} == {"medium"}   # the definition's effort
  assert reviews.last_run(reviewable_repo) == "1003-0102-bbbb"

  found = lambda **kwargs: sorted(row["file"] for row in reviews.filtered(reviews.conversations(reviewable_repo), reviewable_repo, **kwargs))
  for kwargs, expected in (({"run": "1003-0101"}, ["src/models/net.py"]), ({"run": "1003-0102"}, ["README.md", "src/data/load.py"]), ({"path": "src/"}, ["src/data/load.py", "src/models/net.py"]), ({"path": "src/models"}, ["src/models/net.py"]), ({"path": "*.md"}, ["README.md"]), ({"failed": True}, [])):
    assert found(**kwargs) == expected, kwargs
  assert found(agent="logic") == found(agent="file-review")   # a kind or its agent

  load.write_text("y = 3\n")
  by_file = {row["file"]: row for row in run_review("file-review", backend, [net, load], reviewable_repo, role="code", run="1003-0103-cccc")}
  assert len(backend.shown) == 4   # only the edited file was asked
  assert by_file["src/models/net.py"]["reused"] == "1003-0101-aaaa" and not by_file["src/data/load.py"].get("reused")
  for kwargs, asked in (({"effort": "low"}, 6), ({"effort": "low", "fresh": True}, 8)):   # the command's effort overrides, and --fresh asks again
    run_review("file-review", backend, [net, load], reviewable_repo, role="code", **kwargs)
    assert len(backend.shown) == asked and backend.asked[-1][1] == "low"


def test_a_review_names_what_it_skipped_and_a_listing_defaults_to_where_you_stand(reviewable_repo, monkeypatch, capsys):
  """Files no standard covers are named, --open from a folder shows that folder, `--tail 0` lists nothing and a bad `--commit` is named."""
  tool = reviewable_repo / "tool"
  for name, text in (("install.sh", "#!/usr/bin/env bash\n"), ("README.md", "# t\n"), ("dotfiles/tmux.conf", "set -g mouse off\n")): put(tool, name, text=text)
  subprocess.run(["git", "add", "-A"], cwd=reviewable_repo, check=True)   # discovery reads what git tracks
  monkeypatch.chdir(tool)
  cli.main(["sub", "review", ".", "--dry-run"])
  printed = capsys.readouterr()
  assert "file-review" in printed.out and "tool/install.sh" in printed.out   # shell scripts route to both reviewers
  assert "not reviewed, no standard covers them: 1 file (.conf 1) in tool/dotfiles/ 1" in printed.err
  assert "agent sub review logic dotfiles/tmux.conf" in printed.err   # a path that works from here

  put(reviewable_repo, "top.py")
  for task, file, issue in (("t-top", "top.py", "elsewhere"), ("t-here", "tool/install.sh", "here")): reviews.write(record(reviewable_repo, task, file, [{"line": 1, "issue": issue}]), reviewable_repo)
  open_here = lambda *extra: (cli.main(["sub", "reviews", "--open", *extra]), capsys.readouterr())[1]
  scoped = open_here()
  assert "here" in scoped.out and "elsewhere" not in scoped.out and "under tool/" in scoped.err
  assert "elsewhere" in open_here("--all").out

  assert cli.main(["sub", "reviews", "--tail", "1"]) == 0 and "install.sh" in capsys.readouterr().out
  assert cli.main(["sub", "reviews", "--tail", "0"]) == 0 and capsys.readouterr().out == ""
  assert cli.main(["sub", "review", "simplify", "--commit", "nosuchref", "--dry-run"]) == 2
  assert "git could not read nosuchref" in capsys.readouterr().err
  assert cli.main(["sub", "review", "--recheck", "--commit", "HEAD"]) == 2
  assert "use one" in capsys.readouterr().err
