#!/usr/bin/env bash
# Standards and .agents notes for the file being edited, resolved in one call.
# Everything with logic lives in agentkit; this only moves bytes.
set -euo pipefail
. "$HOME/.agents/hooks/log.sh"

. "$HOME/.agents/hooks/gate.sh"

payload=$(cat)
{ read -r session; read -r path; } < <(printf '%s' "$payload" |
  jq -r '(.session_id // "nosession"), (.tool_input.file_path // .tool_input.notebook_path // "")')
[ -n "$path" ] || { hook_log inject "$session" "skip   no file path in the payload"; exit 0; }

# Asked about this path already this session, and the answer was nothing. Four calls in five were
# one of those, each paying a `uv run` to say so.
if gate_skip inject "$path" "$session"; then
  hook_log inject "$session" "gated  answered already, not asked again  $path"
  exit 0
fi

err=$(mktemp) && trap 'rm -f "$err"' EXIT
rc=0
# The payload goes back in on stdin so `inject` can see what the edit removes, not only what the
# file needs. One call either way: a second PreToolUse hook cost more than both of these together.
text=$(printf '%s' "$payload" |
  "$HOME/.agents/bin/agent" inject "$path" --session "$session" --edit 2>"$err") || rc=$?

# A non-zero exit with nothing on stderr is `inject` saying this file is already in context. With
# something on stderr it is a real failure, which used to look exactly the same from here.
if [ -s "$err" ]; then
  # the last line, not the first 200 bytes: two logged errors recorded only the runpy frames that
  # open every traceback, so the exception -- the one part worth keeping -- was cut off
  hook_log inject "$session" "ERROR  rc=$rc $(tail -n 1 "$err" | cut -c1-200)  $path"
  exit 0
fi
if [ -z "$text" ]; then
  # agent exits 3 when nothing governs the file, 1 when it was already sent this session. Either way
  # the answer holds for the session, so remember it rather than asking again on the next edit.
  gate_ledger "$path"
  gate_mark inject "$path" "$session" "$GATE_LEDGER"
  if [ "$rc" -eq 3 ]; then hook_log inject "$session" "none   nothing governs this file  $path"
  else hook_log inject "$session" "quiet  already in context         $path"; fi
  exit 0
fi

hook_log inject "$session" "sent   ${#text} bytes  $path"

# What went in, as one line the user can see. `additionalContext` is delivered to the model and
# shown to nobody, so without this an edit that loaded five standards looks exactly like one that
# loaded nothing. Counted off the delimiters agentkit already writes; set AGENTS_HOOK_QUIET=1 to
# turn it off.
if [ "${AGENTS_HOOK_QUIET:-0}" = "1" ]; then
  jq -n --arg t "$text" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $t}}'
  exit 0
fi

# one pass over the text rather than four greps: this runs on every edit that was not gated
read -r rules notes open drops < <(printf '%s\n' "$text" | awk '
  /^--- [a-z.-]+ \([^)]+\) ---$/ { r++ }   /^--- .*\.md ---$/ { n++ }
  /^Open review findings/ { o++ }          /^This edit removes / { d++ }
  END { print r+0, n+0, o+0, d+0 }')

parts=""
[ "$rules" -gt 0 ] && parts="$rules standard$([ "$rules" = 1 ] || echo s)"
[ "$notes" -gt 0 ] && parts="${parts:+$parts, }$notes note$([ "$notes" = 1 ] || echo s)"
[ "$open" -gt 0 ] && parts="${parts:+$parts, }open findings"
# worth its own words rather than counting as context: it is the one part that is about the edit
[ "$drops" -gt 0 ] && parts="${parts:+$parts, }a task leaving todo.md unarchived"

# bytes under a kilobyte: "(0k)" read as nothing delivered, and one session went looking for the rest
if [ "${#text}" -lt 1024 ]; then size="${#text} B"; else size="$(( ${#text} / 1024 ))k"; fi
jq -n --arg t "$text" --arg m ".agents loaded ${parts:-context} for ${path##*/} ($size)" \
  '{systemMessage: $m, hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $t}}'
