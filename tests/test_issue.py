"""Reporting friction with the hub from another repo: the report carries where it was met.
No test runs `gh`; the calls are recorded and the assertions are about what was asked of it.

Author: Marco Cassar (@Ocramaru)
"""

import json, socket, subprocess

import pytest
from conftest import git

from agentkit import issue, version


@pytest.fixture
def gh(monkeypatch):
  """Stand in for the gh CLI: record what was asked, answer with whatever the test queued."""
  def fake(*args):
    fake.calls.append(list(args))
    reply = fake.replies.get(verb := args[1] if len(args) > 1 else "", "[]" if verb == "list" else "")   # gh prints [] when nothing is open
    return subprocess.CompletedProcess(args, 0, reply if isinstance(reply, str) else json.dumps(reply), "")
  fake.calls, fake.replies = [], {}
  monkeypatch.setattr(issue, "gh", fake)
  return fake


def test_it_files_on_the_hub_naming_its_commit_and_nothing_private_and_the_same_complaint_is_one_issue(gh, tmp_path):
  """The report names the .agents commit, and the repo and hostname only with --context; a title already open gets a comment, matched on casefolded words."""
  elsewhere = git(tmp_path / "project")   # not the hub, which is where friction with it is met
  footer = lambda **options: issue.file("t", "", elsewhere, "Ocramaru/.agents", dry=True, **options)[1].split("\n\n")[-1]
  assert footer().startswith(f"agentkit {version()}") and "unknown" not in footer()   # the version and HEAD resolve in .agents
  assert "project" not in footer() and socket.gethostname() not in footer()
  assert "met in project" in footer(context=True) and socket.gethostname() in footer(context=True)
  assert {call[1] for call in gh.calls} == {"list"}   # a dry run asks for nothing but the list

  gh.replies["create"] = "https://github.com/Ocramaru/.agents/issues/1"
  code, filed = issue.file("remap rewrote a README", "", elsewhere, "Ocramaru/.agents")
  assert code == 0 and filed.endswith("/issues/1")
  create = next(call for call in gh.calls if call[1] == "create")
  assert create[create.index("--repo") + 1] == "Ocramaru/.agents"
  assert f"agentkit {version()}" in create[create.index("--body") + 1] and "project" not in create[create.index("--body") + 1]

  gh.calls.clear()
  gh.replies["list"] = [{"number": 4, "title": "Close takes file line but open prints file", "url": "https://github.com/Ocramaru/.agents/issues/4"}]
  code, said = issue.file("close takes file:line, but open prints file!", "on another machine too", elsewhere, "Ocramaru/.agents")
  assert code == 0 and "added to" in said and "/issues/4" in said
  assert not any(call[1] == "create" for call in gh.calls)
  comment = next(call for call in gh.calls if call[1] == "comment")
  assert comment[2] == "4" and "on another machine too" in comment[comment.index("--body") + 1]

  gh.replies["list"] = [{"number": 5, "title": "Ünïcode títle", "url": "u/5"}, {"number": 6, "title": "???", "url": "u/6"}]
  assert issue.file("ünïcode TÍTLE", "", elsewhere, "Ocramaru/.agents", dry=True)[1].startswith("would comment on u/5")   # \W keeps non-ASCII letters
  assert issue.file("!!!", "", elsewhere, "Ocramaru/.agents", dry=True)[1].startswith("would open")   # nothing left to compare is never a match


def test_the_listing_counts_replies_and_a_gh_that_fails_files_nothing(gh, monkeypatch, tmp_path):
  """Each open issue shows its comment count; a missing or failing gh is a message, and an unreadable list files nothing rather than a duplicate."""
  gh.replies["list"] = [{"number": 4, "title": "close wants file:line", "url": "u/4", "comments": [{"body": "fixed in 3243a79"}]},
                        {"number": 7, "title": "remap ate a README", "url": "u/7", "comments": []},
                        {"number": 9, "title": "older gh shape", "url": "u/9", "comments": 3}]
  listing = "\n".join(issue.filed("Ocramaru/.agents"))
  assert "#4  close wants file:line, 1 comment" in listing and "u/4" in listing
  assert "#7  remap ate a README\n" in listing   # nothing waiting, so nothing claimed
  assert "#9  older gh shape, 3 comments" in listing

  monkeypatch.undo()   # the real gh again
  with monkeypatch.context() as patch:
    patch.setenv("PATH", "/nonexistent")
    result = issue.gh("auth", "status")
  assert result.returncode == 127 and "not installed" in result.stderr

  verbs = []
  monkeypatch.setattr(issue, "gh", lambda *args: verbs.append(args[1]) or subprocess.CompletedProcess(args, 1, "", "gh: not logged in"))
  code, said = issue.file("x", "", tmp_path, "Ocramaru/.agents")
  assert code == 1 and "not filing blind" in said
  assert verbs == ["list"]   # never got as far as create
  assert "could not read" in issue.filed("Ocramaru/.agents")[0]


@pytest.mark.parametrize("url, want", [
  ("git@github.com:Ocramaru/.agents.git", "Ocramaru/.agents"),
  ("https://github.com/Ocramaru/.agents", "Ocramaru/.agents"),
  ("https://github.com/Ocramaru/.agents.git/", "Ocramaru/.agents"),
  (None, None),   # no remote is nowhere to file
])
def test_the_hub_repo_comes_from_its_remote(tmp_path, url, want):
  """owner/name is read from the hub's remote, so a fork files on itself."""
  hub = git(tmp_path / "hub")
  if url: subprocess.run(["git", "remote", "add", "origin", url], cwd=hub, check=True)
  assert issue.slug(hub) == want
