# Integrating with this repo

Written for indexers, and anything else that wants to index or traverse the standards and notes. Nothing here depends on the indexer: this repo works with none installed, and that is deliberate: a `PreToolUse` hook resolves a standard on every edit and cannot wait on a catalog.

Treat everything below as the stable surface. Everything else is ours to change.

## Ask, do not parse

```sh
agent manifest            # the hub: standards and agent definitions
agent manifest --notes .  # every .agents/ note directory under a tree
```

Both emit JSON tagged `"schema": "agents-hub/1"`. Read that rather than reading frontmatter yourself, and the format of a standard stays free to change without breaking you. The schema string changes when the shape does.

## Two kinds of `.agents`

The name is used for both, which matters when indexing.

| | |
|---|---|
| **the hub** | this repo. Its parent holds `standards/` and `agents/`. One per machine, installed to `~/.agents` |
| **note directories** | the per-directory convention. Any folder in any repo may hold one, containing `context.md`, `learned.md`, `todo.md` |

`agent manifest --notes` flags which is which via `"hub": true`. A discovery pass that treats the hub as a note directory will index `standards/` twice.

## What is stable

`agent manifest` is the only entry point. There is no generated index file to read. Resolution happens in `agentkit` on demand, so nothing goes stale and a fresh clone needs no build step.

Note files carry frontmatter with `name`, `description` and `kind` (`context`, `learned`, `todo`). The body is prose.

Wikilinks are `[[name]]`, optionally `[[name|label]]` or `[[name#section]]`. `name` is a file stem, not a path. A link to something that does not exist yet is intentional: it marks work worth doing, so surface it as unresolved rather than as an error.

## What we want back

Backlinks. `related:` runs one direction only: `ml.runs` layers under `ml`, but `ml` has no idea anything sits below it. "What relies on this assumption" is the question worth answering before a standard changes, and inverting that graph is your side of the seam.

Orphans. A standard nothing relates to, whose `applies` matches nothing, is dead weight still being parsed on every index.

Unresolved links, as a to-write list.

Staleness. A `learned.md` far older than the code beside it is the failure mode this whole convention exists to prevent.

## What we will not do

Resolve standards through you. `applies` matching and `related` traversal stay native, in `agentkit.standards`, because they run in a hook on every edit.

Require a catalog for anything. Degrade to "run the indexer's reindex" and carry on.
