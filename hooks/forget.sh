#!/usr/bin/env bash
# Compaction can summarise away what inject.sh delivered while the stamps still claim it is in
# context. Clearing them makes the next edit re-inject whatever that file needs.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

session=$(cat | jq -r '.session_id // "nosession"')
d="${TMPDIR:-/tmp}/agents-$session"
n=$(ls -1 "$d" 2>/dev/null | wc -l)
rm -rf "$d"
hook_log forget "$session" "cleared $n stamps, so the next edit re-injects"
