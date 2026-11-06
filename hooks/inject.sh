#!/usr/bin/env bash
# Standards and .agents notes for the file being edited, or read where `[inject] read` puts Read in the matcher, resolved in one call.
# Everything with logic lives in agentkit; this moves bytes and counts the delimiters it writes for the one-line notice.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"
# a review agentkit runs through `claude -p` is a session too, and its prompt already carries what it may see
[[ -z "${AGENTS_REVIEWER:-}" ]] || { hook_log inject reviewer "skip   inside a reviewer agentkit started"; exit 0; }

. "$HOME/.agents/hooks/gate.sh"

payload=$(cat)
{ read -r session; read -r path; } < <(printf '%s' "$payload" |
  jq -r '(.session_id // ""), (.tool_input.file_path // .tool_input.notebook_path // "")') || true   # a payload jq cannot read is logged below, not a silent exit
# the id names the stamp directory; with none, inject sends everything and stamps nothing, rather than share one with every other session without an id
[[ -z "$session" || "$session" =~ ^[A-Za-z0-9_-]+$ ]] || { hook_log inject nosession "ERROR  refused a session id that is not a plain name"; exit 0; }
[[ -n "$path" ]] || { hook_log inject "$session" "skip   no file path in the payload"; exit 0; }

# Asked about this path already this session, and the answer was nothing. Four calls in five were
# one of those, each paying a `uv run` to say so.
if [[ -n "$session" ]] && gate_skip inject "$path" "$session"; then
  hook_log inject "$session" "gated  answered already, not asked again  $path"
  exit 0
fi

stderr_file=$(mktemp) && trap 'rm -f "$stderr_file"' EXIT
exit_code=0
# The payload goes back in on stdin so `inject` can see what the edit removes, not only what the
# file needs. One call either way: a second PreToolUse hook cost more than both of these together.
text=$(printf '%s' "$payload" |
  "$AGENTS_CLI" inject "$path" --session "$session" --edit --depends 2>"$stderr_file") || exit_code=$?

# `inject`'s exit codes are named once, in agentkit/cli/notes.py: SENT 0 with text, ALREADY_SENT 1 and NOTHING_GOVERNS 3. Any other
# exit, or one of those with something on stderr, is a failure; a warning beside a zero exit is not, so the text still goes.
if [[ "$exit_code" -ne 0 && ( -s "$stderr_file" || ( "$exit_code" -ne 1 && "$exit_code" -ne 3 ) ) ]]; then
  # the last line, not the first 200 bytes: two logged errors recorded only the runpy frames that
  # open every traceback, so the exception -- the one part worth keeping -- was cut off
  hook_log inject "$session" "ERROR  rc=$exit_code $(tail -n 1 "$stderr_file" | cut -c1-200)  $path"
  exit 0
fi
if [[ "$exit_code" -ne 0 ]]; then
  # NOTHING_GOVERNS or ALREADY_SENT. Either way the answer holds for the session, so remember it
  # rather than asking again on the next edit.
  if [[ -n "$session" ]]; then gate_mark inject "$path" "$session" "$text"; fi   # --depends printed the paths whose change reopens it
  if [[ "$exit_code" -eq 3 ]]; then hook_log inject "$session" "none   nothing governs this file  $path"
  else hook_log inject "$session" "quiet  already in context         $path"; fi
  exit 0
fi

hook_log inject "$session" "sent   ${#text} bytes  $path"

# What went in, as one line the user can see. `additionalContext` is delivered to the model and
# shown to nobody, so without this an edit that loaded five standards looks exactly like one that
# loaded nothing. Counted off the delimiters agentkit already writes; set AGENTS_HOOK_QUIET=1 to
# turn it off.
message=""
if [[ "${AGENTS_HOOK_QUIET:-0}" != "1" ]]; then
  # one pass over the text rather than four greps: this runs on every edit that was not gated
  read -r standards notes findings tasks < <(printf '%s\n' "$text" | awk '
    /^--- [a-z.-]+ \([^)]+\) ---$/ { standards++ }   /^--- .*\.md ---$/ { notes++ }
    /^Open review findings/ { findings++ }           /^This edit removes / { tasks += $4 }
    END { print standards+0, notes+0, findings+0, tasks+0 }')

  parts=""
  [[ "$standards" -gt 0 ]] && parts="$(count "$standards" standard)"
  [[ "$notes" -gt 0 ]] && parts="${parts:+$parts, }$(count "$notes" note)"
  [[ "$findings" -gt 0 ]] && parts="${parts:+$parts, }open findings"
  # worth its own words rather than counting as context: it is the one part that is about the edit
  [[ "$tasks" -gt 0 ]] && parts="${parts:+$parts, }$(count "$tasks" task) leaving todo.md unarchived"

  message=".agents loaded ${parts:-context} for ${path##*/} ($(measure "${#text}"))"
fi
jq -n --arg t "$text" --arg m "$message" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $t}} + (if $m == "" then {} else {systemMessage: $m} end)'
