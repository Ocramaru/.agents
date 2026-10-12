"""Tests for the review ledger, the messages the person reads, and a review run as it is watched.

Author: Marco Cassar (@Ocramaru)
"""

import subprocess, threading
from contextlib import nullcontext

import pytest
from conftest import Stub, findings, git, note, put, record, run_review

from agentkit import agents, cli, command, doctor, hooks, inject, review, reviews
from agentkit.cli import out, show


def test_the_ledger_loses_no_record_and_keeps_no_half_written_review(ledger, monkeypatch):
  """Queued records land in order, a failed one costs only itself, a store that cannot open raises, and a review lands with its findings or not at all."""
  duckdb = pytest.importorskip("duckdb")
  with reviews.writer(ledger) as put_row:
    for index in range(6): put_row(record(ledger, f"t{index}", f"f{index}.py", [{"line": index, "issue": f"bad {index}"}]))
  rows = reviews.conversations(ledger)
  assert len(rows) == 6 and [row["id"] for row in rows] == sorted(row["id"] for row in rows)   # uuid7 orders itself
  assert (ledger / ".agents" / ".gitignore").read_text().splitlines() == [".reviews/", ".local/"]

  held, real_connect, real_insert = threading.Event(), reviews.connect, reviews._insert
  monkeypatch.setattr(reviews, "connect", lambda *args, **kwargs: (held.wait(5), real_connect(*args, **kwargs))[1])   # the writer waits on the first record while the other two queue behind it
  monkeypatch.setattr(reviews, "_insert", lambda connection, row: (_ for _ in ()).throw(ValueError("bad row")) if row["task"] == "u1" else real_insert(connection, row))
  with pytest.raises(ValueError, match="bad row"), reviews.writer(ledger) as put_row:
    for index in range(3): put_row(record(ledger, f"u{index}", f"g{index}.py", []))
    held.set()
  assert sorted(row["task"] for row in reviews.conversations(ledger) if row["task"].startswith("u")) == ["u0", "u2"]

  same = reviews.uuid7()
  monkeypatch.setattr(reviews, "uuid7", lambda: same)   # two findings with one id: the second insert fails
  with pytest.raises(duckdb.ConstraintException): reviews.write(record(ledger, "half", "mod.py", [{"line": 1, "issue": "first"}, {"line": 2, "issue": "second"}]), ledger)
  assert "half" not in [row["task"] for row in reviews.conversations(ledger)]

  monkeypatch.setattr(reviews, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no duckdb")))
  with pytest.raises(RuntimeError, match="no duckdb"), reviews.writer(ledger) as put_row: put_row({"id": "x"})


def test_open_findings_are_the_newest_verdict_on_a_file_that_still_has_content(ledger):
  """A newer verdict supersedes, an emptied or deleted file has none, and old rows and old ledgers still read."""
  duckdb = pytest.importorskip("duckdb")
  module, second = put(ledger, "mod.py", "a.py")
  reviews.write(record(ledger, "t", "mod.py", [{"line": 1, "issue": "backwards"}]), ledger)
  with duckdb.connect(str(reviews.path(ledger))) as connection: connection.execute("drop table closures")   # a ledger with no closures table
  assert reviews.dismissals(ledger) == {}
  assert [finding["issue"] for finding in inject.open_findings(module)] == ["backwards"]

  reviews.write(record(ledger, "t", "mod.py", [], "clean now"), ledger)
  assert reviews.open_findings(ledger) == [] and inject.open_findings(module) == []
  assert reviews.conversation(reviews.latest("t", ledger)).messages   # and still resumable

  stored = record(ledger, "t-a", "a.py", [{"line": "133, 136 vs 137", "issue": "real"}, {"line": 9, "issue": "   "}])
  stored["findings"][0]["file"] = str(second)   # a model echoes a path as it likes
  stored["findings"][1]["file"] = "a.py"
  reviews.write(stored, ledger)
  assert [(finding["file"], finding["issue"]) for finding in reviews.open_findings(ledger)] == [("a.py", "real")]
  assert reviews.first_line("133, 136 vs 137-139") == 133
  second.unlink()
  assert reviews.open_findings(ledger) == [] and reviews.to_recheck(ledger) == {}

  backend = Stub(findings({"line": 1, "issue": "x is unused", "fix": "drop it"}))
  for text, opened in (("x = 1\n", True), ("", False)):   # a file emptied since its review has no open findings
    module.write_text(text)
    run_review("file-review", backend, [module], ledger, tier="code")
    assert bool(reviews.open_findings(ledger)) == opened


def test_a_finding_closes_by_line_range_or_id_and_only_wrong_is_passed_back(ledger):
  """`wrong` tells the next reviewer and `fixed` stays on the recheck list until a verdict lands after it."""
  put(ledger, "a.py", "mod.py", "o.py", "c.py", "abcdef")
  reviews.write(record(ledger, "t-a", "a.py", [{"line": 9, "issue": "backwards"}, {"line": 12, "issue": "stale comment"}]), ledger)
  assert [closure["issue"] for closure in reviews.close(ledger, "a.py", 9, "wrong", "lower is better here, the comparison is right")] == ["backwards"]
  assert [finding["issue"] for finding in reviews.open_findings(ledger)] == ["stale comment"]
  quiet, backend = reviews.dismissals(ledger)["a.py"], Stub()
  review.file("file-review", backend, ledger / "a.py", agents.definition("file-review", agents.definitions()), "text", ledger, quiet, libraries={})
  assert quiet[0]["reason"].startswith("lower is better")
  assert "backwards" in backend.shown[-1] and "closed as wrong" in backend.shown[-1]
  reviews.close(ledger, "a.py", 0, "fixed")
  assert reviews.open_findings(ledger) == []
  assert list(reviews.dismissals(ledger)) == ["a.py"]   # only the one closed as wrong

  reviews.write(record(ledger, "t-mod", "mod.py", [{"line": "12-14", "issue": "first"}, {"line": 30, "issue": "second"}, {"line": "40-41", "issue": "third"}, {"line": 168, "issue": "fourth"}, {"line": 200, "issue": "fifth"}]), ledger)
  issues = lambda target, line=0: [finding["issue"] for finding in reviews.close(ledger, target, line, "fixed")]
  assert issues("mod.py", 12) == ["first"]
  assert issues("mod.py", 30) == ["second"]
  assert issues("mod.py", 40) == ["third"]
  assert issues("mod.py", 163) == []   # where an edit moved it: no match
  assert issues(reviews.short_id(next(finding for finding in reviews.open_findings(ledger) if finding["issue"] == "fourth")["id"])) == ["fourth"]
  assert issues("mod.py") == ["fifth"]

  for name in ("o.py", "c.py"): reviews.write(record(ledger, f"t-{name}", name, [{"line": 1, "issue": "x"}]), ledger)
  reviews.close(ledger, "c.py", 0, "wrong", "it is right")
  assert cli.main(["sub", "close", "o.py:1-2", "--as", "fixed", "--root", str(ledger)]) == 0   # the command reads a line the way reviewers write one
  assert reviews.to_recheck(ledger) == {"file-review": ["a.py", "mod.py", "o.py"]}
  for name in ("a", "mod"): reviews.write(record(ledger, f"t-{name}", f"{name}.py", [], "clean"), ledger)
  assert reviews.to_recheck(ledger) == {"file-review": ["o.py"]}   # the claims have been checked

  reviews.write(record(ledger, "t-id", "abcdef", [{"line": 1, "issue": "named like an id"}]), ledger)
  assert issues("abcdef") == ["named like an id"]   # a file named like a finding id is closed by its name


def test_what_the_person_is_told_arrives_whole(ledger, capsys, monkeypatch):
  """The hook log reads back by session and parses into columns, model text survives the table and the pipe, and a duplicate command name is refused."""
  log = ledger / "h.log"
  log.write_text("t1\tinject\tabc12345\tsent 10 bytes\nt2\tforget\tabc12345\tcleared 2 stamps\nt3\tinject\tzz999999\tsent 20 bytes\n")
  assert len(hooks.entries(log=log)) == 3
  assert [row[1] for row in hooks.entries(session="abc12345", log=log)] == ["inject", "forget"]
  assert hooks.entries(session="abc123", log=log)   # a prefix is enough
  assert [row[0] for row in hooks.entries(hook="forget", log=log)] == ["t2"]
  assert hooks.entries(log=ledger / "nope.log") == []

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
  put(ledger, "mod.py")
  long = "First sentence. " + "word " * 60
  reviews.write(record(ledger, "t", "mod.py", [{"line": 1, "issue": long}]), ledger)
  show.findings(reviews.open_findings(ledger))
  row = capsys.readouterr().out.strip().split("\t")
  assert row[3] == " ".join(long.split()) and row[4] == reviews.short_id(reviews.open_findings(ledger)[0]["id"])

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

  for where, setting, enabled in ((repo, '"editor.formatOnSave": true', True), (repo, '"editor.formatOnSave": false', False), (plain, '// "editor.formatOnSave": true,\n  "a": 1', False)):   # plain is outside any repo
    put(where, ".vscode/settings.json", text=f'{{\n  // mine\n  {setting}\n}}')
    monkeypatch.chdir(where)
    assert [passed for passed, label, _ in doctor.checks() if "format-on-save" in label] == [not enabled], setting

  monkeypatch.setattr(hooks, "entries", lambda: [["2000-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "stale"], ["2100-01-01T09:00:00+0000", "inject", "abc12345", "sent", "2 standards"]])
  assert [passed for passed, label, _ in doctor.checks() if "hook errors" in label] == [True]
  monkeypatch.setattr(hooks, "entries", lambda: [["2100-01-01T09:00:00+0000", "inject", "abc12345", "ERROR", "jq: parse error"]])
  (passed, _, fix), = [check for check in doctor.checks() if "hook errors" in check[1]]
  assert not passed and fix.startswith("1 logged, the latest from inject: jq: parse error")


def test_a_run_reports_each_file_as_it_finishes_under_its_own_name(ledger, monkeypatch):
  """An empty file is never sent, a slow one holds back nothing, and a finding, a failure or a full ledger keeps the file's report."""
  backend = Stub()
  results = run_review("file-review", backend, put(ledger, "__init__.py", text="") + put(ledger, "blank.py", text="\n   \n"), ledger, tier="code")
  assert backend.shown == []
  assert {(row["file"], row["state"], row["body"]) for row in results} == {("__init__.py", "completed", review.EMPTY), ("blank.py", "completed", review.EMPTY)}

  slow, quick = put(ledger, "slow.py", text="# SLOW\nx = 1\n") + put(ledger, "quick.py")
  started, landed = [], []
  run_review("file-review", Stub(), [slow, quick], ledger, tier="code", on_start=started.append, on_done=lambda row: landed.append(row["file"]))
  assert sorted(started) == ["quick.py", "slow.py"] and landed == ["quick.py", "slow.py"]

  result, stored = review.file("file-review", Stub(findings({"file": "/somewhere/else.py", "line": 2, "issue": "backwards"})), quick, agents.definition("file-review", agents.definitions()), "text", ledger, libraries={})
  assert [finding["file"] for finding in result["findings"]] == [finding["file"] for finding in stored["findings"]] == ["quick.py"]
  outside = ledger.parent / "elsewhere" / "b.py"
  assert review.label(outside, ledger) == str(outside)   # outside the root keeps a usable name

  landed.clear()
  with monkeypatch.context() as patch:
    patch.setattr(reviews, "writer", lambda root: nullcontext(lambda row: (_ for _ in ()).throw(OSError("ledger full"))))
    with pytest.raises(OSError, match="ledger full"): run_review("file-review", Stub(), put(ledger, "mod.py"), ledger, tier="code", on_done=lambda row: landed.append(row["state"]))
  assert landed == ["completed"]   # reported before its record could not be queued

  monkeypatch.setattr(review, "file", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
  row, = run_review("file-review", Stub(), [quick], ledger, tier="code")
  assert row["file"] == "quick.py" and row["state"] == "failed" and "boom" in row["body"]


def test_a_run_is_tagged_so_it_can_be_found_filtered_and_reused(ledger):
  """A run is found by id, path or kind; only an edited file is asked again, unless the effort differs or --fresh."""
  assert {name: definition.get("effort") for name, definition in agents.definitions().items()} == {name: "medium" for name in agents.definitions()}
  backend, (net, load, readme) = Stub(), put(ledger, "src/models/net.py", "src/data/load.py", "README.md")
  run_review("file-review", backend, [net], ledger, tier="code", run="1003-0101-aaaa")
  run_review("file-review", backend, [load, readme], ledger, tier="code", run="1003-0102-bbbb")
  assert len(backend.shown) == 3 and {effort for _, effort in backend.asked} == {"medium"}   # the definition's effort
  assert reviews.last_run(ledger) == "1003-0102-bbbb"

  found = lambda **kwargs: sorted(row["file"] for row in reviews.filtered(reviews.conversations(ledger), ledger, **kwargs))
  for kwargs, expected in (({"run": "1003-0101"}, ["src/models/net.py"]), ({"run": "1003-0102"}, ["README.md", "src/data/load.py"]), ({"path": "src/"}, ["src/data/load.py", "src/models/net.py"]), ({"path": "src/models"}, ["src/models/net.py"]), ({"path": "*.md"}, ["README.md"]), ({"failed": True}, [])):
    assert found(**kwargs) == expected, kwargs
  assert found(agent="logic") == found(agent="file-review")   # a kind or its agent

  load.write_text("y = 3\n")
  by_file = {row["file"]: row for row in run_review("file-review", backend, [net, load], ledger, tier="code", run="1003-0103-cccc")}
  assert len(backend.shown) == 4   # only the edited file was asked
  assert by_file["src/models/net.py"]["reused"] == "1003-0101-aaaa" and not by_file["src/data/load.py"].get("reused")
  for kwargs, asked in (({"effort": "low"}, 6), ({"effort": "low", "fresh": True}, 8)):   # the command's effort overrides, and --fresh asks again
    run_review("file-review", backend, [net, load], ledger, tier="code", **kwargs)
    assert len(backend.shown) == asked and backend.asked[-1][1] == "low"


def test_a_review_names_what_it_skipped_and_a_listing_defaults_to_where_you_stand(ledger, monkeypatch, capsys):
  """Files no standard covers are named, --open from a folder shows that folder, `--tail 0` lists nothing and a bad `--commit` is named."""
  tool = ledger / "tool"
  for name, text in (("install.sh", "#!/usr/bin/env bash\n"), ("README.md", "# t\n"), ("dotfiles/tmux.conf", "set -g mouse off\n")): put(tool, name, text=text)
  subprocess.run(["git", "add", "-A"], cwd=ledger, check=True)   # discovery reads what git tracks
  monkeypatch.chdir(tool)
  cli.main(["sub", "review", ".", "--dry-run"])
  printed = capsys.readouterr()
  assert "file-review" in printed.out and "tool/install.sh" in printed.out   # shell scripts route to both reviewers
  assert "not reviewed, no standard covers them: 1 file (.conf 1) in tool/dotfiles/ 1" in printed.err
  assert "agent sub review logic dotfiles/tmux.conf" in printed.err   # a path that works from here

  put(ledger, "top.py")
  for task, file, issue in (("t-top", "top.py", "elsewhere"), ("t-here", "tool/install.sh", "here")): reviews.write(record(ledger, task, file, [{"line": 1, "issue": issue}]), ledger)
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
