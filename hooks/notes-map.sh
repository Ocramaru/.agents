#!/usr/bin/env bash
# PostToolUse: refresh a note's section table after it is edited. Idempotent and cheap, so it can
# run on every note edit without checking whether anything moved.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

payload=$(cat)
path=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')
session=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"')
case "$path" in */.agents/*.md) ;; *) exit 0 ;; esac
[ -f "$path" ] || exit 0
out=$("$HOME/.agents/bin/agent" remap "$path" 2>&1) || out="remap failed"
hook_log notes-map "$session" "$(printf '%s' "$out" | head -1)"
