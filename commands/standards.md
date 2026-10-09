---
allowed-tools: Bash(agent:*), Bash(jq:*), Read
description: Load the standards for a file, a topic, or list what exists
---

## Standards that exist

!`agent manifest | jq -r '.standards | to_entries[] | "\(.key): \(.value.description)  [\(.value.layers | join(" + "))]"'`

## Your task

The argument is a file, a topic, or empty: **$ARGUMENTS**

Load the standards that apply and say what they change about what you were about to do.

- A file: run `agent inject <file>`. It prints every standard that governs it (by its `applies` globs, the repo's `[applies]`, and `related` followed transitively), already narrowed to that file, with the `.agents` notes on its path.
- A topic: read the standard of that name at the `path` `agent manifest` gives for it, which is your profile's copy when you have one.
- Empty: list what exists above and ask which is wanted, rather than loading all of them.

A repo's own `<repo>/.agents/standards/<name>.md` adds to the standard of that name rather than replacing it; `agent inject` delivers both, the repo's last.

Do not summarise a standard back at length. Say what it requires, and flag anything that contradicts what you were about to do.
