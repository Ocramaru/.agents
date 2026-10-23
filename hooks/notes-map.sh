#!/usr/bin/env bash
# PostToolUse: refresh a note's section table after it is edited. Idempotent and cheap, so it can
# run on every note edit without checking whether anything moved.
# Author: Marco Cassar (@Ocramaru)
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

payload=$(cat)
path=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')
session=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"')
case "$path" in */.agents/*.md) ;; *) exit 0 ;; esac   # a cheap first cut: the hub itself is a .agents, so its README matches too
[[ -f "$path" ]] || exit 0
out=$("$AGENTS_CLI" remap --if-note "$path" 2>&1) || out="ERROR  remap failed: $(printf '%s' "$out" | tail -n 1 | cut -c1-200)"
hook_log notes-map "$session" "$(printf '%s' "$out" | head -1)"
