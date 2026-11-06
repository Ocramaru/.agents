# shellcheck shell=bash
# Sourced by a hook that wants to skip a call whose answer it already has this session.
#
# The stamp is the decision, and it names the paths that would change it, one per line; `-nt` compares them.
# A path missing when the stamp is made counts once it appears, so a `.agents` made mid-session reopens it.
# Helpers set a variable rather than print, because `$(...)` is a fork and this runs on every edit.
# Nothing is cached across sessions: a stale cache is worse than a slow hook.
#
# gate_skip <hook> <path> <session>              0 = the answer is known and empty, so skip
# gate_mark <hook> <path> <session> [paths]      remember it, until one of `paths` is newer than now

_gate_stamp() {  # sets GATE_STAMP, a filename from the path without hashing it
  local flat="${2//_/_u}"   # _ becomes _u and / becomes _s, so two paths never share a stamp
  flat="${flat//\//_s}"
  # inside the session's stamp directory, where inject and forget.sh put theirs: TMPDIR, as they
  # use it, so compaction clears these too. A Mac sets TMPDIR, and a fixed /tmp would outlive it.
  GATE_STAMP="${TMPDIR:-/tmp}/agents-${3:-nosession}/gate/$1.${flat#_s}"
}

gate_skip() {
  # A note is never gated: the todo.md check is about the edit in hand, not about context.
  case "$2" in .agents/*.md|*/.agents/*.md) return 1 ;; esac
  _gate_stamp "$1" "$2" "$3"
  [[ -f "$GATE_STAMP" ]] || return 1
  local dependency=""
  while read -r dependency; do
    # the same age reopens too: macOS's bash 3.2 compares whole seconds, so a change in the stamp's own second is not older
    [[ -n "$dependency" && -e "$dependency" && ! "$GATE_STAMP" -nt "$dependency" ]] && return 1
  done < "$GATE_STAMP" 2>/dev/null
  return 0
}

gate_mark() {
  _gate_stamp "$1" "$2" "$3"
  mkdir -p "${GATE_STAMP%/*}" 2>/dev/null || return 0   # a gate that cannot write is just a slow hook
  printf '%s\n' "${4:-}" > "$GATE_STAMP" 2>/dev/null || true
}
