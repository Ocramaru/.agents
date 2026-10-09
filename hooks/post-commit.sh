#!/usr/bin/env bash
# Review what the commit just made touched, detached, into this repo's ledger.
#
# A commit must never wait on a model, so this returns immediately and the findings turn up in
# `agent sub reviews --open` when they land. Installed per repo by `agent hook install`, which writes
# a shim calling this, so a `git pull` in the hub updates the logic everywhere.
set -euo pipefail

agent="${1:-auto}"
backend="${2:-}"

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
log="$root/.agents/.reviews/post-commit.log"
mkdir -p "$(dirname "$log")"

args=(sub review "$agent" --commit HEAD)
[ -n "$backend" ] && args+=(--backend "$backend")

printf '\n=== %s %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$(git rev-parse --short HEAD)" >>"$log"

# Detach, so closing the terminal does not kill a review halfway. macOS has no setsid; nohup keeps
# it alive through the hangup, which is the part that matters here.
if command -v setsid >/dev/null 2>&1; then
  AGENTS_HOOK=post-commit setsid "$HOME/.agents/bin/agent" "${args[@]}" >>"$log" 2>&1 </dev/null &
else
  AGENTS_HOOK=post-commit nohup "$HOME/.agents/bin/agent" "${args[@]}" >>"$log" 2>&1 </dev/null &
fi
