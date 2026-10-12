---
name: todo
description: Open work on the hub
kind: todo
---

# TODO

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| Next | 19 |
| Owed | 25 |

<!-- /map -->


## Next

- [ ] Once it is verified good enough for others, ship `.agents` as a `uv tool install` rather than a clone, and only then start versioning: bump `version` in pyproject.toml and tag `vX.Y.Z` releases. Until then it stays 0.1.0, and `agent --version` names the commit.
- [ ] Generate `~/.claude/agents/*.md` from `agents/*.md` at install time, for definitions that want the parent model to invoke them rather than a hook. Without it, native subagents drift as a second copy.
- [ ] Prove the codex backend end to end. The event shapes are confirmed and unit-tested, but no real `agent sub run --backend codex` has been through resume yet.

## Owed


- [ ] Nothing triages what `agent issue` files. An issue from a machine-local session is only useful if it is read, and the only reader is me.
- [ ] Decide what federation means before the schema hardens. `author` is on every row already, but nothing says whose `closed_by` wins when two machines disagree, and nothing syncs.
- [ ] The indexer seam is specified but unexercised: no catalog exists, and `~/.agents` sits outside the indexer's workspace root.

- [ ] `inject` cannot see a Bash edit, so a session that writes with `sed` or a heredoc gets no standards. Worth deciding whether the answer is a `Stop`-hook sweep of the working diff, or just knowing.

- [ ] `agent manifest` lists a split note's index and not its parts, and reads only `[[wikilinks]]`, so an indexer never sees `context/*.md` or `learned/*.md`. It is the versioned surface in INTEGRATION.md, so listing parts is a schema change to agree first.
