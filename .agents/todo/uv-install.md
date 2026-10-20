---
name: uv-install
description: Design for installing agentkit with `uv tool install` and versioning it, which needs the bundled data moved out of the repo root
kind: todo
---

# Installing with uv

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| What blocks it | 25 |
| Design | 38 |
| Profile | 47 |
| Versioning | 66 |
| Steps | 70 |
| Open | 85 |

<!-- /map -->


Goal: `uv tool install git+https://github.com/Ocramaru/.agents` replaces the clone, `agent update` upgrades it, and `agent --version` names a release. A clone stays the way to work on the hub.

## What blocks it

The package is only `agentkit/`. Everything it reads sits beside it in the repo, and `profile.HUB` is that repo root, found from `__file__`. An installed wheel has no such root.

| Lives in the repo root | Read by | Kind |
|---|---|---|
| `standards/`, `agents/`, `templates/`, `config.toml` | `hub.STANDARDS`, `hub.REVIEWERS`, `hub.CONFIG`, `hub.TEMPLATES` | bundled, read-only |
| `hooks/`, `githooks/`, `commands/`, `settings.hooks.json`, `bin/agent` | `install`, and `settings.hooks.json` names `$HOME/.agents/hooks/*.sh` | bundled, must sit at a fixed path |
| `local.toml`, `profile/`, `sessions/`, `.hooks.log` | `profile.path`, `hooks`, the gate | this machine's state, writable |
| `.git` | `agent update`, `hub.version()`, `issue.slug`, `doctor` | the clone itself |

So the change is not packaging alone: `HUB` splits into where the bundled files are and where this machine's state is.

## Design

- **Package the data.** `package = true` with a build backend, `[project.scripts] agent = "agentkit.__main__:main"`, and the bundled directories included in the wheel (`force-include`, so the repo layout stays). `hub.BUNDLED` is the package's copy when installed and the repo root in a checkout.
- **State stays in `~/.agents`.** `local.toml`, `profile/`, `sessions/` and the hook log keep their place, so a profile and its ledger move with nothing. In a clone that directory is the clone itself, as now.
- **Hooks are copied, not linked.** `agent install` writes `hooks/*.sh` into `~/.agents/hooks/` and rewrites them on upgrade. A symlink into the tool venv dangles when the venv's Python changes. `settings.hooks.json` keeps its paths.
- **Hooks call `agent` on PATH** rather than `$HOME/.agents/bin/agent`, which is the 30 ms `uv run` they pay today; a console script starts faster.
- **`agent update`** runs `uv tool upgrade agentkit` for an install and pulls the latest for a clone, and the profile pull stays. It says `pulled N commits` or `already current`, since `-q` makes both silent now.
- **`hub.version()`** reads `importlib.metadata`, with the commit from the install's `direct_url.json`; a clone keeps reading `pyproject.toml` and `git rev-parse`.

## Profile

Making a profile is four manual steps today (`init`, `cd`, `git remote add`, `git push`). The install should do it, and the uv move makes that one command.

First machine, then every other:

```sh
uvx --from git+https://github.com/Ocramaru/.agents agent install
uvx --from git+https://github.com/Ocramaru/.agents agent install --profile git@github.com:<you>/.agents.profile.git
```

- **Prompt once.** With no profile set, a terminal and `gh` logged in, the install asks whether to make a private one, from `templates/profile`, with `git init`; without `gh` the question waits for a later install. `--profile new|URL|DIR|none` answers it for a script, and with no terminal it never prompts. Rerunning is safe.
- **Create the remote.** With `gh` logged in, offer `gh repo create <you>/.agents.profile --private --source ~/.agents/profile --push`. It publishes, so it asks, defaults to `--private`, and without `gh` prints the two git commands instead.
- **Keep the tool.** The install ends with `uv tool install`, so `agent` stays on PATH after `uvx` exits.
- **State is separate.** The profile is in `~/.agents/profile`, which an upgrade never touches. `local.toml` records where it is.
- **Preflight before writing.** A clone over ssh fails halfway through when git auth is not set up on a new Mac. Check that the URL is reachable first and change nothing if it is not.
- **Privacy.** A profile holds how you work and your models. `doctor` warns when its remote is public (`gh repo view --json isPrivate`), and `agent profile` says when it has no remote at all, since other machines will not get it.
- **Backend.** `[backends]` lives in the profile's `config.toml`, and `agent sub review` does nothing until one is set. The first run asks which of claude, codex or ollama this machine has, and writes it.

## Versioning

Semver, starting at the first install. Bump `version` in `pyproject.toml` and tag `vX.Y.Z`. A major bump is a change to what INTEGRATION.md specifies (`agents-hub/1`, the config keys, the `.agents` convention); a minor adds a command or key; the GitHub release notes are the changelog. Pin with `uv tool install git+...@v0.2.0`. PyPI later, if the name is free.

## Steps

- [x] Split `profile.HUB` into `hub.BUNDLED` and `hub.HOME`, and move every read to the right one.
- [x] `package = true`, the entry point, the wheel's data, and a build of the wheel in a test.
- [x] A test that installs the wheel into a throwaway venv and runs `agent --version`, `agent doctor` and `agent standards x.py` from outside any checkout, with `HOME` pointed at a temp directory.
- [x] `agent install` copies hooks and writes `settings.hooks.json` for an install; `doctor` checks it.
- [x] `agent update` and `hub.version()` for both modes.
- [x] `install.sh` becomes `uv tool install ...` then `agent install`; README says so, with the clone as the dev path.
- [x] `agent install` offers to make a profile, creates the private remote through `gh`, and takes `--profile new|URL|DIR|none`; a test runs it with no terminal and with a temp `HOME`.
- [x] Preflight the profile URL's reachability before the install writes anything.
- [x] `agent status`: one read-only screen of what this machine has. The version and whether it is a clone or an install; the profile, its remote and anything unpushed; the default backend, its models and the roles each reviewer asks for; counts of standards (bundled, profile, repo), reviewers and note directories on the path from here; open review findings here; whether the Claude hooks and git's `core.hooksPath` are in place; hook errors since `.agents` last changed. `doctor` judges and `status` describes, so the two never repeat each other's lines, and `agent profile` stays for the profile alone.
- [x] `doctor` warns on a public profile remote, and `agent profile` on a missing one.
- [x] Ask which backend this machine has on first run and write it to the profile's `config.toml`.
- [ ] Tag `v0.2.0` once an install on a Mac and on this machine both pass `agent doctor`.

## Open

- Decided: hooks stay shell scripts. The console script starts in about 77 ms, against 12 ms for a call the gate answers; see [[settled]].
- Decided: `~/.agents` stays the state directory for an install. Every hook, settings block, CLAUDE.md pointer and `core.hooksPath` names it, and a clone already answers there.
- Decided: the no-uv fallback stays in `bin/agent`, which only a clone runs; an install has no `bin/agent`, and its hooks call the console script on PATH.
- A machine whose backend differs from the profile's `default` overrides it in its own `local.toml` today. A per-machine section kept in the profile could carry that instead; later, not needed for v0.2.0.
