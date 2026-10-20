#!/usr/bin/env bash
# Compaction can summarise away what inject.sh delivered while the stamps still claim it is in
# context. Clearing them makes the next edit re-inject whatever that file needs.
# Author: Marco Cassar (@Ocramaru)
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

session=$(cat | jq -r '.session_id // "nosession"')
stamps="${TMPDIR:-/tmp}/agents-$session"
count=$(ls -1 "$stamps" 2>/dev/null | wc -l)
rm -rf "$stamps"
hook_log forget "$session" "cleared $count stamps, so the next edit re-injects"
