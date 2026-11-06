#!/usr/bin/env bash
# Install .agents as a uv tool, then wire it into this machine's agents; arguments go to `agent install`.
# AGENTS_SOURCE installs from elsewhere, such as a release: git+https://github.com/Ocramaru/.agents@v0.2.0
set -euo pipefail

requirement="${AGENTS_SOURCE:-git+https://github.com/Ocramaru/.agents}"
if ! command -v uv >/dev/null 2>&1; then echo "install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; fi
dry_run='' arguments=()
for argument in "$@"; do if [[ "$argument" == "--dry-run" ]]; then dry_run=1; else arguments+=("$argument"); fi; done
if [[ -n "$dry_run" ]]; then printf 'would run: uv tool install %s\n           agent install %s\n' "$requirement" "${arguments[*]:-}"; exit 0; fi

uv tool install "$requirement"
agent="$(uv tool dir --bin)/agent"

# Piped from curl, stdin is this script: `agent install` gets the terminal, so it can ask about a profile
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then exec "$agent" install "$@" </dev/tty; fi
exec "$agent" install "$@"
