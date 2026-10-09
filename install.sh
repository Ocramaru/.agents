#!/usr/bin/env bash
# The installer is `agent install` now; this stays so `./install.sh` still works.
exec "$(cd -P "$(dirname "$0")" && pwd)/bin/agent" install "$@"
