---
name: uv-install
description: Design for installing agentkit with `uv tool install` and versioning it, which needs the shipped data moved out of the repo root
kind: todo
---

# Installing with uv

<!-- map: generated. Edit the note, not this; after a manual edit run `agent remap` -->

| section | line |
|---|---|
| What blocks it | 24 |
| Design | 37 |
| Versioning | 46 |
| Steps | 50 |
| Open | 60 |

<!-- /map -->


Goal: `uv tool install git+https://github.com/Ocramaru/.agents` replaces the clone, `agent update` upgrades it, and `agent --version` names a release. A clone stays the way to work on the hub.

## What blocks it

The package is only `agentkit/`. Everything it reads sits beside it in the repo, and `profile.HUB` is that repo root, found from `__file__`. An installed wheel has no such root.

| Lives in the repo root | Read by | Kind |
|---|---|---|
| `standards/`, `agents/`, `templates/`, `config.toml` | `standards.GLOBAL`, `agents.AGENTS`, `profile.CONFIG`, `profile.TEMPLATES` | shipped, read-only |
| `hooks/`, `githooks/`, `commands/`, `settings.hooks.json`, `bin/agent` | `install`, and `settings.hooks.json` names `$HOME/.agents/hooks/*.sh` | shipped, must sit at a fixed path |
| `local.toml`, `profile/`, `sessions/`, `.hooks.log` | `profile.path`, `hooks`, the gate | this machine's state, writable |
| `.git` | `agent update`, `version()`, `issue.slug`, `doctor` | the clone itself |

So the change is not packaging alone: `HUB` splits into where the shipped files are and where this machine's state is.

## Design

- **Package the data.** `package = true` with a build backend, `[project.scripts] agent = "agentkit.__main__:main"`, and the shipped directories included in the wheel (`force-include`, so the repo layout stays). `profile.SHIPPED` is the package's copy when installed and the repo root in a checkout.
- **State stays in `~/.agents`.** `local.toml`, `profile/`, `sessions/` and the hook log keep their place, so a profile and its ledger move with nothing. In a clone that directory is the clone itself, as now.
- **Hooks are copied, not linked.** `agent install` writes `hooks/*.sh` into `~/.agents/hooks/` and rewrites them on upgrade. A symlink into the tool venv dangles when the venv's Python changes. `settings.hooks.json` keeps its paths.
- **Hooks call `agent` on PATH** rather than `$HOME/.agents/bin/agent`, which is the 30 ms `uv run` they pay today; a console script starts faster.
- **`agent update`** runs `uv tool upgrade agentkit` for an install and `git pull --ff-only` for a clone, and the profile pull stays. It says `pulled N commits` or `already current`, since `-q` makes both silent now.
- **`version()`** reads `importlib.metadata`, with the commit from the install's `direct_url.json`; a clone keeps reading `pyproject.toml` and `git rev-parse`.

## Versioning

Semver, starting at the first install. Bump `version` in `pyproject.toml` and tag `vX.Y.Z`. A major bump is a change to what INTEGRATION.md specifies (`agents-hub/1`, the config keys, the `.agents` convention); a minor adds a command or key; the GitHub release notes are the changelog. Pin with `uv tool install git+...@v0.2.0`. PyPI later, if the name is free.

## Steps

- [ ] Split `profile.HUB` into `SHIPPED` and `HOME`, and move every read to the right one.
- [ ] `package = true`, the entry point, the wheel's data, and a build of the wheel in a test.
- [ ] A test that installs the wheel into a throwaway venv and runs `agent --version`, `agent doctor` and `agent standards x.py` from outside any checkout, with `HOME` pointed at a temp directory.
- [ ] `agent install` copies hooks and writes `settings.hooks.json` for an install; `doctor` checks it.
- [ ] `agent update` and `version()` for both modes.
- [ ] `install.sh` becomes `uv tool install ...` then `agent install`; README says so, with the clone as the dev path.
- [ ] Tag `v0.2.0` once an install on a Mac and on this machine both pass `agent doctor`.

## Open

- Whether hooks should stay shell scripts at all, or become `agent hook <name>`. The gate is shell to avoid a fork per edit, so keep them unless the console script's start time is as good.
- Whether `~/.agents` stays the state directory name for an install, since it is also what the convention is called.
- The no-uv fallback in `bin/agent` (plain `python3` for hooks) goes away for an install, which needs uv to exist.
