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
| How the parts fit | 32 |
| Changing it | 48 |

<!-- /map -->


The hub: standards, notes and review, linked into every agent from `~/.agents`.

## Assumptions

| | |
|---|---|
| hooks | thin bash, logic in `agentkit`; stdlib only on the hook path |
| deps | `duckdb` and `rich`, imported only where used |
| models | subscription CLIs and local endpoints, nothing metered |
| install | `agent install`; symlinks, and the hub answers at `~/.agents` |
| stores | append-only, uuid7 keys, one writer per duckdb file |

## How the parts fit

| | |
|---|---|
| `standards/` | the data: `applies` globs, `related` names; the ones shipped here are starters |
| `profile.py` | where your own standards, reviewers, backends and config live; one replaces a starter by name, and a repo still layers on top |
| `library_for` | the only answer to which standards govern a file; inject and review both use it |
| `inject.py` | standards, notes and open findings for a file, once per session |
| `review.py` | routes each file to the agents whose standards govern it |
| `reviews.py` | the ledger, `<repo>/.agents/.reviews/`, gitignored |
| `config.toml` `[backends]` | where agents run; a role maps to a model |
| `githooks/` | `core.hooksPath`: the repo's own hook first, a review only where a note opts the repo in |
| `hooks/gate.sh` | any hook: skip a call whose answer is known, stamped per session, invalidated by one named file |

Dependencies point one way: `frontmatter` → `standards` → `agents`, and `backends` → `session`.

## Changing it

```sh
env -u PYTHONPATH uv run pytest tests/    # temporary trees only, so nothing here touches the install
uv run ruff check --fix
agent doctor                              # this machine's install, which tests cannot see
```

Done means all three, and the finding written down: a trap into [[learned]], open work into [[todo]].

Work in a git worktree, never in `~/.agents` itself: every agent on the machine runs from it, so an edit there is live for all of them mid-change. Land finished work by fast-forward.

Friction met somewhere else goes to the hub as an issue, with `agent issue "<what was awkward>"`, because another repo's notes are the wrong place for it and would never be read here.

Findings in [[learned]], open work in [[todo]].
