"""Reporting friction with the hub from another repo: a draft that opens for the person to submit, carrying where it was met.
No test runs `gh` or a browser; the calls are recorded and the assertions are about what was asked of them.

Author: Marco Cassar (@Ocramaru)
"""

import argparse, json, platform, socket, subprocess, urllib.parse, webbrowser

import pytest
from conftest import git

from agentkit import cli, doctor, gh as agentkit_gh, hub, issue

HUB = "Ocramaru/.agents"
OPEN_FOUR = [{"number": 4, "title": "Close takes file line but open prints file", "url": "https://github.com/Ocramaru/.agents/issues/4"}]


@pytest.fixture
def gh(monkeypatch):
  """Stand in for the gh CLI: record what was asked, answer with whatever the test queued, or fail with `code`."""
  def fake(*args):
    fake.calls.append(list(args))
    reply = fake.replies.get(verb := args[1] if len(args) > 1 else "", "[]" if verb == "list" else "")   # gh prints [] when nothing is open
    return subprocess.CompletedProcess(args, fake.code, reply if isinstance(reply, str) else json.dumps(reply), "gh: not logged in" if fake.code else "")
  fake.calls, fake.replies, fake.code = [], {}, 0
  monkeypatch.setattr(agentkit_gh, "run", fake)
  return fake


@pytest.fixture
def browser(monkeypatch):
  """Stand in for the browser: record each address it was asked to open, and open nothing."""
  opened = []
  monkeypatch.setattr(webbrowser, "open", lambda address: opened.append(address) or True)
  return opened


@pytest.fixture
def elsewhere(tmp_path):
  """A repo that is not the hub, which is where friction with it is met."""
  return git(tmp_path / "project")


def sent(said):
  """The title, the body and the address in the link a draft ends with."""
  address = said.splitlines()[-1].split(": ", 1)[1]
  return {name: values[0] for name, values in urllib.parse.parse_qs(urllib.parse.urlsplit(address).query).items()} | {"address": address}


@pytest.mark.parametrize("listed, code, dry, body", [
  ([], 0, False, "x"),   # nothing open: a new issue
  (OPEN_FOUR, 0, False, "x"),   # the title is open: a comment
  ([], 1, False, "x"),   # gh cannot read the issues
  ([], 0, True, "x"),
  ([], 0, False, "line\n" * 5000),   # a link too long to carry it
], ids=["new", "duplicate", "no gh", "dry run", "long"])
def test_no_path_creates_an_issue_or_a_comment(gh, browser, elsewhere, listed, code, dry, body):
  """The only thing asked of gh is the list of open issues; the person submits."""
  gh.replies["list"], gh.code = listed, code
  issue.draft("close takes file:line, but open prints file!", body, elsewhere, HUB, dry=dry)
  assert gh.calls and {tuple(call[:2]) for call in gh.calls} == {("issue", "list")}


def test_the_link_carries_the_title_and_body_url_encoded_and_is_printed_as_well_as_opened(gh, browser, elsewhere):
  """The new-issue page for the hub holds the title and the body, the footer included, as a browser reads them back, and the same link ends what is printed."""
  title, body = "remap & split: 100% of a #heading = é?", "line one\nline two with a & b=c ? and 100%\n\n    indented\nünicöde ☃"
  said = issue.draft(title, body, elsewhere, "someone/fork")   # a fork files on itself
  link = urllib.parse.urlsplit(browser[0])
  assert len(browser) == 1 and (link.scheme, link.netloc, link.path) == ("https", "github.com", "/someone/fork/issues/new")
  assert sent(said) == {"title": title, "body": f"{body}\n\n---\nagentkit {hub.version()} · {platform.system()}", "address": browser[0]}
  assert " " not in browser[0] and "\n" not in browser[0] and browser[0].count("&") == 1   # a & inside a value is %26, so only the one between the two fields remains
  assert f"# {title}" in said and body in said and said.startswith("Draft issue for someone/fork") and said.splitlines()[-1] == f"Opened in your browser: {browser[0]}"


def test_a_machine_with_no_browser_still_gets_the_link(gh, monkeypatch, elsewhere):
  """webbrowser.open returns False on a headless machine or over SSH; the output says so and still ends with the link to hand to the person."""
  monkeypatch.setattr(webbrowser, "open", lambda address: False)
  said = issue.draft("a title", "x", elsewhere, HUB)
  assert said.splitlines()[-1].startswith("No browser opened: https://github.com/Ocramaru/.agents/issues/new?") and sent(said)["title"] == "a title"


def test_the_draft_names_the_commit_and_nothing_private_unless_asked(gh, browser, elsewhere):
  """The report names the .agents commit, and the repo and hostname only with --context, in the text and in the link."""
  plain, asked = issue.draft("t", "", elsewhere, HUB), issue.draft("t", "", elsewhere, HUB, context=True)
  assert sent(plain)["body"].startswith(f"agentkit {hub.version()}") and "unknown" not in plain   # the version and HEAD resolve in .agents
  assert "project" not in plain and socket.gethostname() not in plain
  assert "met in project" in asked and socket.gethostname() in asked
  assert "met in project" in sent(asked)["body"] and socket.gethostname() in sent(asked)["body"]


def test_an_open_issue_with_the_same_title_opens_that_issue_and_prints_the_body_to_paste(gh, browser, elsewhere):
  """A title open already, matched on casefolded words, opens that issue's own page and prints the body for a comment; a title with nothing to compare matches nothing."""
  gh.replies["list"] = OPEN_FOUR
  said = issue.draft("close takes file:line, but open prints file!", "on another machine too", elsewhere, HUB)
  assert browser == [OPEN_FOUR[0]["url"]]
  assert "#4" in said and "Paste this under it as a comment" in said and "on another machine too" in said and said.endswith(f": {OPEN_FOUR[0]['url']}")
  assert "issues/new" not in said

  gh.replies["list"] = [{"number": 5, "title": "Ünïcode títle", "url": "u/5"}, {"number": 6, "title": "???", "url": "u/6"}]
  issue.draft("ünïcode TÍTLE", "", elsewhere, HUB)
  assert browser[-1] == "u/5"   # \W keeps non-ASCII letters
  issue.draft("!!!", "", elsewhere, HUB)
  assert browser[-1].startswith("https://github.com/Ocramaru/.agents/issues/new?")   # nothing left to compare is never a match


@pytest.mark.parametrize("code, reply", [(127, "gh is not installed"), (1, "gh: not logged in")], ids=["missing", "logged out"])
def test_without_gh_the_draft_is_made_and_says_the_duplicate_check_was_skipped(gh, browser, elsewhere, code, reply):
  """A gh that is missing or logged out costs the duplicate check and nothing else: the new issue still opens."""
  gh.code = code
  said = issue.draft("a title", "what happened", elsewhere, HUB)
  assert browser == [sent(said)["address"]] and sent(said)["title"] == "a title" and "what happened" in sent(said)["body"]
  assert "duplicate check was skipped" in said

  gh.code = 0
  assert "duplicate check was skipped" not in issue.draft("a title", "what happened", elsewhere, HUB)   # a gh that answers is not blamed


@pytest.mark.parametrize("listed", [[], OPEN_FOUR], ids=["new", "duplicate"])
def test_a_dry_run_prints_the_draft_and_the_link_and_opens_nothing(gh, browser, elsewhere, listed):
  """--dry-run says so, shows the text and ends with the link it would have opened."""
  gh.replies["list"] = listed
  said = issue.draft("close takes file:line, but open prints file!", "the body", elsewhere, HUB, dry=True)
  assert browser == [] and "the body" in said
  assert said.splitlines()[-1].startswith("Dry run, nothing opened: https://github.com/Ocramaru/.agents/issues/")


@pytest.mark.parametrize("count", range(1000, 1004))   # a different number of lines to drop each time
def test_a_body_too_long_for_a_link_is_cut_in_the_link_at_a_line_and_printed_whole(gh, browser, elsewhere, count):
  """Past issue.LINK_LIMIT characters the link keeps the lines that fit, whole lines only, and says so; the printed draft has every line."""
  body = "\n".join(f"line {number}" + "x" * (number % 7) for number in range(count))
  said = issue.draft("a long one", body, elsewhere, HUB)
  full = f"{body}\n\n---\nagentkit {hub.version()} · {platform.system()}"
  carried = sent(said)["body"]
  assert carried != full and full.startswith(carried + "\n")   # a prefix that ends where a line does
  assert len(browser[0]) <= issue.LINK_LIMIT < len(browser[0]) + len(urllib.parse.quote("\n" + full[len(carried) + 1:].split("\n")[0]))   # as many lines as fit: the next one would not
  assert "A browser caps the length of a link" in said and f"line {count - 1}" in said and full in said


def test_a_body_that_fits_is_not_cut(gh, browser, elsewhere):
  """A link under the limit carries the whole body and does not apologise."""
  said = issue.draft("short", "\n".join(f"line {number}" for number in range(50)), elsewhere, HUB)
  assert "line 49" in sent(said)["body"] and "caps the length" not in said


def test_the_command_drafts_for_the_hub_and_passes_dry_and_context_through(gh, browser, elsewhere, monkeypatch, capsys):
  """`agent issue` prints the draft and opens it; --dry-run opens nothing, --context adds where it was met, and a missing title is asked for."""
  monkeypatch.setattr(issue, "slug", lambda: HUB)
  monkeypatch.chdir(elsewhere)
  options = {"body": "what I was doing", "list_": False, "dry": False, "context": False}

  assert cli.setup.cmd_issue(argparse.Namespace(title="a title", **options)) == 0
  said = capsys.readouterr().out
  assert len(browser) == 1 and said.endswith(f"{browser[0]}\n") and "what I was doing" in said and "met in" not in said

  assert cli.setup.cmd_issue(argparse.Namespace(title="a title", **{**options, "dry": True, "context": True})) == 0
  said = capsys.readouterr().out
  assert len(browser) == 1 and "Dry run" in said and "met in project" in said

  assert cli.setup.cmd_issue(argparse.Namespace(title=None, **options)) == 2
  assert len(browser) == 1 and "say what was awkward" in capsys.readouterr().err


def test_the_listing_counts_replies_and_an_unreadable_list_is_a_message(gh, monkeypatch):
  """Each open issue shows its comment count; a missing or failing gh is a message."""
  gh.replies["list"] = [{"number": 4, "title": "close wants file:line", "url": "u/4", "comments": [{"body": "fixed in 3243a79"}]},
                        {"number": 7, "title": "remap ate a README", "url": "u/7", "comments": []},
                        {"number": 9, "title": "older gh shape", "url": "u/9", "comments": 3}]
  listing = "\n".join(issue.filed(HUB))
  assert "#4  close wants file:line, 1 comment" in listing and "u/4" in listing
  assert "#7  remap ate a README\n" in listing   # nothing waiting, so nothing claimed
  assert "#9  older gh shape, 3 comments" in listing

  monkeypatch.undo()   # the real gh again
  with monkeypatch.context() as patch:
    patch.setenv("PATH", "/nonexistent")
    result = agentkit_gh.run("auth", "status")
  assert result.returncode == 127 and "not installed" in result.stderr

  monkeypatch.setattr(agentkit_gh, "run", lambda *args: subprocess.CompletedProcess(args, 1, "", "gh: not logged in"))
  assert "could not read" in issue.filed(HUB)[0]


@pytest.mark.parametrize("returncode, passes", [(0, True), (1, False)])
def test_doctor_checks_gh_for_the_duplicate_lookup_and_the_listing(monkeypatch, returncode, passes):
  """The gh check passes when gh is logged in and fails when it is not, and it names what gh is still for."""
  monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
  monkeypatch.setattr(agentkit_gh, "run", lambda *args: subprocess.CompletedProcess(args, returncode, "", ""))
  (passed, label, fix), = [check for check in doctor.checks() if "gh authenticated" in check[1]]
  assert passed == passes and "find an issue already filed" in label and "--list" in fix and "reach the hub" not in label


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
