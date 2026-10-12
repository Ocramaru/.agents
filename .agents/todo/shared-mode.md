---
name: shared-mode
description: Design for noticing a shared repo and stepping the profile back by a chosen level
kind: todo
---

# Shared mode

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| What it notices | 27 |
| The mode | 39 |
| Finer control | 61 |
| Line notices | 75 |
| Seeing it | 85 |
| Cost | 96 |
| Build order | 100 |
| Open | 107 |

<!-- /map -->


Your profile is your taste, and it should not be imposed on code other people write. Shared mode is how `.agents` notices it is in someone else's company and steps back by a level you choose.

## What it notices

Git already records who wrote what, so nothing has to be set up.

| Level | Question | How |
|---|---|---|
| repo | does anyone else commit here? | one `git log` of authors, cached per repo, compared with your identities |
| file | who created this file? | the commit that added it; an uncommitted file is yours |
| lines | who wrote the lines being edited? | `git blame -L` on the edited range only |

Your identities are your git `user.email` plus any your profile lists, so every address you commit under counts as you.

## The mode

Shared mode turns on by itself when anyone else has committed, and you can set it per repo. Its level decides how far your profile steps back.

| `shared` | Your standards | Your tool config (ruff ignores, formatter guard) | Authorship | Their files and lines |
|---|---|---|---|---|
| `off` | apply | written into the repo's config | yes | yours to restyle |
| `polite` | guide new code | the repo's own config wins | only on files you create | kept in their idiom, with a line notice |
| `restricted` | not sent | the repo's own config wins | no | kept in their idiom, with a line notice |

`off` is the default where only you commit, and `polite` is the default once anyone else does. `restricted` is for a repo where you are a guest.

```toml
# .agents/.local/agents.toml: just you, never committed
shared = "restricted"

# .agents/agents.toml: everyone working in the repo
shared = "polite"
```

`.local` wins over `agents.toml`, which wins over what git shows.

## Finer control

A standard or a config section can say where it applies, for the cases a level does not cover:

```markdown
---
name: authorship
applies: *.py, *.sh, *.go
where: solo, yours
---
```

`where` takes `solo` or `shared` for the repo and `yours` or `theirs` for the file, and every listed label must hold. Without `where`, the level decides.

## Line notices

When an agent edits lines someone else wrote, the edit hook says so once per author per file per session, in one line:

```
Lines 40-52 are Alex Chen's (3 weeks ago, a1b2c3d "Mask the unknown layer before scoring"). Keep their idiom; change only what the task needs.
```

Nothing is said for your own lines, for reads, or for new files. A range with many authors names the few most recent commits; `git show <hash>` is there for more.

## Seeing it

`agent profile` names the mode where you stand and why, and what it does to each preference:

```
shared: polite (alex@example.com committed here)
  python    guides new code
  authorship  only on files you create
  ruff      the repo's config wins
```

## Cost

One cached `git log` per repo, one git call the first time a file is edited in a session, and one `git blame -L` per edit of lines someone else wrote. Small next to the rest of the edit hook.

## Build order

1. Detection: the repo, file and line signals, and your identities.
2. The `shared` setting and its three levels, with `where:` for finer control.
3. Line notices in the edit hook.
4. Authorship as its own standard, and your ruff ignores in the profile, both reviewed with you before they land.

## Open

- Whether `polite` should send your standards for files someone else created, or only for files you create.
