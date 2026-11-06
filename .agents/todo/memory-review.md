---
name: memory-review
description: Design for `agent memory review`: condense Claude Code's auto memory and move each fact to the note or profile entry where it costs least
kind: todo
---

# Memory review

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| What one conversation reads | 26 |
| What it returns | 37 |
| Where a fact goes | 49 |
| Condensing | 58 |
| Applying | 62 |
| Around it | 66 |
| Open | 72 |

<!-- /map -->


Claude Code's auto memory is read only by sessions started in the folder it was saved from, so it piles up where little reads it. `memory.py` already finds the inbox and the place each project folder is; this review decides where each memory belongs and proposes the text that moves it there.

## What one conversation reads

One conversation per project folder, run in parallel, so each prompt stays local and small:

- that folder's memory files, without `MEMORY.md`
- the `.agents` chain of `memory.place(folder)`, root down: every `context.md`, and the section maps of `learned.md` and `todo.md`
- the profile's `AGENTS.md` and the standards index (name and description, not bodies)
- the `agent-notes` and `profile-entries` standards, so a proposed entry already reads as its destination should

A folder whose place no longer exists gets the profile alone, and its memories are judged as `stale` or profile candidates.

## What it returns

One verdict per memory, kept in the profile's reviews like any finding:

| verdict | means | carries |
|---|---|---|
| `move` | it belongs in a note or the profile | the destination file and section, and the exact text to add |
| `merge` | the same fact as other memories | which, and the one entry they become |
| `covered` | already said somewhere | where, quoted |
| `stale` | the notes or the code contradict it | the evidence |
| `keep` | fits no note or profile entry | why |

## Where a fact goes

By what each place costs a session:

- `context.md` is sent on every edit beneath it: only a rule a session would otherwise get wrong
- `learned.md` and `todo.md` are named, never sent: measurements, traps, open work
- `.agents/.local/` for what is true on this machine only
- the profile, as a standard or an `AGENTS.md` section, for what holds in more than one repo

## Condensing

After the per-folder conversations, one short pass over their `move` verdicts alone: a fact proposed for two repos becomes one profile entry, and folders that are the same repo (a worktree, a symlinked memory dir, a copy like `act` beside `rag`) collapse to one.

## Applying

Nothing is written by the review. The verdicts are read with `agent sub reviews --open --root <profile>`; a session applies the accepted ones with Edit and Write, so standards load and each change is a diff; a profile or standard change is quoted word for word first. A memory file is deleted only once its destination is committed, and its finding is closed as `fixed` then.

## Around it

- `agent profile review` stops reading memory: its subject is the profile against the starters and the repo overrides, and its prompt shrinks by the inbox.
- `agent status` suggests `agent memory review` once the inbox passes a threshold, about 20 files.
- `review.whole` already runs one conversation over many files into a root's reviews; this needs it per folder, plus the condensing pass.

## Open

- Whether the condensing pass is a model call or plain grouping of identical destinations.
- Whether `keep` memories stay in Claude's memory or move to a profile-level `.local` file.
