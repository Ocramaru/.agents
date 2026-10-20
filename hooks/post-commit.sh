#!/usr/bin/env bash
# Review what the commit just made touched, detached, into this repo's reviews.
#
# A commit must never wait on a model, so this returns immediately and the findings turn up in
# `agent sub reviews --open` when they land. Installed per repo by `agent hook install`, which writes
# a shim calling this, so updating the hub updates the logic everywhere.
# Author: Marco Cassar (@Ocramaru)
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

agent="${1:-auto}"
backend="${2:-}"

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
log="$root/.agents/.reviews/post-commit.log"
mkdir -p "$(dirname "$log")"

commit=$(git rev-parse HEAD)   # read here: the review starts later, when another commit may have moved HEAD
args=(sub review "$agent" --commit "$commit")
[[ -n "$backend" ]] && args+=(--backend "$backend")

printf '\n=== %s %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "${commit:0:7}" >>"$log"

# Detach, so closing the terminal does not kill a review halfway. macOS has no setsid; nohup keeps
# it alive through the hangup, which is the part that matters here.
if command -v setsid >/dev/null 2>&1; then
  AGENTS_HOOK=post-commit setsid "$AGENTS_CLI" "${args[@]}" >>"$log" 2>&1 </dev/null &
else
  AGENTS_HOOK=post-commit nohup "$AGENTS_CLI" "${args[@]}" >>"$log" 2>&1 </dev/null &
fi
