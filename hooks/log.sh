# Sourced by every hook: one log line per firing, so "did it fire" is answerable afterwards, and which `agent` to call.
#
# A hook is silent by design: it either injects context the model never shows you, or it has
# nothing to say. Those two look identical from the UI, and so does a hook that crashed. The log
# is the only place the difference is recorded.
#
# It never fails the hook it is logging. A log that cannot be written is not a reason to block an
# edit, so every line here swallows its own errors.
# Author: Marco Cassar (@Ocramaru)

AGENTS_HOOK_LOG="${AGENTS_HOOK_LOG:-$HOME/.agents/.hooks.log}"

# The CLI every hook calls: a clone's own bin/agent, or the console script an install put on PATH,
# which starts without the `uv run` a clone pays. A builtin test, so no fork on every edit.
AGENTS_CLI="$HOME/.agents/bin/agent"
[[ -x "$AGENTS_CLI" ]] || AGENTS_CLI=agent

hook_log() {  # hook_log <hook> <session> <what happened...>
  local hook="${1:-unknown}" session="${2:-nosession}"
  # a call with no text is a bug in the hook, so it is logged as an error rather than as the hook's name
  if (( $# >= 3 )); then shift 2; else set -- "ERROR  hook_log needs <hook> <session> <what>, and got $# arguments"; fi
  local tab=$'\t' newline=$'\n' text
  text="${*//$tab/ }"   # one row per line, tab-separated, so neither goes into the text
  {
    local size lock="$AGENTS_HOOK_LOG.lock"
    size=$(wc -c < "$AGENTS_HOOK_LOG" 2>/dev/null || echo 0)   # stat -c is GNU; wc is everywhere
    if [[ "$size" -gt 1000000 ]]; then
      # mkdir is the lock, since macOS has no flock; a lock older than a minute was left by a killed hook.
      # A line appended while the copy is made is lost, which once a megabyte is cheaper than locking every line.
      [[ -n "$(find "$lock" -maxdepth 0 -mmin +1 2>/dev/null)" ]] && rm -rf "$lock"
      if mkdir "$lock"; then
        tail -n 500 "$AGENTS_HOOK_LOG" > "$lock/log" && mv "$lock/log" "$AGENTS_HOOK_LOG"
        rm -rf "$lock"
      fi
    fi
    printf '%s\t%-10s\t%-8s\t%s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$hook" "${session:0:8}" "${text//$newline/ }" >> "$AGENTS_HOOK_LOG"
  } 2>/dev/null || true
}
