---
name: settled
description: Findings that held up: measurements, designs that worked, and why things are the shape they are
kind: learned
---

# Settled

- **A review's time is the model thinking, and effort is the knob; a smaller model is not.** One file-review of a 336-line module, one sample each: Sonnet at default effort 183 s, 3 findings, 17,013 output tokens; medium 123 s, 5 findings, all substantive; low 19 s, 4 findings, two of them noise and both real ones missed; Haiku 129 s and an unreadable reply. The prompt was 27,000 characters, so reading it is not the cost. Choosing files is milliseconds and was never it either.

- **The public `.agents` plus a private profile reproduces the hub exactly.** Staged from HEAD and checked both ways: `.agents` alone passes its whole suite on the starters with every reviewer and standard resolving, and `.agents` plus the profile governs every probed file type with the same standards as before, the profile's own versions delivered. The cutover was rehearsed against local bare repos for the first machine and a following one, 17 checks each. A leak scan over the public tree found 14 references to private projects in code comments and fixtures before anything was published.

- **Four in five `inject` calls produced nothing.** Of 250 logged calls, 69% were already in context and 12% governed by nothing, each paying ~90 ms for a `uv run`. `hooks/gate.sh` remembers the empty answer per session and path, keyed to the review ledger, and the same edit costs 12 ms.

- **`map_over` at 2048 made a 2 KB note worse, not cheaper.** A 2070-byte `context.md` was sent as a 375-byte table instead of itself. Raised to 6144: against a 24000 budget, the map is for a note that is genuinely long.

- **Two tests read the machine's `config.toml` instead of a hub of their own**, so raising `map_over` there broke them for reasons unrelated to what they checked.

- **agentkit already matched the reference codebase on density everywhere except `except`.** Measured by ast over both: line length is the same shape (85.7% of lines under 90 characters against 84.3%, ~2% past 110 in both), and agentkit keeps a one-statement `if` on one line 83% of the time against the reference's 35%. The one real gap was exception handlers (16 split over two lines, against `if` at 83% dense), so the fix was 17 joins, not a formatting pass. Worth knowing before someone "fixes" density that is not broken. The gaps that do remain: comments run about a third of the reference's rate (4.0% of lines carrying one against 11.8%), and function docstrings 52% against 69%.

- **The convention had no way to record a finding about itself.** "Findings outlive sessions" resolves to the nearest `learned.md`, which for a session working in another repo is that repo's: the wrong file, and never read here. So every complaint about the hub raised from outside the hub was lost by construction, which is the exact failure the notes exist to prevent. `agent issue` is the channel: it reaches the hub from any repo on any machine, because GitHub is the only thing both clones share. Dedupe is on a normalised title, so the same friction from two machines is one issue with two comments.

- **Chained `str.replace` for argv placeholders corrupts the payload, order-dependently.** `a.replace("{model}", m).replace("{prompt}", p).replace("{session}", s)` rescans text it just inserted, so a prompt containing `{session}` had it substituted away, while `{model}` survived only because it was replaced before the prompt was injected. Reviewing this repo's own source is what exposed it: the file `doc-check` received read `.replace("", session or "")`. Fixed with one `re.sub` pass in `_fill()`.
- **doc-check found a real bug while reporting a different one.** It flagged line 43 as non-obvious code; the actual defect was that the line it saw was not the line on disk. Worth remembering when a finding looks wrong: check what the agent was actually shown before dismissing it.
- **Claude's `--resume` carries subagent context properly.** A reply went back into session `c44e443b` and the agent answered with a question about the earlier turn, so the handle in `Session.handles` is doing its job. Codex's resume flags are still unverified.

- **One project's chain of notes is 28.5k characters of notes, injected on every session.** Its deepest `learned.md` alone is 13.3k. Budgeted to 24k, spent assumptions-first, it lands at 24.3k with one todo truncated, but the naive fill order dropped the root `context.md` (1.2k) to keep a nested `todo.md` (3.1k), which is backwards. Context files go first regardless of depth.
- **Shelling to Python from a PreToolUse hook costs ~67 ms.** Acceptable for the notes hook, where chain-following and budgeting need real logic.

- **Two PreToolUse hooks answering one question cost more than one.** `standards.sh` (54 ms, six-plus `jq` spawns in a loop) plus `agents-context.sh` (91 ms, one Python call) came to 145 ms an edit; merged into `agent inject` it is 88 ms. The generated `standards/index.json` existed only to keep the shell hook fast and went away with it, taking `agent index`, an install step and a gitignore entry with it.
- **One project was injecting its notes twice**, from its own pre-rewrite `.claude/hooks/agents-context.sh` and from the global install, with different logic and different budgets. A repo that predates a global convention keeps shadowing it silently.

- **The reformatter guard matched anywhere in a command, not at a command position.** It blocked a commit whose message mentioned the tool in prose, and separately blocked the test harness that carried invocations as data. It also missed `uv run <formatter>`, since a runner prefix is not a command separator. Now anchored to a command position with an optional runner prefix, 12/12 on the cases.

- **Codex's `--json` is an event stream, and both key guesses were wrong.** `thread.started` carries `thread_id`, not `session_id`; the reply is `item.text` on an `item.completed` event, not a top-level `last_agent_message`. Backends now declare `format = "json" | "jsonl" | "text"` and a dotted `reply_key`, so a schema change is a config edit.
- **A self-referencing map converges in one pass if you size it before you number it.** The first version looped because writing the block shifted every line it recorded. The block's height depends only on the section count, which is known beforehand: render at the right size, then number against the finished layout. Verified across a section-count change, which alters the height.
- **A hand edit never fires a `PostToolUse` hook**, so a map goes stale silently and a rendered table reads as authoritative while being wrong. Injection now heals a drifted map before using it.
- **`hash()` is salted per process**, so the default task id from `agent sub run` never matched on a later invocation and a session could not be resumed without `--task`. Content hash now.

- **The loop is closed, and injection is where it closes.** A commit fires `hooks/post-commit.sh`, which reviews only the files the agent's standards govern, detached, into the repo's duckdb ledger. `inject.payload()` then carries the open findings for a file to whoever edits it next, keyed on a hash of the findings so a review landing mid-session still arrives. Verified end to end in a clean repo: commit a file with an inverted comparison plus a `.png`, and one file is reviewed, one finding is stored, and the next `agent inject` on that file carries it. The `.png` never reaches a model.

- **`uv run` costs about 30ms, which the inject hook can afford.** Measured against the ~90ms the hook already takes. Running `bin/agent` through uv means a fresh clone provisions its own venv, duckdb included, so the dependency does not have to be installed by hand or into a system python Debian has marked externally managed. Without uv it falls back to `python3` and everything but `agent sub review` still works.

- **`systemMessage` is how a hook says anything to the person.** Claude Code renders it as a collapsed "Claude Code notice", prefixed with the event: `PreToolUse:Write says: .agents loaded 2 standards for hooktrigger.py (4k)`. `additionalContext` goes to the model and is shown to nobody, which is why a working hook and a broken one looked identical for months. The other visible channel is a block -- exit 2 prints its stderr inline. Everything else needs `agent hooks`.
