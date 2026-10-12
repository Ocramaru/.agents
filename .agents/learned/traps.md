---
name: traps
description: What already cost a run here, newest first. Read before repeating an experiment
kind: learned
---

# Traps

- **Per-test coverage cannot choose which tests to cut.** `pytest --cov` does not trace the tests that run `agent(...)` as a subprocess, so they look like they reach nothing, and Python 3.14's default core cannot record `--cov-context`; set `COVERAGE_CORE=ctrace`. A test is worth keeping if a mutation of the source fails it: apply the edit, run the test, revert.

- **A test of a hook that sources `$HOME/.agents` runs the installed hub, not the checkout.** Mutating `hooks/gate.sh` in a worktree changed nothing until the test gave the hook a throwaway HOME whose `.agents` points at the checkout (`test_gate.Hook`). Check that a mutated copy of the code under test fails the test.

- **The argparse fold test passes vacuously on a newer Python.** Only system 3.12.3 strands `nargs="*"` after a flag; 3.12.12, 3.13 and 3.14 do not, so the test bites only under `UV_PYTHON=/usr/bin/python3.12`.

- **A conflicted merge in `~/.agents` breaks every agent's hooks until it is resolved.** A cherry-pick left conflict markers in `cli/sub.py`, and the guard failed to import in two sessions at once; it failed open, so nothing was blocked. Merge and cherry-pick in a worktree, then fast-forward.

- **`uv run agent` in a worktree runs the installed hub, not the worktree.** The project declares no `agent` script, so uv falls through to `~/.local/bin/agent`, and a change looked like it did nothing. Try a worktree's CLI with `uv run python -m agentkit`.

- **A local model server is one process holding one model, and it fails like one.** Four concurrent calls during a 30B-to-8B swap took ollama down with `Connection refused`, it drops connections or returns 500 while it swaps, and it keeps a model's memory for its keep-alive after the last request (qwen3:8b held 17.5 GB for five minutes). Declare `parallel = 1`, retry a transport failure with a short backoff, and release the model when a review finishes.

- **Report each result as it lands, and say what is about to be slow.** Results printed in submission order waited for the slowest file, and four silent minutes read as a hang. Print the model, start time and timeout before a plan starts, and each result as it completes.

- **Text from a model or a file is not markup.** Rich deleted `[[context]]` and `[context.md]` from findings about exactly those brackets. Escape everything that is not the code's own styling.

- **A filter written for one route misses the others.** Discovery skipped `__pycache__`, while a commit's file list and a named file came in unfiltered; and notes and reviews kept separate skip lists that drifted apart. One skip list, applied on every route.

- **A model's output is not the shape the prompt asked for.** Besides findings as a bare list, one review returned four entries that were a line number and two empty strings, and line fields arrive as prose (`12-14`, `86, 90`), which `isdigit` read as no line and so closed every finding in the file. Drop entries with a blank issue, and read a line as its first number.

- **The ledger's schema grows, so neither writers nor readers may assume it.** Positional insert values broke the day a column was added, and a read-only connection cannot migrate, so `--open` broke on a ledger written before `closures` existed. Name the columns in every insert; check a table or column exists before reading it.

- **Only a verdict replaces a conversation's open findings.** A question to the reviewer, or a recheck that failed, wrote the newest record and erased its findings with no closure. A record supersedes only when it is a findings verdict or carries findings.

- **An empty answer is not a delivered one.** The hook log called an empty inject payload "already in context" both when it had been sent and when nothing governed the file. Report "nothing applies" on its own path.

- **Test a chain three deep.** `extends` followed one level, and every two-deep test passed while a base of a base was never loaded.

- **Compare a task line against task lines, never against a file's text.** Matching a removed todo task against the whole archive counted it archived because another line mentioned it.

- **Accept a lone string wherever a list is expected in config.** `voice = "projects.json"` under `[applies]` matched nothing until a bare string was read as one glob.

- **A check that reads hand-edited config reports a parse error as a failure, not a crash.** A trailing comma in `settings.json` crashed `agent doctor`. Backups of such files go to the first free name: a fixed `.bak` overwrote the previous install's.

- **A regex cannot see shell quoting.** The formatter guard's second regex matched a formatter after `&&` inside a quoted string. Parse with `shlex` and match only at a command position.

- **Every commit a subagent makes in its worktree starts a full background review.** The global post-commit hook fires there too, so three agents' commits started three reviews of work about to be squashed, each writing a ledger into a worktree that was then removed. Squash first and let the landed commit be the one reviewed, or expect the folders to reappear until those reviews finish.

- **A subagent given its own worktree starts from `origin/main`, not local `main`.** With eleven commits unpushed, five agents began on code from before the CLI split. Push first, or have each agent `git reset --hard main` before it starts.

- **A uuid7 orders by the millisecond, not within one.** Its tail is random, so "closed after the last verdict" compared by id failed one test run in three. Compare the `at` column when order inside a burst matters.

- **`claude -p` waits three seconds for input on any stdin left open.** A hook or background review inherits an open pipe nobody writes to: an empty call took 7.2 s against 4.1 s with stdin closed. The backend passes `stdin=DEVNULL`.

- **`~/.agents` is live for every agent on the machine, so it is not where to work on the hub.** A half-done refactor there broke `agent sub reviews --open` for another session, which filed an issue about a `NameError` that existed only in the working tree. Change the hub in a worktree (`bin/agent` runs its own checkout) and move `~/.agents` forward by fast-forward only.

- **A reviewer with no tools knows only what the prompt carries, and fills the gaps by guessing or stalling.** A recheck sent as the words "fixed, recheck" was judged against the old file; a reviewer not told it saw one file called a widely used name unused, then stalled promising to "check call sites"; one buried under 14 KB of standards for a 1.7 KB file asked six times in eleven what it was reviewing. Say it sees one file, send only the standards that govern that file, and carry the current file with every follow-up.

- **Tightening a lenient default exposes what quietly relied on it.** Making unreadable replies `failed` turned every empty file into a failure, because a model's prose about an empty file had been counting as a clean pass. The real fault was sending an empty file at all. Look for what depends on a default before changing it.

- **A path hard-coded to `/tmp` is not where per-session state lives on macOS.** `tempfile` and `forget.sh` honour `TMPDIR`, a per-user directory there, so stamps under `/tmp` would have survived compaction and claimed context that was gone. Per-session state goes under `${TMPDIR:-/tmp}/agents-<session>`.

- **`python -m` runs the package in the working directory ahead of `PYTHONPATH`.** `agent` run from inside another checkout ran that checkout's code, and every test happened to run from the right directory. `-P` turns it off.

- **A model role must name a kind, and every role an agent asks for must exist on every backend.** `large` meant a coder model on ollama, so prose would have been judged by it; `small` existed nowhere on ollama, so an agent naming no model could not run there. Roles are `text` or `code`, optionally `-large`, `model_for` narrows to what a backend has, and a test checks every installed agent's role resolves.

- **A review `exclude` of `*.py` excludes the whole tree.** `fnmatch`'s `*` crosses `/`, so `*.py` reaches `sub/deep/mod.py`. Anchor an exclude to a full path or a directory that appears once.

- **A test that reads the machine's own config passes or fails with the machine.** One CLI test broke the day the global git hook was installed, and two inject tests broke when `map_over` was raised, with no code changed. `conftest.agent()` pins `GIT_CONFIG_GLOBAL` to `os.devnull`, and a test that needs config builds a hub of its own.

- **`rglob` walks everything and filters afterwards.** Finding note directories took 24 s over a workspace, mostly inside `.venv` and `node_modules`; `os.walk` pruning before descending took 1.3 s, and stops following symlinks into dataset trees.

- **A reviewer is confidently wrong often enough that dismissals need reasons.** On the hub's own change, 3 of 22 findings were wrong, including YAML escaping for frontmatter that is not YAML. Close those `--as wrong` with the reason; the next review reads it and does not raise them again.

- **A test that passes on the old code proves nothing, and reading it does not tell you.** Two of seven new tests passed against the pre-fix code; a later one set the very field it claimed the code under test set, under a comment saying what it meant to prove. Mutate the source and watch which tests fail.

- **Stamps outlive a test run.** They live in `/tmp/agents-<session>` and pytest reuses tmp directory names, so a fixed session id found the last run's stamps. Use a random session.

- **Changing how a note is stored can change who reads it.** Splitting a context.md injected only the index, so the obvious remedy for an oversized note silently removed its rules from every session. Parts are injected by their `applies` now; check delivery after any storage change.

- **An agent explains the system from what it was told.** A session watched the edit notice appear and then told the person the hook was "silent by design" and to try `claude --debug`, because AGENTS.md never mentioned the notice or once-per-session delivery. When a feature ships, the file agents read about it ships with it.

- **"Which standards govern this file" had two answers, and fixing one left the other.** `inject` resolved through `library_for`, honouring a repo's `[applies]`, while review built a bare `Library()`, so a training script was written under `ml.runs` and reviewed without it; review routing then repeated the split for prose named in `[applies]`. Everything that asks goes through `library_for`. Grep for every place that matches a filename against a standard, not only the one that broke.

- **A tool tested against its own assumptions passes until it meets the real thing.** The hub had never run on macOS (`setsid`, `readlink -f`, `stat -c` all missing); `remap` was only run from a repo root; `split` was only run on notes written for the test, then cut a real heading mid-word and lost the newest-first order. A CLI matrix over five working directories found two failures on its first run. Run a tool where it will run, on real data, under a stripped `PATH` and a throwaway `HOME`.

- **`git add <files> && git commit` commits the whole index, not the files you added.** In a tree with 24 files already staged, a commit about gitignore swept all of them in. Name the paths on the commit itself, `git commit -m "..." -- <paths>`, and check `git diff --cached --stat` first.

- **A `claude -p` reviewer is a whole Claude Code session unless told otherwise.** It loaded every MCP server and could open files or delegate; `tools: none` in the definition was a comment. `--tools "" --strict-mcp-config` enforces it. Those flags cut startup from 4.4 s to 2.6 s, but the time was the model: Opus passed the 300 s timeout on a 400-line file.

- **Where the caller knows the answer, assign it; do not offer it as a default.** `setdefault("file", rel)` kept whatever path a model echoed, so half a commit's findings were stored absolute and never matched the next edit.

- **An agent editing through Bash gets no standards, and nothing says so.** The hook fires on Edit and Write only; a whole session of `sed` and heredocs left no stamps at all, and a hook that never fired looks the same as one with nothing to say. `agent hooks` makes the absence visible.

- **When a backend misbehaves, call it bare before theorising about the harness.** Five ollama failures were blamed in turn on prompt size, model swapping and concurrency; all five were a non-coder model, and one `curl` to the endpoint settled it. Concurrency is still the backend's to declare: `parallel = 1` for a local server holding one model.

- **DuckDB gives the write lock to one process, and the post-commit hook makes concurrent reviews normal.** The second of two commits a minute apart died with `Conflicting lock is held`. Take the lock per insert, retry briefly, and let go.

- **An explicit file skips the glob filter; a commit's file list must not.** The bypass for "a named file is an explicit ask" spread to commits, and the hook handed `logo2.png` to a code model. `plan(explicit=...)` keeps them apart.

- **`at` is a reserved word in DuckDB.** The parser error points at the column, not the keyword. Quote it.

- **A writer thread that dies on connect loses the whole queue in silence.** A missing duckdb killed the thread, `join` returned cleanly, and four reviews were reported written with nothing stored. Connect inside the guard and drain to the sentinel.

- **A backend that never answered was spending turns.** Three transient disconnects burned six of an eight-turn cap and replayed the error text to the model. A transport failure is rolled back: nothing answered, so nothing happened.

- **A reply runs on a different reviewer unless the conversation carries its model.** `Session.answer` defaulted to the small model, so replying to a large review continued on an 8B that had never read the file. The model belongs in the stored conversation, not a default.

- **When an agent's output disappears, print what the backend returned before blaming the model.** A review reported 0 findings across 14 files because the model returned `data` as a bare list and the harness read only a mapping; two planted defects were found and thrown away three times.

- **The hub is a repo named after the thing it implements, and that has caused three bugs.** Any markdown counted as a note, so the hub's README made the whole repo one note directory and `remap` wrote a map into every standard; the walk skipped the hub's own `.agents`, so a session here ran without its context; an empty `.agents` from another tool captured the chain. `notes.note_files` is the single test: a file whose stem the convention defines, or a part in a split note.

- **argparse strands a `nargs="*"` positional once a flag interrupts it.** `review file-review --backend ollama train.py` failed with `unrecognized arguments`, and `parse_intermixed_args` refuses subparsers. `main` folds stray non-flag tokens back into the command's file list; any new command taking files inherits the trap.

- **A dotted standard name is a path in TOML.** `ml.runs = [...]` under `[applies]` parses as `{ml: {runs: [...]}}`. Both spellings are accepted, and `agent doctor` reports a name that does not exist.

- **Machine-wide filename guesses miss real layouts.** `ml.runs` globbed `train_*.py` and never loaded on a project's `train.py`, the file it was written for. A repo names its own entry points in `[applies]`.

- **Three designs for a section map all failed the same way.** Inside the note it referenced itself, beside it in `map.json` it drifted, rendered into it it did both; every fix existed to compensate for one note being monolithic. Splitting the note into files deleted all of it: the filename is the map.

- **A standard nobody wrote down gets violated.** Four files arrived with 4-space indents and no `Author:` line while `python.md` was injected on every edit, because neither rule was in it. When a review finds a style miss, fix the standard before the code.
