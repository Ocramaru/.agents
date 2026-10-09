---
name: markdown
description: How markdown is written here
applies: *.md, *.mdx, *.markdown
related: commits
---

# Markdown

Never hand-format. Do not hard-wrap paragraphs at a column, and do not pad with spaces to line things up. The renderer does layout, and hand-formatting only survives until someone edits the sentence.

A paragraph is one line, however long. Anything tabular goes in a table, not an indented block with padded columns. Code goes in a fenced block, not an indented one, so the language is declared.

Link between documents rather than repeating them. If two files need the same paragraph, one of them should own it and the other should point.

Inside `.agents/` notes and `standards/`, cross-reference with `[[name]]` wikilinks rather than relative paths, so a link survives the file moving and an indexer can build the graph without a markdown parser. `name` is a file stem. Linking to something that does not exist yet is fine: it marks work worth doing.

Prose over structure. A heading, a table, and a checklist each earn their place by being the clearest form for that content. Reach for a paragraph first, and do not impose section scaffolding on three sentences.
