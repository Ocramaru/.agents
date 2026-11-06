---
name: todo.archive
description: Finished work on the hub, newest first: why the code looks the way it does
kind: todo
---

# Done

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| 2026-11-06 | 25 |
| 2026-11-05 | 61 |
| 2026-10-10 | 65 |
| 2026-10-05 | 69 |
| 2026-10-03 | 78 |
| 2026-09-25 | 85 |

<!-- /map -->


Moved out of [[todo]] as each finished. What any of it taught is in [[learned]]; this records that it happened.

## 2026-11-06

- [x] No test replaces `subprocess.run`: `uv`, the new `agent`, `claude` and a failing or missing `git` are fake programs on PATH, made by `conftest.fake`, which `fake_gh` wraps, so the code under test runs a real subprocess.
- [x] The directories nothing reads are `[walk] skip` in config.toml, a list every layer adds to, read once per walk by `tree.skipped`; a repo adds its own in its agents.toml.
- [x] The hub requires Python 3.15, so `uuid.uuid7` and `lazy import` are always there, and keys its reviews with the standard library's `uuid.uuid7`.
- [x] A `pre-commit run` names a hook only by an id its config has, so no table of pre-commit's flags is kept.

- [x] With no default backend, `agent update` and `agent doctor` say that headless reviews (post-commit, doc-check) cannot run, and name `agent install --backend <name>`. Nothing writes a default on its own, so a machine that relied on the dropped `default = "claude"` hears it there rather than only in `post-commit.log`.
- [x] Picking `URL` or `DIR` by number at the profile question asks for the address or the directory; nothing typed leaves the question for the next install.
- [x] The guard skips a `pre-commit run` flag's value when it looks for a hook id: every flag but `-a`, `-v`, `--show-diff-on-failure` and `-h` takes the next word unless it carries `=`, so `pre-commit run --from-ref origin/main` is judged as running every hook.
- [x] `backends.choose` with a profile writes the default to its config.toml and drops a `default` from local.toml's `[backends]`, which is read after the profile and would otherwise still win. `config.write` drops a key given None.
- [x] Install merges the settings.json `hooks` block by script: the hub's own entries, known by running `~/.agents/hooks/*.sh` however home is spelled, are added, updated, or removed when the bundle no longer has them, and every other hook in every event stays as it was, a numbered `.bak` kept before any write. `install.partition` is the one rule, and `doctor` and `status` call the block current by it, so a user's own hooks are no drift.
- [x] An install records each file it copies into `~/.agents` by sha256 in `~/.agents/.copied`. A copy that is a link, or not as the last install left it, is set aside to a numbered `.bak` before the new one is written, never written through; a recorded copy the bundle no longer has is removed, or set aside if changed; `doctor` fails until it is. With no record yet, everything there counts as an earlier install's.
- [x] `install.sh` finds `--dry-run` anywhere among its arguments, and prints the rest as what `agent install` would get.
- [x] `agent hook install` reads the repo's effective `core.hooksPath`: one that is not this hub's, such as husky's, is refused with where to call the review from instead, since git never reads `.git/hooks` then.
- [x] `doctor` reports a settings.json that is not a JSON object instead of crashing, and checks `githooks/_dispatch` is executable, which every githook links to.
- [x] `hand_over` sets `AGENTS_HANDED_OVER` for the kept tool, and `keep` returns at once under it, so the kept tool hands over to nothing, even with uv's tool directory inside its cache.
- [x] `githooks/_dispatch` runs under `set -euo pipefail`, its opt-in loop an `if` and its git lookups `|| true`; a test checks every script with a shebang in hooks/, githooks and install.sh is strict.
- [x] `hooks/forget.sh` counts stamps only when the session's stamp directory exists, so a PostCompact with nothing stamped logs `cleared 0 stamps` instead of exiting 2.
- [x] `hooks/log.sh` puts `2>/dev/null` before `< "$AGENTS_HOOK_LOG"` when it measures the log, so a first write has nothing to say about a missing file. The group's own `2>/dev/null` already swallowed it, so nothing showed before either.
- [x] `backends.py` starts every CLI reviewer with `AGENTS_REVIEWER=1`, and `session-start.sh` and `inject.sh` exit at once inside one, logging `skip` under the session `reviewer`, so a review is judged on its prompt alone.
- [x] `inject.sh` and `session-start.sh` refuse a session id that is not a plain name with an ERROR, as `forget.sh` does, and with no id ask `inject` with an empty `--session`, which sends everything and stamps nothing, and leave the gate alone.
- [x] `agent inject --depends` prints, when there is nothing to send, the paths whose change could change that: each `.agents` the chain walk could find, whether or not it exists yet, the `.local`, `standards` and `agents.toml` in each that does, the standards' folders and the repo's reviews. `inject.sh` stamps them all, and `gate.sh` reopens when any is newer than its stamp, so a note or standard added mid-session reaches a file already answered.
- [x] The reviews a gate watches are `reviews.path`'s, at the git root's `.agents`, so a review landing there reopens a file under a package-level `.agents`; `gate_reviews` is gone.
- [x] `agent install` records an install's `agent` by absolute path in `~/.agents/.cli`, which `log.sh` reads after a clone's `bin/agent` and before PATH, so a git GUI or a desktop app without uv's bin on PATH still reaches it.
- [x] `inject.open_findings` still fails open on reviews it cannot read, and says why in the hook log: a lock another process holds is a `skip`, anything else an ERROR naming the file and the reason.
- [x] A failed review never supersedes: `SUPERSEDES` requires a state other than `failed`, so a run whose reply called itself findings and failed leaves the earlier findings open. A `working` reply that carries findings still counts, since the run reports them as found.
- [x] `review.unread` is the one filter for every route, discovery, a commit's file list and a named file alike: a skipped directory, an `exclude`, or a file over `max_bytes`, each told as `skipping N files <why>`. An exclude's `**/` also matches no folder, as in .gitignore, so `**/uv.lock` excludes the root's.
- [x] `reviews.verdicts` and `reviews.dismissals` wait for a lock another process holds as a write does (`reviews.TRIES`), so a review run beside a hook's reads its history rather than none. Other reads still try once, so an edit's hook never waits.
- [x] `agent sub review` refuses paths from more than one repo, naming each, since each repo keeps its own reviews.
- [x] A worktree's `wrong` or `wontfix` closure is written to the main checkout's reviews first, so when that write fails nothing is closed and closing again writes both. A failure of the worktree's own write after it can leave the dismissal in the main checkout twice.
- [x] A profile review reads a repo override once per repo and place in it, a repo being its origin, else its main checkout: a worktree or clone of one repo is read once, and another repo holding the same text is read too.
- [x] A finding from a review of several files lists as open under whatever name the model gave it, a basename two shown files share included, since that conversation's next verdict replaces it whole; a review of one file still drops the findings of a file since deleted. A recheck skips an open finding whose name is no file.
- [x] `profile.init` writes `.agents/.gitignore` into a new profile before its first commit, so `agent profile review` leaves nothing for `doctor` to call uncommitted.
- [x] The http backend retries a 408 or 429 like a dropped call, waiting the `Retry-After` seconds a reply gives, on any retried status, capped at the backend's timeout, or the usual backoff without one.

## 2026-11-05

- [x] `.agents/context.md` says what `session-start.sh`, `memory.py`, `review.whole` and `standards.bases` and `files` each are.

## 2026-10-10

- [x] A gitignored `.agents/.local/` for machine-specific notes, laid out like its `.agents` and read right after it. `agent init` writes `.agents/.gitignore` from the template, ignoring `.local/` and `.reviews/`, and appends what an old one lacks.

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
