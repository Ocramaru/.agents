---
name: shell
description: How shell scripts are written, checked and laid out here
applies: *.sh, *.bash, *.zsh, zshrc, .zshrc, bashrc, .bashrc, .profile, .zprofile
related: commits
---

# Shell

A starter. Put your own `shell.md` in your profile and it replaces this one.

Bash for scripts, `#!/usr/bin/env bash`, with `set -euo pipefail` at the top. Check with `bash -n`, and `shellcheck` where it is installed. No whole-file formatter (`shfmt -w`) unless asked.

Quote every expansion (`"$path"`, `"${files[@]}"`), use `[[ ]]` for tests and `$( )` for substitution, and keep argument lists in arrays.

Anything that changes the machine takes `--dry-run`, changes nothing on a second run, and moves a file it did not make aside instead of overwriting it.

Portable to Linux and macOS: no `readlink -f`, `stat -c`, `date -Is`, `setsid`, or `sed -i` without a suffix. Detect with `uname`; never assume.

Once logic outgrows a screen of bash, move it to a real language and have the script call it.
