---
allowed-tools: Bash(agent:*), Bash(jq:*), Read
description: Load the .agents notes for a path, or list what exists
---

## Notes that exist

!`agent manifest --notes . | jq -r '.notes[] | "\(.scope): \(.files | keys | join(", "))"'`

## Your task

The argument is a path, or empty: **$ARGUMENTS**

Read the `.agents` notes that apply to it and say what they change about how you would work there.

- A path: run `agent context <path>`. It prints the notes from that path up to the repo root, outermost first, as an edit there would get them, and names the ones it leaves for you to read.
- Empty: list what exists above and ask which is wanted, rather than loading everything.

Each `.agents` holds up to four notes: `context.md`, what the directory assumes and how its parts fit; `learned.md`, what experiments showed and the traps that already cost a run; `todo.md`, open work; `todo.archive.md`, finished work and why.

Do not summarise a note back at length. Say what is settled, what is still open, and anything that contradicts what you were about to do.
