# .agents

`.agents` gives every coding agent on a machine the same notes, the same standards and the same rules. Notes live next to the code in `.agents/` directories; standards say how a kind of file should look, everywhere. A hook injects whichever apply when an agent edits a file, and a reviewer checks commits against them.

This repo is public and ships a few starter standards. What is *yours* (your standards, how you like to work, your models) lives in a profile: your own private repo, layered over this one.

## Install

```sh
uv tool install git+https://github.com/Ocramaru/.agents
agent install
```

At a terminal with `gh` logged in, the first install asks about a [profile](#your-profile), your own standards and settings kept in a private repo; on every machine after the first, hand it yours:

```sh
agent install --profile git@github.com:<you>/.agents.profile.git
```

`~/.agents` is this machine's: the profile, `local.toml` and the hook log live there, and an upgrade never touches them.

It also asks what reviews run on: Claude Code, the Codex CLI or Ollama, each shown as found on this machine or with how to install it. The answer is your profile's `[backends] default`, so later machines are not asked, and `--backend <name>` gives it without a terminal. No default ships, so nothing runs on a model until one is chosen; a review started at a terminal before then offers the same question.

With no arguments `agent install` wires up every agent whose config directory exists; name them to be explicit, or `--all` to create the directories. It copies the hooks, commands and `AGENTS.md` into `~/.agents`, where the agents' settings name them, checks `git` and `jq` before writing anything, and moves anything already in place to a `.bak` that never overwrites an older one. A second run reports `ok` for everything.

[`install.sh`](install.sh) runs both steps, and says where to get uv if you have none: `curl -LsSf https://raw.githubusercontent.com/Ocramaru/.agents/main/install.sh | bash`. So does `uvx --from git+https://github.com/Ocramaru/.agents agent install`, which keeps `agent` installed as a uv tool once it is done.

`agent --version` names the release, and `agent update` upgrades it and copies the new hooks into place. To stay on one release, install it by its tag: `uv tool install git+https://github.com/Ocramaru/.agents@<tag>`.

### Working on .agents itself

A clone is the way to change the hub:

```sh
git clone https://github.com/Ocramaru/.agents ~/.agents
~/.agents/bin/agent install
```

`bin/agent` finds its own repo, so the installer runs before anything is on PATH, and `uv` builds the venv on first use. A clone is linked rather than copied, so `agent update` pulling it is the whole upgrade. Its `profile/` and `local.toml` are gitignored: this repo never carries your content.

To have commits reviewed in repos that opt in:

```sh
agent hook install --global
```

That sets git's `core.hooksPath` to [`githooks/`](githooks), whose dispatcher runs each repo's own hooks first and reviews only where the repo has a note in `.agents/`. `agent hook uninstall --global` undoes it.

## Your profile

`agent install` makes one the first time it runs at a terminal with `gh` logged in; without `gh` the question waits until it is. Answer `new` and it lays out `~/.agents/profile`, commits it, and offers to make `<you>/.agents.profile` on GitHub, private, and push it there; it publishes only on a yes. `--profile new` without `gh` makes it all the same and prints the two git commands to push it. On every other machine, `agent install --profile <url>` and you are done.

`--profile` answers the question for a script, or for a machine with no terminal, where install never asks: `new`, a URL to clone to `~/.agents/profile`, a directory to use where it is, or `none` to stay on the starters. The answer is kept in `~/.agents/local.toml`, so a machine is asked once. `agent profile use <dir-or-url>` switches later, and `agent profile init <dir> --use` makes one somewhere else.

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

`update` pulls the latest `.agents` and your profile; a pull that would have to merge stops and says so. `agent profile` shows where yours is and what is in it, and `agent doctor` warns when it has work another machine would miss: an uncommitted edit, a commit not pushed, or no remote at all. `agent profile use <dir-or-url>` switches to a different one.

`agent profile review` reads the whole profile in one conversation, with the starters it replaces, every repo's `.agents/standards/` it can find from where Claude Code has run, and Claude's own auto memory under `~/.claude/projects/*/memory/`. It reports rules that contradict, repeat or sit in the wrong place, and for each memory the `.agents` note or profile file it belongs in. Its findings land in the profile's reviews, so `agent sub reviews --open --root ~/.agents/profile` and `agent sub close` work on them; `--dry-run` lists what it would read.

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

`--last` or `--run <id>` reads a run back as it printed. `--open` lists what is still unresolved; `--path` takes a folder or a pattern like `'*.py'`, and `--agent` a reviewer or a kind. Close findings by the id `--open` shows, `agent sub close <id> --as fixed`, or `--as wrong --reason '…'` so the next review does not raise it again. In a git worktree, a `wrong` or `wontfix` closure is written to the main checkout's reviews as well and a review reads both, so it survives the work landing; `agent sub import <reviews>` copies the ones another checkout's reviews already hold. `agent sub review --recheck` asks again about every file with something open or claimed fixed. An agent reading results should pass `--jsonl`: one JSON object per file, as each finishes.

## What is in here

| | |
|---|---|
| [`AGENTS.md`](AGENTS.md) | the convention: `.agents/` notes, standards, how they load |
| [`standards/`](standards) | the starters, one file per topic, each declaring what it `applies` to and what it is `related` to |
| [`agents/`](agents) | reviewer definitions, each naming the standards it judges against |
| [`hooks/`](hooks) | `session-start`, `inject` and `forget`, the reformatter guard, the notes remapper, and the gate that skips a repeated question |
| [`commands/`](commands) | `/agents` and `/standards`, for loading on demand |
| `settings.hooks.json` | the hooks block `agent install` writes into Claude Code's settings |
| [`githooks/`](githooks) | one dispatcher under every git hook name, for `agent hook install --global` |
| [`templates/`](templates) | what `agent init` writes into a new `.agents/`, and `agent profile init` into a new profile |
| [`INTEGRATION.md`](INTEGRATION.md) | the stable surface for indexers: what to read, and what not to parse |

## What each agent gets

Claude Code is the only one with a hook system, so it gets the full thing: the `.agents/` notes for where a session starts arrive when it starts, standards inject themselves when you edit a file they govern, `.agents/` notes inject themselves when you edit a file near them, and a `PreToolUse` guard, once `[guard]` turns it on, refuses to run a whole-file formatter. `[inject] read = true` makes opening a file with Read do what editing it does; it ships off, since most of what it adds goes to sessions that never edit.

Codex and Gemini have a global instructions file and no hooks. They get the pointer to `AGENTS.md` and nothing auto-injects, which is why `AGENTS.md` carries a one-line summary of each standard rather than only links.

Anything else that reads `~/.<name>/AGENTS.md` works as a generic target: `agent install whatever`.

## Checking it works

```sh
agent status
agent doctor
env -u PYTHONPATH uv run pytest tests/
```

`status` describes this machine on one screen and never fails: the version and whether it is a clone or an install, the profile and what it has not pushed, the default backend and the role each reviewer asks for, the standards and notes in force where you stand, the open findings there, how many of Claude's auto memories are waiting to move into `.agents` or the profile, and whether the hooks are wired. At a terminal what wants a look is yellow and what is broken red; piped, it is plain text with the part named on every line.

`doctor` judges, and covers what tests cannot: whether the hooks are registered here and an install's copies of them are current, whether `agent` on PATH is this install or clone, whether a standard points at one that was renamed, whether a backend's CLI is installed, whether a note's map has drifted, and whether your profile is pushed. The suite runs only against temporary trees, so it never touches your install or your profile.

agentkit is a uv project. `duckdb` is the one heavy dependency, and only `agent sub review` needs it; in a clone without uv, `bin/agent` falls back to plain `python3` and everything but reviews still works.

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

It opens a prefilled issue on this repo in your browser, to read, edit and submit, carrying the commit `.agents` is at and your platform. The link is printed too, for a machine with no browser. Its issues are public, so the repo you were in and your machine's name go in only with `--context`. A title already open opens that issue instead, with the text printed to paste as a comment; without `gh` the draft is made and that check is skipped. `--dry-run` prints the draft and the link and opens nothing, and `agent issue --list` shows what is already filed.
