# How agents work here

Two things carry across sessions: the `.agents/` notes that live next to the code, and the standards in `~/.agents/standards`. Notes are about one directory. Standards are about how an artifact should look, everywhere.

## The `.agents/` convention

Any directory may hold an `.agents/` directory. It holds up to three files, and each answers a different question:

| | |
|---|---|
| `context.md` | what this directory assumes and how its parts work as a whole: the context needed to change it correctly |
| `learned.md` | what we have learned: what experiments showed, and the traps that already cost a run |
| `todo.md` | open work, scoped to this directory |

Notes are scoped to where they sit. A repo-root `.agents/` is repo-wide; a package's `.agents/` is about that package. They compose: outermost first, most specific last, so a package can narrow or override what the root says.

`todo.archive.md` is optional and holds finished tasks. Move things there rather than deleting them; a closed task explains why the code looks the way it does.

### What goes in each

The [`agent-notes`](standards/agent-notes.md) standard covers this, and it loads automatically when you edit one of these files.

### How the notes reach you

One `PreToolUse` hook resolves both the standards and the notes for a file and injects what has not already been sent this session. Only `context.md` loads automatically; `learned.md` and `todo.md` are named with their section maps so you can read one when you have a reason to. A `PostCompact` hook clears the stamps, since compaction can summarise the notes away while the stamps still claim they are in context.

`/agents <path-or-topic>` and `/standards <file-or-topic>` load either on demand.

The hook fires on the Edit and Write tools only. A file written through Bash (`sed`, a heredoc) gets nothing, so edit with the tools when a standard should apply.

What the person sees: a one-line notice, `PreToolUse:Edit says: .agents loaded 2 standards, 1 note for <file>`, and only when something was delivered. Delivery is once per file per session, so a second edit to the same file shows no notice. That is the dedupe working, not the hook failing. Do not tell the person the hook is invisible, and do not send them to `claude --debug` or `/hooks`. `agent hooks --hook inject` lists every edit the hook saw: `sent` delivered, `quiet` already delivered this session, `none` nothing governs the file, `ERROR` the hook broke.

When notes are injected, do not summarise them back at length. Say what is settled, what is still open, and anything that contradicts what you were about to do.

## Standards

Standards live once, in `~/.agents/standards`, one file per topic. Each declares in its frontmatter what it `applies` to and what it is `related` to. Editing a file loads the standards that govern it and everything those relate to, followed transitively: a training script pulls the run rules, which pull the Python rules, which pull the commit format.

| | |
|---|---|
| [`markdown`](standards/markdown.md) | never hand-format: no hard-wrapped paragraphs, no space padding, tabular data in a table |
| [`python`](standards/python.md) | run through the project's environment, never a whole-file formatter unasked, match the file |
| [`shell`](standards/shell.md) | bash, `set -euo pipefail`, quote everything, dry-run and portable to macOS |
| [`commits`](standards/commits.md) | subject then one-line bullets, no run numbers, no unrelated churn |
| [`agent-notes`](standards/agent-notes.md) | what context, learned, todo and todo.archive each hold |

These are starters. Your own standards live in your profile — `~/.agents/profile/standards`, its own private repo — where one named like a starter replaces it and any other is added. `agent profile` says where yours is.

A repo adds to a standard by name in `<repo>/.agents/standards/<name>.md`: both are delivered, the repo's last, and where they disagree it wins. That is how a fork whose upstream mandates `ruff format` lives alongside a global rule forbidding it, and `[guard] enabled = false` in its `.agents/agents.toml` lets the command run there.

To make a global standard cover a file its globs miss, such as a site whose prose lives in `data/projects.json`, name the file in `<repo>/.agents/agents.toml` under `[applies]`, for example `<standard> = ["projects.json"]`, rather than widening the global globs or copying the standard. Globs match the filename alone, never the path, so `data/*.json` matches nothing.

A standard narrows itself by section: a `##` heading that names a file, like `## todo.md` in [`agent-notes`](standards/agent-notes.md), loads only when you edit that file, while every prose heading always loads. A split note's part is governed as its note, so `learned/01-traps.md` gets the `learned.md` rules.

`/standards <file-or-topic>` loads them on demand. Read the full file before acting on a one-line summary above. The summary exists so the rule is never entirely unknown, not to stand in for it.

## Working with it

### Anything injected is paid for every session

`AGENTS.md`, the standards and every `context.md` are read by each session that touches them. Write them as reference cards: the rule, not the case for it. Add a line only if a session without it would get something wrong.

### Findings outlive sessions

If a session establishes something that would have saved the session (a trap, a constraint, a measurement that misleads), write it into the nearest `learned.md` before finishing. That is the entire point of the convention, and it is the step most often skipped.

When what was learned is about the tooling itself rather than the repo you are in (a command that is awkward, a hook that did nothing, a standard that contradicts itself), `agent issue "<one line>"` files it against the hub, since this repo's notes are the wrong place and nobody would read it there. Same complaint twice becomes one issue with two comments.
