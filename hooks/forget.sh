#!/usr/bin/env bash
# Compaction can summarise away what inject.sh delivered while the stamps still claim it is in
# context. Clearing them makes the next edit re-inject whatever that file needs.
# Author: Marco Cassar (@Ocramaru)
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

session=$(cat | jq -r '.session_id // "nosession"')
# the id becomes part of a path handed to rm -rf, so anything but a plain name is refused
[[ "$session" =~ ^[A-Za-z0-9_-]+$ ]] || { hook_log forget nosession "ERROR  refused a session id that is not a plain name"; exit 0; }
stamps="${TMPDIR:-/tmp}/agents-$session"
count=$(( $(ls -1 "$stamps" 2>/dev/null | wc -l) ))   # arithmetic, since a Mac's wc pads its count
rm -rf "$stamps"
hook_log forget "$session" "cleared $count stamps, so the next edit re-injects"
