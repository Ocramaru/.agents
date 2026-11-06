---
name: context
description: What this repo assumes and how its parts fit together
kind: context
---

# .agents

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| Assumptions | 22 |
| How the parts fit | 33 |
| Changing it | 54 |

<!-- /map -->


The hub: standards, notes and review, linked into every agent from `~/.agents`.

## Assumptions

| | |
|---|---|
| hooks | thin bash, logic in `agentkit`; stdlib only on the hook path |
| deps | `duckdb` and `rich`, imported only where used |
| models | subscription CLIs and local endpoints, nothing metered |
| install | `agent install`. A clone is linked and answers at `~/.agents`; an install (`uv tool install`) copies its hooks, githooks, commands and AGENTS.md there, recorded by sha256 in `.copied` so a later install sets aside what it did not leave, and its hooks call the `agent` recorded in `.cli`, then PATH |
| paths | `hub.BUNDLED` is what agentkit comes with, read-only; `hub.HOME` is this machine's state. A clone is both, so never assume they differ, nor that they are the same. `profile.py` is only about your profile, and `git.run` runs git anywhere |
| stores | append-only, uuid7 keys, one writer per duckdb file |

## How the parts fit

| | |
|---|---|
| `standards/` | the data: `applies` globs, `related` names; the ones bundled here are starters |
| `profile.py` | where your own standards, reviewers, backends and config live; one replaces a starter by name, and a repo still layers on top |
| `library_for` | the only answer to which standards govern a file; inject and review both use it |
| `standards.py` | `bases` is the only reader of a dot in a name (`latex.robotics` layers on `latex`); `files` the only finder of standard files, a family's folder included. A folder is layout and carries no meaning |
| `inject.py` | standards, notes and open findings for a file, once per session, on Edit and Write, and on Read where `[inject] read` |
| `hooks/session-start.sh` | `inject.start`: the notes for the directory a session starts in, from the repo root down, no standards; stamped with inject's own keys, so the first edit there sends none of it again |
| `memory.py` | Claude Code's auto memory, an inbox: `agent status` counts it and `agent profile review` says where each one belongs |
| `review.py` | routes each file to the agents whose standards govern it; `whole` is the one review over many files in one conversation, which `agent profile review` runs into the profile's reviews |
| `reviews.py` | every review, kept in `<repo>/.agents/.reviews/`, gitignored, one per checkout; a linked worktree writes its `wrong` and `wontfix` closures to the main checkout's as well and reads dismissals from both, while open findings and `fixed` stay where they were made |
| `config.toml` `[backends]` | where agents run; a role maps to a model. No `default` ships: the profile names one, and `backends.get` never falls back to the first |
| `cli/utilities.py` | `CliHelpers.ask` is the only way the CLI asks (yes or no, a choice, text); it returns its default unasked unless stdin and stdout are both terminals, so a question whose default records something checks `CliHelpers.at_terminal()` first |
| `githooks/` | `core.hooksPath`: the repo's own hook first, a review only where a note opts the repo in |
| `hooks/gate.sh` | any hook: skip a call whose answer is known, stamped per session, invalidated by the paths `agent inject --depends` names, any of them the same age as the stamp or newer |
| `install.partition` | the one rule for which settings.json hooks are the hub's: those running `~/.agents/hooks/*.sh`. Install merges by it, and doctor and status judge the block by it |

Dependencies point one way: `frontmatter` → `standards` → `agents`, and `backends` → `session`.

## Changing it

```sh
env -u PYTHONPATH uv run pytest tests/    # temporary trees only, so nothing here touches the install
uv run ruff check --fix
agent doctor                              # this machine's install, which tests cannot see
```

Done means all three, and the finding written down: a trap into [[learned]], open work into [[todo]].

Work in a git worktree, never in `~/.agents` itself: every agent on the machine runs from it, so an edit there is live for all of them mid-change. Finished work moves into `~/.agents` only when nothing needs merging, so it never holds a conflict.

Before a push, `agent sub review` every file changed since `origin/main` and triage it until nothing is open; then the whole diff goes to the owner to read, with a short guide to what changed where. Nothing is pushed or moved into `~/.agents` until they say so.

Words: what `reviews.py` keeps is reviews, never a ledger; `agent update` pulls the latest, never "fast-forward" in prose, while `--ff-only` stays in code. Check new text with `git grep -iE 'ledger|fast[- ]forward'`.

Friction met somewhere else goes to the hub as an issue, with `agent issue "<what was awkward>"`, because another repo's notes are the wrong place for it and would never be read here.

Findings in [[learned]], open work in [[todo]].
