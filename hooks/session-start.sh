#!/usr/bin/env bash
# SessionStart: the .agents notes for the directory a session starts in, so one that only reads, explores or answers
# is grounded in them too, not only one that edits. The logic is agentkit's; this moves bytes. What it sends is
# stamped as inject.sh stamps it, so the first edit does not send the same notes again, and forget.sh clears both.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"
# a review agentkit runs through `claude -p` is a session too, and its prompt already carries what it may see
[[ -z "${AGENTS_REVIEWER:-}" ]] || { hook_log start reviewer "skip   inside a reviewer agentkit started"; exit 0; }

payload=$(cat)
{ read -r session; read -r cwd; } < <(printf '%s' "$payload" | jq -r '(.session_id // ""), (.cwd // "")') || true   # a payload jq cannot read is logged below, not a silent exit
# the id names the stamp directory; with none, inject sends everything and stamps nothing, rather than share one with every other session without an id
[[ -z "$session" || "$session" =~ ^[A-Za-z0-9_-]+$ ]] || { hook_log start nosession "ERROR  refused a session id that is not a plain name"; exit 0; }
[[ -n "$cwd" && -d "$cwd" ]] || { hook_log start "$session" "skip   no directory in the payload"; exit 0; }

stderr_file=$(mktemp) && trap 'rm -f "$stderr_file"' EXIT
exit_code=0
text=$("$AGENTS_CLI" inject "$cwd" --session "$session" --start 2>"$stderr_file") || exit_code=$?

# exit codes as agentkit/cli/notes.py names them: SENT 0 text, ALREADY_SENT 1 (a resume), NOTHING_GOVERNS 3 no notes on the path here
if [[ "$exit_code" -ne 0 && ( -s "$stderr_file" || ( "$exit_code" -ne 1 && "$exit_code" -ne 3 ) ) ]]; then
  hook_log start "$session" "ERROR  rc=$exit_code $(tail -n 1 "$stderr_file" | cut -c1-200)  $cwd"
  exit 0
fi
if [[ -z "$text" ]]; then
  if [[ "$exit_code" -eq 3 ]]; then hook_log start "$session" "none   no notes on the path here  $cwd"
  else hook_log start "$session" "quiet  already in context         $cwd"; fi
  exit 0
fi
hook_log start "$session" "sent   ${#text} bytes  $cwd"

# the one line the person sees, as inject.sh writes it; AGENTS_HOOK_QUIET=1 turns it off
message=""
if [[ "${AGENTS_HOOK_QUIET:-0}" != "1" ]]; then
  notes=$(printf '%s\n' "$text" | awk '/^--- .*\.md ---$/ { n++ } END { print n+0 }')
  parts="the names of its notes"   # every note already sent, or none loads, and only the list of what to read went
  [[ "$notes" -gt 0 ]] && parts="$(count "$notes" note)"
  place="${cwd##*/}"   # empty for / or a path ending in one, which is then named whole
  message=".agents loaded $parts for ${place:-$cwd} ($(measure "${#text}"))"
fi
jq -n --arg t "$text" --arg m "$message" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $t}} + (if $m == "" then {} else {systemMessage: $m} end)'
