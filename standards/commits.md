---
name: commits
description: Commit message format, and what never goes in one
applies: COMMIT_EDITMSG
related:
---

# Commits

A starter. Put your own `commits.md` in your profile and it replaces this one. That is where your name, email and trailer rules belong.

## Format

A one-line subject, then one bullet per change, each bullet one line. Say what changed, not how you found out.

```
Fix the scoring mask and checkpointing

- Mask the score to answerable pixels
- Keep a periodic snapshot alongside the best checkpoint
```

Numbers from a run do not go in a commit: results move, and a commit is permanent. They belong in the nearest `.agents/learned.md`, where a wrong one can be corrected.

## Scope

Never let unrelated churn ride along. If `git diff --stat` shows files you did not mean to touch, stop and look before committing. Name the paths you mean: `git add X && git commit` commits everything already staged, not only `X`.

## Before pushing

Read `git log @{u}..` as one change. A commit that fixes, trims or renames work not yet pushed belongs in the commit it amends, or merged with the neighbours it finishes: pushed history says what changed, not the order it was found in. Squash by contiguous runs where you can, since `git commit-tree <last>^{tree}` keeps the final tree exact with no conflicts to resolve.
