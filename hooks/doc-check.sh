#!/usr/bin/env bash
# Stop hook: run doc-check over the working diff when a session ends.
# Opt in with AGENTS_DOC_CHECK=1. Advisory only -- it reports and lets the session end.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"
# a review agentkit runs through `claude -p` is a session too, and its Stop must not start another review
[[ -z "${AGENTS_REVIEWER:-}" ]] || { hook_log doc-check reviewer "skip   inside a reviewer agentkit started"; exit 0; }

payload=$(cat)
session=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"') || true   # a payload jq cannot read is logged below, not a silent exit
[[ -n "$session" ]] || { hook_log doc-check nosession "ERROR  a payload jq cannot read"; exit 0; }

[[ "${AGENTS_DOC_CHECK:-0}" == "1" ]] || { hook_log doc-check "$session" "off    set AGENTS_DOC_CHECK=1 to enable"; exit 0; }
[[ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" == "true" ]] && exit 0  # continuing from a Stop hook, so this diff was checked when it first stopped

git rev-parse --git-dir >/dev/null 2>&1 || exit 0
git diff --quiet HEAD 2>/dev/null && exit 0

stderr_file=$(mktemp) && trap 'rm -f "$stderr_file"' EXIT
exit_code=0
out=$("$AGENTS_CLI" sub run doc-check --changed --json 2>"$stderr_file") || exit_code=$?
[[ "$exit_code" -eq 0 ]] || { hook_log doc-check "$session" "ERROR  rc=$exit_code $(tail -n 1 "$stderr_file" | cut -c1-200)"; exit 0; }
failure=$(printf '%s' "$out" | jq -r 'select(.state == "failed") | "state=failed \(.body // "")"' 2>/dev/null | head -c 200 | tr '\n' ' ') || true   # not JSON is reported below
[[ -z "$failure" ]] || { hook_log doc-check "$session" "ERROR  $failure"; exit 0; }
summary=$(printf '%s' "$out" | jq -r '
  if .state == "input-required" then "doc-check asked: \(.body)"
  elif (.findings // [] | length) > 0 then
    "doc-check:\n" + (.findings | map("  \(.file):\(.line)  \(.issue)") | join("\n"))
  else empty end' 2>/dev/null) || { hook_log doc-check "$session" "ERROR  not JSON from agent sub run: $(printf '%s' "$out" | head -c 120 | tr '\n' ' ')"; exit 0; }
[[ -n "$summary" ]] || { hook_log doc-check "$session" "clean  nothing to report"; exit 0; }

hook_log doc-check "$session" "reported $(( $(printf '%s\n' "$summary" | wc -l) )) lines"
jq -n --arg t "$summary" '{systemMessage: $t}'
