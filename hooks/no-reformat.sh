#!/usr/bin/env bash
# Refuse the formatters config.toml's [guard] names; `agent guard` parses the command, and this only moves bytes.
# It fails open: when the guard cannot run, the command goes through and the log says so.
# Author: Marco Cassar (@Ocramaru)
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

payload=$(cat)
command=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')
session=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"')
[ -n "$command" ] || exit 0

rc=0
found=$("$HOME/.agents/bin/agent" guard "$command" 2>/dev/null) || rc=$?
if [ "$rc" -eq 0 ]; then
  hook_log no-reformat "$session" "allow  $(printf '%s' "$command" | head -c 80 | tr '\n' ' ')"
  exit 0
fi
if [ -z "$found" ]; then
  hook_log no-reformat "$session" "ERROR  guard would not run, allowing rc=$rc"
  exit 0
fi

echo "Refusing to run $found" >&2
hook_log no-reformat "$session" "BLOCKED  ${found%%: *}  --  $(printf '%s' "$command" | head -c 80 | tr '\n' ' ')"
exit 2
