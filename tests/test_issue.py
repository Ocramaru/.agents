"""Reporting friction with the hub from another repo.

The channel is the point: a session in another repo that finds a command awkward has nowhere else to put
it. So what is tested is that the report carries where it was met, and that the same complaint from
three machines is one issue with three comments rather than three issues.

Nothing here runs `gh`. The calls are recorded, and the assertions are about what was asked of it.

Author: Marco Cassar (@Ocramaru)
"""

import json
import socket
import subprocess

import pytest
from conftest import git

from agentkit import issue


@pytest.fixture
def gh(monkeypatch):
  """Stand in for the gh CLI: record what was asked, answer with whatever the test queued."""
  calls, replies = [], {}

  def fake(*args):
    calls.append(list(args))
    sub = args[1] if len(args) > 1 else ""
    out = replies.get(sub, "[]" if sub == "list" else "")   # gh prints [] when nothing is open
    return subprocess.CompletedProcess(args, 0, out if isinstance(out, str) else json.dumps(out), "")

  monkeypatch.setattr(issue, "gh", fake)
  fake.calls, fake.replies = calls, replies
  return fake


@pytest.fixture
def elsewhere(tmp_path):
  """A repo that is not the hub, which is where friction with the hub is actually met."""
  return git(tmp_path / "project")


def test_it_files_on_the_hub_naming_its_commit_and_nothing_private(gh, elsewhere):
  """The report names the .agents commit; the repo it was met in and the hostname go in only with --context."""
  foot = lambda **kw: issue.file("t", "", elsewhere, "Ocramaru/.agents", dry=True, **kw)[1].split("\n\n")[-1]
  said = foot()
  assert said.startswith(".agents at ") and "unknown" not in said   # HEAD resolves in .agents
  assert "project" not in said and socket.gethostname() not in said
  told = foot(context=True)
  assert "met in project" in told and socket.gethostname() in told
  gh.calls.clear()

  code, said = issue.file("map is wrong", "body here", elsewhere, "Ocramaru/.agents", dry=True)
  assert code == 0 and "# map is wrong" in said and "body here" in said
  assert [c[1] for c in gh.calls] == ["list"]                       # a dry run asks for nothing else

  gh.replies["create"] = "https://github.com/Ocramaru/.agents/issues/1"
  code, said = issue.file("close takes file:line but open prints file", "", elsewhere, "Ocramaru/.agents")
  assert code == 0 and said.endswith("/issues/1")
  asked = next(c for c in gh.calls if c[1] == "create")
  assert asked[asked.index("--repo") + 1] == "Ocramaru/.agents"
  body = asked[asked.index("--body") + 1]
  assert ".agents at " in body and "project" not in body


def test_the_same_complaint_is_one_issue_and_a_different_one_is_not(gh, elsewhere):
  """Dedupe is on a casefolded title of words, so punctuation and case never make a new issue, and an empty title matches nothing."""
  gh.replies["list"] = [{"number": 4, "title": "Close takes file line but open prints file",
                         "url": "https://github.com/Ocramaru/.agents/issues/4"}]
  code, said = issue.file("close takes file:line, but open prints file!", "on another machine too",
                            elsewhere, "Ocramaru/.agents")
  assert code == 0 and "added to" in said and "/issues/4" in said
  assert not any(c[1] == "create" for c in gh.calls)
  comment = next(c for c in gh.calls if c[1] == "comment")
  assert comment[2] == "4" and "on another machine too" in comment[comment.index("--body") + 1]

  issue.file("remap rewrote a README", "", elsewhere, "Ocramaru/.agents")
  assert any(c[1] == "create" for c in gh.calls)

  gh.replies["list"] = [{"number": 5, "title": "Ünïcode títle", "url": "u/5"}, {"number": 6, "title": "???", "url": "u/6"}]
  assert issue.file("ünïcode TÍTLE", "", elsewhere, "Ocramaru/.agents", dry=True)[1].startswith("would comment on u/5")   # \W keeps non-ASCII letters
  assert issue.file("!!!", "", elsewhere, "Ocramaru/.agents", dry=True)[1].startswith("would open")   # nothing left to compare is never a match


def test_the_listing_says_which_filed_issues_have_a_reply_waiting(gh):
  """Each open issue shows its comment count, from the comments gh returns or the count an older gh gives."""
  gh.replies["list"] = [{"number": 4, "title": "close wants file:line", "url": "u/4",
                         "comments": [{"body": "fixed in 3243a79"}]},
                        {"number": 7, "title": "remap ate a README", "url": "u/7", "comments": []},
                        {"number": 9, "title": "older gh shape", "url": "u/9", "comments": 3}]
  out = "\n".join(issue.filed("Ocramaru/.agents"))
  assert "#4  close wants file:line, 1 comment" in out and "u/4" in out
  assert "#7  remap ate a README\n" in out            # nothing waiting, so nothing claimed
  assert "#9  older gh shape, 3 comments" in out


def test_without_gh_nothing_is_filed_and_nothing_raises(monkeypatch, elsewhere):
  """A missing or failing gh is a message, and a list that could not be read files nothing rather than a duplicate."""
  with monkeypatch.context() as m:
    m.setenv("PATH", "/nonexistent")
    r = issue.gh("auth", "status")
  assert r.returncode == 127 and "not installed" in r.stderr

  calls = []
  monkeypatch.setattr(issue, "gh", lambda *args: calls.append(args[1]) or subprocess.CompletedProcess(args, 1, "", "gh: not logged in"))
  code, said = issue.file("x", "", elsewhere, "Ocramaru/.agents")
  assert code == 1 and "not filing blind" in said
  assert calls == ["list"]                                  # never got as far as create
  assert "could not read" in issue.filed("Ocramaru/.agents")[0]


@pytest.mark.parametrize("url, want", [
  ("git@github.com:Ocramaru/.agents.git", "Ocramaru/.agents"),
  ("https://github.com/Ocramaru/.agents", "Ocramaru/.agents"),
  (None, None),                                    # no remote is nowhere to file
])
def test_the_hub_repo_comes_from_its_remote(tmp_path, url, want):
  """owner/name is read from the hub's remote, so a fork files on itself."""
  hub = git(tmp_path / "hub")
  if url: subprocess.run(["git", "remote", "add", "origin", url], cwd=hub, check=True)
  assert issue.slug(hub) == want
