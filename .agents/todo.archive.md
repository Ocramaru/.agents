---
name: todo.archive
description: Finished work on the hub, newest first: why the code looks the way it does
kind: todo
---

# Done

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| 2026-10-05 | 22 |
| 2026-10-03 | 31 |
| 2026-09-25 | 38 |

<!-- /map -->


Moved out of [[todo]] as each finished. What any of it taught is in [[learned]]; this records that it happened.

## 2026-10-05

- [x] A standard's file-scoped section (`## todo.md` in agent-notes) goes out the first time a file it names is edited, even when the rest of the standard already went out for another file. Each section is stamped on its own key, so nothing is sent twice. Issue #3.
- [x] Nearest means the nearest directory with notes, so a `.agents` holding only `agents.toml` no longer demotes the real notes to the ancestor rule.
- [x] `notes.split` finds sections through `mapblock.headings`, so a `## ` inside a fence no longer cuts a note, and split agrees with the section map.
- [x] `agent sub agents` says each reviewer sees one file, has no tools, and returns findings by line.
- [x] `python.md` says comments state the present (issue #4), and `go.md` exists (issue #1). No Go of mine was on the machine to derive it from, so it follows the issue and python.md's principles, with gofmt expected.
- [x] Issue #2 was not ours: the empty `.git/.agents` was made in July beside `.git/.codex` in the same millisecond, before this repo existed, and the `site-packages` ones ship inside the fastapi and typer wheels.

## 2026-10-03

- [x] `agent sub review --recheck` asks again about the files with a finding open, or one closed as fixed since their last verdict, each by the reviewer that raised it. `fixed` stays a claim until a verdict lands after it; an unchanged file keeps its verdict without being asked.
- [x] `agent sub close` takes several targets, and a six-character id as `--open` and the injected findings show it, since an edit moves the line a review recorded and `file:line` then matches nothing.
- [x] A finding on a file that no longer exists is not open. Nothing reviews a deleted file again, so four sat on `agentkit/cli.py` after it became a package.
- [x] `--open` names the reviewer rather than its kind, which labelled a docstring complaint `logic`, and cuts the text only on a terminal, so a script reading the pipe gets every word.

## 2026-09-25

- [x] Removed `skills/`, 2.0 MB of AWS plugin skills copied here on 2026-07-15. Verified first that nothing linked to it, no config named the path, and all 14 of its skills existed in the installed `aws-core` plugin cache or in `~/.claude/skills`, with `aws-deployment` checked separately, since the current plugin has dropped it. The `.gitignore` line stays: removing it while the directory existed would have offered 2 MB of untracked files to the next `git add -A`, and it is insurance against another copy appearing.
- [x] `agent issue --list`, naming which open issues have a reply waiting. Filing was never the missing half: dedupe already stopped the second copy, but nothing told a session the first one had been answered. `f458a7b`.
- [x] Tests for the three gaps a condensing pass exposed: the reply tier, the truncate branch of `payload`, and `discover`'s filtering with the exclude layering. `Session.answer` lost its default tier in the process, so one call site is no longer the only thing carrying a conversation's model forward. `2918592`.
- [x] A note, not a bare `.agents`, opts a repo into commit-time review. `reviews.path()` creates `.agents/.reviews/` in whatever repo it reviews, so reviewing a third-party checkout once used to enrol it forever. `a0ae8df`.
- [x] Condensed the test suite, 142 test functions to 104, and replaced one that pinned a trap without ever calling the function it claimed to pin. `0bf9dde`.
- [x] `agent issue`, so friction met in another repo reaches the hub at all. The nearest `learned.md` is the wrong file for it and nobody would read it there. `fffb7e3`.
