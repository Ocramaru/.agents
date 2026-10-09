---
name: agent-notes
description: How the .agents notes are written: context, learned, todo, todo.archive
applies: context.md, learned.md, todo.md, todo.archive.md, agents.toml
related: markdown
---

# Writing `.agents` notes

Four files, each answering a different question. Putting content in the wrong one is the common failure, and it makes the whole set less useful because nobody knows which to trust.

Only `context.md` loads automatically. The others are advertised by name and section map and read when there is a reason to. An agent that is handed every finding in the tree spends its context before it starts.

Each section below that is named after a file loads only when you edit that file. The rest load whenever you edit any note.

## context.md

What this directory assumes, and how its parts fit together as a whole. The context needed to make a correct change here.

Lead with the constraints that bound everything (a two-column table works well), then how the pieces relate and where a new file goes.

It is not a history and it is not a rationale essay. What was tried and rejected goes in `learned.md`. Keep it to what is true now, because it is read as fact by someone about to edit the code.

Write as much as is true. There is no limit, but this is the one note that is sent on every edit beneath it, so keep an eye on what it costs: `agent doctor` says how many bytes it sends.

When it grows past `map_over`, it sends its section table instead of its body, and is read by section from the file at the lines the table gives. That happens by itself: the table is regenerated on every edit, so a long note already says what is in it and where. Nothing is lost and nothing has to be run.

`agent split context.md` is there when you would rather keep a note as a file per `##`. The index is still sent, the parts are named, and a part carrying `applies:` is sent for those files without being asked for.

Before splitting, check the content is in the right note at all. `learned.md` and `todo.md` are never sent, only named, so what a measurement showed and what is still open cost nothing per session. And a rule about a kind of file, rather than about this place, belongs in a standard. Name the files in `[applies]`.

Still a reference card, not an essay: the constraint, not the argument for it. Reasoning belongs in `learned.md`, named from here.

## learned.md

What we learned. Not injected. Read it when something is surprising, when a measurement looks wrong, or before repeating an experiment.

Once it outgrows a screen, split it: `agent split learned.md` turns each `##` into `learned/<slug>.md` and leaves the note as an index linking to them. An agent then opens the one file it needs rather than seeking into a long one.

Newest at the top, each entry a line or two. Bold the claim, then the number that supports it.

An entry earns its place by the lesson, not the story: the claim, its evidence, and what to do instead. When a file passes a screen, refine it before splitting: merge entries that teach one lesson, cut the narrative, and drop a fixed bug that teaches nothing beyond itself. `agent sub review refine <file>` names the candidates.

Group it: what is settled, facts about the data, diagnoses that held up, measurement traps, what is still open. The traps section is the highest-value part of the convention: every entry is a run already wasted, and the point is that it is wasted once.

Always name which measure a number came from. Two measures of the "same" quantity will disagree, and the disagreement is usually the finding.

Newest-first is load-bearing: the map is read top-down and truncation cuts from the bottom, so the most recent finding is the one that survives either way.

## todo.md

Open work, scoped to this directory, with enough of the reason attached that it can be picked up cold. Not injected either. An agent that already has its task does not need the list, and one that needs a task should read it deliberately.

Track what has been done here as it happens, and move finished items to `todo.archive.md`. Group it as next, owed and housekeeping when there is enough to warrant it.

A task that is really a finding belongs in `learned.md`. A task that is really an assumption belongs in `context.md`.

## todo.archive.md

Finished tasks, moved out of `todo.md` rather than deleted. Same format, newest at the top.

Archive rather than delete because a closed task explains why the code looks the way it does. It is the cheapest available record of a decision, and the reason someone does not undo it next quarter. Move an item when it is done, not when the file gets long.

Keep it out of the injection budget's way: `todo.archive.md` is never injected automatically, so it can grow without cost. Read it deliberately, with `/agents`.

If an archived task produced a finding worth keeping, copy that finding into `learned.md` before archiving. The archive records that work happened; `learned.md` records what it taught.

## The section table

Any note with two or more sections carries a generated table of them under its title, between `<!-- map: ... -->` markers. The opening marker says so, and says how to rebuild it, because whoever just hand-edited the note is looking at that line. Opening a note gives its shape before its contents. It is written by `agent remap` and refreshed by a `PostToolUse` hook; edits between the markers are overwritten.

Nothing is stored anywhere else, so there is no copy to drift: a note is stale exactly when regenerating would change it. Editing one by hand does not fire the hook, so run `agent remap` after.

## Splitting a note

A note that has outgrown one file becomes a directory of the same name: `learned/traps.md` beside `learned/settled.md`. The filename is the map, so nothing has to be generated, nothing goes stale, and an agent opens exactly the section it wants.

`agent split <note>` does it: one file per `##`, slugged from the heading, with the heading kept as the file's `description`. The note itself stays as an index, so a link to it still resolves.

Injection advertises the parts rather than the whole (name, size and description per file), which is the same information a table of contents carried, without a second artifact to keep honest.

This applies to any note. `todo.md` and `context.md` split the same way if either grows.

## agents.toml

Maintained by `agent init`. Records `parent` and `children` so the chain is data rather than a filesystem walk, and `inject` to control how much of this directory reaches a descendant.

The default is `context` everywhere: assumptions load, findings and tasks do not. Set `inject = "full"` on a directory whose findings really are needed on every edit below it, or `"none"` to keep it out entirely.

## All four

Cross-reference with `[[name]]` wikilinks, not relative paths.

Frontmatter carries `name`, `description` and `kind`. The description is what gets shown when a file is too large for the budget, so write it as the one line you would want if the body never loaded.
