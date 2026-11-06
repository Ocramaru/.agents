---
name: todo
description: Open work on the hub
kind: todo
---

# TODO

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| Next | 20 |
| Structure | 34 |
| Owed | 48 |

<!-- /map -->


## Next

- [ ] Shared mode: notice when others commit in a repo, and step the profile back to `polite` or `restricted`, with line notices for code someone else wrote. The design is in [[shared-mode]]; one question is open.
- [ ] Ship `.agents` as a `uv tool install` rather than a clone, and version it from the first install: bump `version` in pyproject.toml and tag `vX.Y.Z`. It stays 0.1.0 until then. The design is in [[uv-install]]: standards, agents, templates and hooks sit beside the code, not in it, and the install should also make your profile, its private remote and a backend in one command.
- [ ] Generate `~/.claude/agents/*.md` from `agents/*.md` at install time, for definitions that want the parent model to invoke them rather than a hook. Without it, native subagents drift as a second copy.
- [ ] Set Codex up as well as Claude Code. Today it gets only the AGENTS.md pointer and the slash prompts: no notes at session start, no standards on an edit, no formatter guard, no compaction reset. Find what Codex's own config offers for each (hooks, notify, instructions files) and wire the hub into it, with `doctor` and `status` rows like the `claude hooks` one.
- [ ] Make the hub agent-agnostic. The Claude-only parts are the hooks (the `settings.json` block and the SessionStart, PreToolUse and PostCompact events), the memory inbox (`~/.claude/projects`), install's `if target == "claude"` branches and its `INSTRUCTIONS` and `COMMANDS` tables, and docs that quote Claude Code's own notice. Put each agent behind one description (where its config lives, how notes and standards reach it, what memory it keeps), so Codex and Gemini plug in the way Claude does; the item above is the first one through it.
- [ ] Prove the codex backend end to end. The event shapes are confirmed and unit-tested, but no real `agent sub run --backend codex` has been through resume yet.
- [ ] Run `agent profile review` on a real backend and triage what it says. Only a stub has been through it; the prompt is about 211k characters (138 files), which fits Sonnet but no ollama model. `agent sub reply` to it carries no files, so a recheck is a rerun.
- [ ] `agent memory review`: one conversation per project folder decides where each of Claude's memories belongs (a note, `.local` or the profile) and proposes the text, then a pass condenses repeats into one entry; nothing is written until accepted. The design is in [[memory-review]]; two questions are open.
- [ ] Check which of `SessionStart` (source `compact`) and `PostCompact` fires first. If the start runs first, it finds the stamps and sends nothing, and the notes come back only with the next edit.
- [ ] A permission level for what an agent runs on its own (builds, installs, deploys, merges): set in the profile, overridden by a project's `.agents/agents.toml`. OpenLoop's deploy exception is a row in its `.agents/context.md` until then.
- [ ] With `[inject] read` on, a Read of a note is never gated, since the gate exempts every `.agents/*.md` for the todo.md check, so each costs a Python start. Gate a note when the tool is Read.

## Structure

- [ ] Use PEP 810's `lazy import`, which `requires-python = ">=3.15"` guarantees: the 14 in-function imports (`duckdb` off the hook path, `rich` for a terminal, the `profile.py` cycle) become top-level lazy ones, and the CLI's command modules load only when their command runs. Measure an edit's hook time before and after; it may settle the next item.
- [ ] Every Bash call starts Python and imports the whole CLI (about 50–70 ms): add a path in `__main__.py` for `guard` and `inject` that imports only those, and have `no-reformat.sh` skip Python when no formatter word is in the command.
- [ ] Ungated edits in a repo with reviews import duckdb (19–20 ms), against `context.md`'s "stdlib only on the hook path". Keep a stdlib-readable open-findings index, or change `context.md`.
- [ ] One injection makes about 58 file reads (standards twice, split-note parts four times, `local.toml` three, `tree.chain` thrice). Carry per-call state in an `InjectionContext` across `inject.py`, `tree.py`, `standards.py`.
- [ ] The in-function imports at `profile.py:46,119` tie 10 modules into a cycle. Split where the profile is from profile operations, and move `memory.config_dir` out of `install`; the two `reviews` imports inside `inject.py` break no cycle.
- [ ] `ReviewStore(root)` for the 18 functions in `reviews.py` that pass `root` (25–40 lines).
- [ ] `ReviewBatch` in `review.py` to take `cmd_review` and `_fan_out` (12 parameters) out of `cli/sub.py`, with one digest helper for `file()` and `whole()` (30–45 lines).
- [ ] CLI and HTTP subclasses in `backends.py` instead of the `_cli`/`_http` switch; `CliHelpers` as plain module functions.
- [ ] One constant each for `.agents` (20 literals) and `.local` (9); the note names in one place instead of `notes.py`, `tree.py`, `doctor.py`, `_dispatch`; backend timeouts and retries into `[backends]`; one install file list instead of `FIXED`, `INSTRUCTIONS`, `COMMANDS` and pyproject; the repo URL once; CLI widths and colors as named constants.
- [ ] Inline the one-caller helpers: `Session.answer`, `Layer.section_header`, `memory.places`, `review._matches`, `guard.past_flags`, `notes._listed`, `install.hand_over`; fold `sub._unreviewed` and `sub._report_review` into `ReviewBatch`.
- [ ] Naming: the `cmd_` prefix on 27 commands, `arg`, `out`, `Doc`.

## Owed

- [ ] A config.toml, local.toml or agents.toml that cannot be read (mode 0, a looping link) crashes `doctor` before its own check reports it: `config.section` reads it first, through `tree.skipped`. Read an unreadable layer as empty there too, as one that does not parse already is.
- [ ] Nothing triages what `agent issue` files. An issue from a machine-local session is only useful if it is read, and the only reader is me.
- [ ] Decide what federation means before the schema hardens. `author` is on every row already, but nothing says whose `closed_by` wins when two machines disagree, and nothing syncs.
- [ ] The indexer seam is specified but unexercised: no catalog exists, and `~/.agents` sits outside the indexer's workspace root.
- [ ] `inject` cannot see a Bash edit, so a session that writes with `sed` or a heredoc gets no standards. Worth deciding whether the answer is a `Stop`-hook sweep of the working diff, or just knowing.
- [ ] `agent manifest` lists a split note's index and not its parts, and reads only `[[wikilinks]]`, so an indexer never sees `context/*.md` or `learned/*.md`. It is the versioned surface in INTEGRATION.md, so listing parts is a schema change to agree first.
