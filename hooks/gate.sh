# Sourced by a hook that wants to skip a call whose answer it already has this session.
#
# The stamp is the decision, and it names the one file that would change it; `-nt` compares them.
# Helpers set a variable rather than print, because `$(...)` is a fork and this runs on every edit.
# Nothing is cached across sessions: a stale cache is worse than a slow hook.
#
# gate_skip <hook> <path> <session>         0 = the answer is known and empty, so skip
# gate_mark <hook> <path> <session> [dep]   remember it, until `dep` is newer than now
# gate_ledger <path>                        sets GATE_LEDGER: the reviews db that could change it

_gate_stamp() {  # sets GATE_STAMP, a filename from the path without hashing it
  local flat="${2//\//_}"
  # inside the session's stamp directory, where inject and forget.sh put theirs: TMPDIR, as they
  # use it, so compaction clears these too. A Mac sets TMPDIR, and a fixed /tmp would outlive it.
  GATE_STAMP="${TMPDIR:-/tmp}/agents-${3:-nosession}/gate/$1.${flat#_}"
}

gate_skip() {
  # A note is never gated: the todo.md check is about the edit in hand, not about context.
  case "$2" in */.agents/*.md) return 1 ;; esac
  _gate_stamp "$1" "$2" "$3"
  [ -f "$GATE_STAMP" ] || return 1
  local dep=""
  read -r dep < "$GATE_STAMP" 2>/dev/null || true
  [ -n "$dep" ] && [ -e "$dep" ] && [ "$dep" -nt "$GATE_STAMP" ] && return 1
  return 0
}

gate_mark() {
  _gate_stamp "$1" "$2" "$3"
  mkdir -p "${GATE_STAMP%/*}" 2>/dev/null || return 0   # a gate that cannot write is just a slow hook
  printf '%s\n' "${4:-}" > "$GATE_STAMP" 2>/dev/null || true
}

gate_ledger() {  # walks up to the nearest .agents, so no fork to git
  local d="${1%/*}"
  GATE_LEDGER=""
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    [ -d "$d/.agents" ] && { GATE_LEDGER="$d/.agents/.reviews/reviews.duckdb"; return 0; }
    d="${d%/*}"
  done
}
