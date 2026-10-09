---
name: python
description: How Python is run, linted and laid out here
applies: *.py, *.pyi, *.ipynb, pyproject.toml
related: commits
---

# Python

A starter. Put your own `python.md` in your profile and it replaces this one.

Run through the project's environment manager (`uv run`, not bare `python`) so the interpreter is the one the project pinned.

```sh
uv run ruff check --fix
uv run pytest tests/
```

## Never run a whole-file formatter unasked

A formatter rewrites every line it disagrees with, and a three-line change becomes a diff nobody can review. `ruff check --fix` is fine: it only touches what the lint rules select. Anything that rewrites layout (`ruff format`, `black`, `autopep8`) runs only when asked for.

Match the file you are editing. Its indentation, line length and idiom are the standard for that file.

## Comments

One line, factual, and only where needed. Explain why, not what. What an experiment showed goes in `.agents/learned.md`, not in a docstring.

## Tests

Functions and fixtures. Favour targeted tests over exhaustive edge cases, and run the one file you are working on rather than the whole suite.
