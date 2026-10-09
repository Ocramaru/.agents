# .agents

`.agents` gives every coding agent on a machine the same notes, the same standards and the same rules. Notes live next to the code in `.agents/` directories; standards say how a kind of file should look, everywhere. A hook injects whichever apply when an agent edits a file, and a reviewer checks commits against them.

This repo is public and ships a few starter standards. What is *yours* (your standards, how you like to work, your models) lives in a profile: your own private repo, layered over this one.

## Install

```sh
git clone https://github.com/Ocramaru/.agents ~/.agents
~/.agents/bin/agent install
```

That runs on the starters. With a profile of your own:

```sh
~/.agents/bin/agent install --profile git@github.com:<you>/.agents.profile.git
```

`--profile` takes a URL, which it clones to `~/.agents/profile`, or a directory, which it uses where it is. Either way it is remembered for this machine in `~/.agents/local.toml`, so it is passed once per machine and never again. Both `profile/` and `local.toml` are gitignored here: this repo never carries your content, and where your profile lives is a fact about one machine.

`bin/agent` finds its own repo, so the installer runs before anything is on PATH, and `uv` builds the venv on first use. With no arguments it wires up every agent whose config directory exists; name them to be explicit, or `--all` to create the directories. It symlinks rather than copies, checks `git` and `jq` before writing anything, and moves anything already in place to a `.bak` that never overwrites an older one. A second run reports `ok` for everything.

To have commits reviewed in repos that opt in:

```sh
agent hook install --global
```

That sets git's `core.hooksPath` to [`githooks/`](githooks), whose dispatcher runs each repo's own hooks first and reviews only where the repo has a note in `.agents/`. `agent hook uninstall --global` undoes it.

## Your profile

Make one, put your standards in it, and push it somewhere private:

```sh
agent profile init --use
cd ~/.agents/profile
git remote add origin git@github.com:<you>/.agents.profile.git
git push -u origin main
```

`init` lays out the directories `.agents` reads and starts a git repo; `--use` makes it this machine's. On every other machine, `agent install --profile <url>` and you are done.

| | |
|---|---|
| `standards/*.md` | named like a starter, it replaces it; named anything else, it is added |
| `agents/*.md` | reviewer definitions, the same way |
| `config.toml` | `[review]`, `[inject]`, `[guard]` and `[backends]` over the ones in `.agents`: review excludes accumulate, a backend replaces the one of the same name, and your `default` wins |
| `AGENTS.md` | how you work, loaded into every session after the one here |

No profile? Any `config.toml` section can go in `~/.agents/local.toml`, gitignored and read last. `[guard] enabled = true` there turns on the formatter guard, which refuses whole-file formatters such as `black` and `ruff format` and ships off.

A profile replaces where a repo adds. A standard in `<repo>/.agents/standards/` still layers on top of whichever won, both delivered and the repo's last, because a repo adds to your rules where a profile *is* them.

Keeping machines in step:

```sh
agent update
agent profile
```

`update` pulls `.agents` and your profile, fast-forward only, so a pull that needs a merge stops and says so. `agent profile` shows where yours is and what is in it, and `agent doctor` warns when it has work another machine would miss: an uncommitted edit, a commit not pushed, or no remote at all. `agent profile use <dir-or-url>` switches to a different one.

Tests never see your profile: the suite sets `AGENTS_PROFILE` empty, which means none. The same variable pointed at a directory overrides `local.toml` for one shell.

## Reviewing

```sh
agent sub review src/
agent sub review simplify src/models/ --dry-run
agent sub review refine docs/ .agents/
```

With a path and no reviewer named, each file goes to whichever reviewers' standards govern it; `agent sub agents` lists them. `--dry-run` shows that routing without asking a model anything. Each file says when it starts and prints its result as it finishes (the verdict, every finding with its fix, and the command that acts on it), so a long run is read as it goes. An empty file is noted and never sent.

A kind of review can have variants, one reviewer per kind of file. `refine` shortens a document without losing a fact, and `refine.learned` does it for a learned note: asking for `refine` sends each file to the one made for it, and `--variant learned` or `--variant default` picks one.

Every run prints an id, and everything it found is kept in `.agents/.reviews/`, gitignored:

```sh
agent sub reviews --last
agent sub reviews --open --path src/models/
agent sub reviews --failed --agent logic
```

`--last` or `--run <id>` reads a run back as it printed. `--open` lists what is still unresolved; `--path` takes a folder or a pattern like `'*.py'`, and `--agent` a reviewer or a kind. Close findings by the id `--open` shows, `agent sub close <id> --as fixed`, or `--as wrong --reason '…'` so the next review does not raise it again. `agent sub review --recheck` asks again about every file with something open or claimed fixed. An agent reading results should pass `--jsonl`: one JSON object per file, as each finishes.

## What is in here

| | |
|---|---|
| [`AGENTS.md`](AGENTS.md) | the convention: `.agents/` notes, standards, how they load |
| [`standards/`](standards) | the starters, one file per topic, each declaring what it `applies` to and what it is `related` to |
| [`agents/`](agents) | reviewer definitions, each naming the standards it judges against |
| [`hooks/`](hooks) | `inject` and `forget`, the reformatter guard, the notes remapper, and the gate that skips a repeated question |
| [`commands/`](commands) | `/agents` and `/standards`, for loading on demand |
| `settings.hooks.json` | the hooks block `agent install` writes into Claude Code's settings |
| [`githooks/`](githooks) | one dispatcher under every git hook name, for `agent hook install --global` |
| [`INTEGRATION.md`](INTEGRATION.md) | the stable surface for indexers: what to read, and what not to parse |

## What each agent gets

Claude Code is the only one with a hook system, so it gets the full thing: standards inject themselves when you edit a file they govern, `.agents/` notes inject themselves when you edit a file near them, and a `PreToolUse` guard refuses to run a whole-file formatter.

Codex and Gemini have a global instructions file and no hooks. They get the pointer to `AGENTS.md` and nothing auto-injects, which is why `AGENTS.md` carries a one-line summary of each standard rather than only links.

Anything else that reads `~/.<name>/AGENTS.md` works as a generic target: `agent install whatever`.

## Checking it works

```sh
agent doctor
env -u PYTHONPATH uv run pytest tests/
```

`doctor` covers what tests cannot: whether the hooks are registered here, whether `agent` resolves to this repo, whether a standard points at one that was renamed, whether a backend's CLI is installed, whether a note's map has drifted, and whether your profile is pushed. The suite runs only against temporary trees, so it never touches your install or your profile.

agentkit is a uv project. `duckdb` is the one heavy dependency, and only `agent sub review` needs it; without uv, `bin/agent` falls back to plain `python3` and everything but reviews still works.

## Adding a standard

Drop a file in your profile's `standards/`, give it frontmatter, commit and push.

```markdown
---
name: shell
description: How shell scripts are written here
applies: *.sh, *.bash
related: commits
---
```

A dot in the name is a namespace: `ml.runs` layers under `ml` if that exists, general first. A hyphen is just a compound word. `applies` is matched against the filename alone, never the path, so the globs are basename patterns. `related` names other standards to pull in with it, followed transitively.

A standard meant for everyone belongs here instead, as a starter: open a pull request.

## Reporting friction

Something about `.agents` is awkward, from inside another repo:

```sh
agent issue "sub close wants file:line but --open prints the file alone" --body "what I was doing"
```

It files against this repo, carrying the commit `.agents` is at and your platform. Its issues are public, so the repo you were in and your machine's name go in only with `--context`. A title already open gets a comment instead of a second issue. `--dry-run` prints it without filing, and `agent issue --list` shows what is already filed.
