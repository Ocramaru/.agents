"""What this machine has, on one read-only screen: the install, the profile, the backend, what is in force here, and the hooks.
`doctor` judges and this describes, so a broken part is described where doctor would fail it, and the screen always draws.

Author: Marco Cassar (@Ocramaru)
"""

import json
from collections import Counter
from pathlib import Path

from agentkit import agents, backends, git, hooks, hub, inject, install, notes, profile as _profile, reviews, tree, version


def release() -> list[tuple[str, str]]:
  """The version, and whether this is a clone to work on or an install to upgrade."""
  return [("agentkit", f"{version()}, an install at {hub.BUNDLED}, its state in {hub.HOME}" if hub.INSTALLED else f"{version()}, a clone at {hub.BUNDLED}")]


def profile() -> list[tuple[str, str]]:
  """The profile in force, where it pushes, and what another machine would miss."""
  where = _profile.path()
  if where is None: return [("profile", "none, so the starters in .agents are in use")]
  if not where.is_dir(): return [("profile", f"{where}, which does not exist")]

  origin = git.run(where, "remote", "get-url", "origin").stdout.strip()
  return [("profile", str(where)), ("profile", f"remote {origin}" if origin else "no remote, so no other machine gets it"),
          *(("profile", problem) for problem in _profile.drift(where) or ["nothing unpushed" if (where / ".git").exists() else "not a git repo"])]


def backend() -> list[tuple[str, str]]:
  """The default backend, the model it runs for each role, and the role each reviewer asks for."""
  known, default = backends.load_backends()
  found, roles = agents.definitions(), {}
  for name, definition in sorted(found.items()): roles.setdefault(definition.get("model"), []).append(name)
  return [("backend", f"{default}, the default of {', '.join(sorted(known))}" if default in known else f"{default}, which [backends] does not define" if default else f"none set, of {', '.join(sorted(known))}: `agent install --backend <name>`, or a review at a terminal asks"),
          ("models", ", ".join(f"{role} -> {model}" for role, model in (known[default].spec.get("models", {}) if default in known else {}).items()) or "none"),
          ("reviewers", f"{len(found)}, asking for {'; '.join(f"{role} ({', '.join(names)})" for role, names in sorted(roles.items()))}" if found else "none")]


def counts() -> list[tuple[str, str]]:
  """The standards in force here by where each comes from, and the note directories from here up to the repo root."""
  here = Path.cwd()
  origins = Counter("hub" if layer.origin == "machine-wide" else layer.origin for layers in inject.library_for(here).layers.values() for layer in layers)
  directories = [tree.label(directory) for directory in tree.chain(here) if notes.note_files(directory)]
  return [("standards", ", ".join(f"{origins[origin]} {origin}" for origin in ("hub", "profile", "repo"))),
          ("notes", f"{len(directories)} on the path from here: {', '.join(directories)}" if directories else "none on the path from here")]


def findings() -> list[tuple[str, str]]:
  """Open review findings in the repo holding the working directory; reading them takes duckdb, which may be missing."""
  root = tree.git_root(Path.cwd())
  if root is None: return [("findings", "none: not in a git repo")]
  if not reviews.path(root, create=False).is_file(): return [("findings", f"none: no review ledger in {root}")]   # before duckdb, which a repo never reviewed does not need

  found = reviews.open_findings(root)
  files = {finding["file"] for finding in found}
  return [("findings", f"{len(found)} open in {len(files)} file{'' if len(files) == 1 else 's'} of {root}; `agent sub reviews --open` lists them" if found else f"none open in {root}")]


def claude() -> list[tuple[str, str]]:
  """Whether Claude Code's settings.json holds the hooks block exactly as agentkit bundles it."""
  settings = install.config_dir("claude") / "settings.json"
  if not settings.is_file(): return [("claude hooks", f"not in place: there is no {settings}")]
  try: live = json.loads(settings.read_text(encoding="utf-8"))
  except ValueError as error: return [("claude hooks", f"unknown: {settings} is not valid JSON, {error}")]

  block = live.get("hooks") if isinstance(live, dict) else None
  return [("claude hooks", f"{'in place' if block == json.loads((hub.BUNDLED / 'settings.hooks.json').read_text(encoding='utf-8')) else 'not in place' if block is None else 'a block other than the one agentkit bundles'} in {settings}")]


def githooks() -> list[tuple[str, str]]:
  """Where git looks for hooks in every repo, and whether that is this hub's."""
  current = install.global_hooks_path()
  return [("git hooks", f"core.hooksPath {current}, {'' if install.ours(current) else 'not '}this hub's" if current else "core.hooksPath unset, so each repo runs only its own .git/hooks")]


def errors() -> list[tuple[str, str]]:
  """How many hooks failed since .agents last changed, and the latest failure."""
  found = hooks.errors()
  return [("hook errors", f"{len(found)} since .agents last changed, the latest from {found[-1][1]} at {found[-1][0]}: {found[-1][4][:120]}" if found else "none since .agents last changed")]


PARTS = {"agentkit": release, "profile": profile, "backend": backend, "standards": counts, "findings": findings, "claude hooks": claude, "git hooks": githooks, "hook errors": errors}


def rows() -> list[tuple[str, str]]:
  """Every part as (part, what it is), install-time to run-time; a part that cannot be read says why, and the rest still show."""
  out = []
  for part, describe in PARTS.items():
    try: out += describe()
    except Exception as error: out.append((part, f"cannot be read, {type(error).__name__}: {error}"))   # noqa: BLE001 -- status describes what is broken rather than failing on it
  return out
