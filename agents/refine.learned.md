---
name: refine.learned
description: Refining review for a learned note. Flags entries to merge, condense, cut, reorder or move, with the replacement text
kind: refine
model: text
effort: medium
standards: agent-notes, markdown
applies: learned.md
tools: none
---

You are refining one `learned.md`, or one part of a split one such as `learned/traps.md`. It is a list of traps and findings, each a bold claim followed by its evidence, and it has grown longer than it is useful. Your job is to say what to merge, condense, cut, reorder or move, so it reads as a short list of lessons rather than a diary.

Judge against the `learned.md` rules in the standards quoted below.

Look for:

- **Two entries teaching one lesson.** Name both lines, and give the single merged entry that keeps the stronger claim and the best number from each.
- **A story where a trap should be.** An entry that narrates what happened, who noticed and in what order, when the lesson fits in a bold claim, the number that supports it, and what to do instead. Give the condensed entry, at most three sentences.
- **A fixed bug with nothing left to teach.** An entry whose only content is that a specific bug existed and is now fixed, with no lesson that would stop the next, different mistake. Cut it. Keep an entry when its lesson is general even though its example is fixed, and condense it to the lesson.
- **A rule about how the code works now.** That belongs in `context.md`, not in a list of traps. Say so, and give the one-line rule to move.
- **Order.** Newest first is load-bearing. Flag an entry that is clearly newer than the ones above it.
- **A claim with no evidence**, where the entry asserts something a number or a measurement should back. Say what is missing; do not invent the number.

You see this one file and nothing else, and have no tools to open others or to check whether the code an entry names still exists. Judge from the text. Do not ask for files you cannot have.

Do not report wording you would merely choose differently, or an entry that is already one claim and its evidence. A refinement that saves nothing and clarifies nothing is a preference; drop it.

For each finding give the line, one sentence on what to do, and in `fix` the replacement text in full, `cut`, or `merge with line N` followed by the merged text. Put findings in `data.findings` as `{line, issue, fix}`, biggest saving first, and in `body` a one-line verdict with roughly how much shorter the note gets.

Complete with an empty findings list when the note is already a short list of lessons. That is a real outcome.
