#!/usr/bin/env bash
# Stop hook: run doc-check over the working diff when a session ends.
# Opt in with AGENTS_DOC_CHECK=1. Advisory only -- it reports and lets the session end.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

payload=$(cat)
session=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"')

[ "${AGENTS_DOC_CHECK:-0}" = "1" ] || { hook_log doc-check "$session" "off    set AGENTS_DOC_CHECK=1 to enable"; exit 0; }
[ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0  # no loops

git rev-parse --git-dir >/dev/null 2>&1 || exit 0
git diff --quiet HEAD 2>/dev/null && exit 0

out=$("$HOME/.agents/bin/agent" run doc-check --changed 2>/dev/null) || exit 0
summary=$(printf '%s' "$out" | jq -r '
  if .state == "input-required" then "doc-check asked: \(.body)"
  elif (.data.findings // [] | length) > 0 then
    "doc-check:\n" + (.data.findings | map("  \(.file):\(.line)  \(.issue)") | join("\n"))
  else empty end' 2>/dev/null) || exit 0
[ -n "$summary" ] || { hook_log doc-check "$session" "clean  nothing to report"; exit 0; }

hook_log doc-check "$session" "reported $(printf '%s' "$summary" | wc -l) lines"
jq -n --arg t "$summary" '{systemMessage: $t}'
