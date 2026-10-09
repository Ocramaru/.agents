# Sourced by every hook. One line per firing, so "did it fire" is answerable afterwards.
#
# A hook is silent by design: it either injects context the model never shows you, or it has
# nothing to say. Those two look identical from the UI, and so does a hook that crashed. The log
# is the only place the difference is recorded.
#
# It never fails the hook it is logging. A log that cannot be written is not a reason to block an
# edit, so every line here swallows its own errors.

AGENTS_HOOK_LOG="${AGENTS_HOOK_LOG:-$HOME/.agents/.hooks.log}"

hook_log() {  # hook_log <hook> <session> <what happened...>
  local hook="$1" session="${2:-nosession}"
  shift 2 2>/dev/null || true
  {
    local size
    size=$(wc -c < "$AGENTS_HOOK_LOG" 2>/dev/null || echo 0)   # stat -c is GNU; wc is everywhere
    [ "$size" -gt 1000000 ] && tail -n 500 "$AGENTS_HOOK_LOG" > "$AGENTS_HOOK_LOG.tmp" \
      && mv "$AGENTS_HOOK_LOG.tmp" "$AGENTS_HOOK_LOG"
    printf '%s\t%-10s\t%-8s\t%s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$hook" "${session:0:8}" "$*" >> "$AGENTS_HOOK_LOG"
  } 2>/dev/null || true
}
