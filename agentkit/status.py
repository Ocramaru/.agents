"""What this machine has, on one read-only screen: the install, the profile, the backend, what is in force here, and the hooks.
`doctor` judges and this describes, so a broken part is described where doctor would fail it, and the screen always draws.
"""

import json
from collections import Counter
from pathlib import Path

from agentkit import agents, backends, git, hooks, hub, inject, install, notes, profile as _profile, reviews, tree


def short(path: Path | str) -> str:
  """A path as this screen shows it, from `~` when it is under home."""
  return f"~/{install.home(Path(path))}" if Path(path).is_relative_to(Path.home()) else str(path)


def release() -> list[tuple[str, str, str]]:
  """The version, and whether this is a clone to work on or an install to upgrade."""
  return [("agentkit", f"{hub.version()}, an install at {short(hub.BUNDLED)} (its state in {short(hub.HOME)})" if hub.INSTALLED else f"{hub.version()}, a clone at {short(hub.BUNDLED)}", "")]


def profile() -> list[tuple[str, str, str]]:
  """The profile in force with where it pushes, and what another machine would miss."""
  where = _profile.path()
  if where is None: return [("profile", "none (the starters in .agents are in use)", "")]
  if not where.is_dir(): return [("profile", f"{short(where)}, which does not exist", "fail")]

  origin = git.run(where, "remote", "get-url", "origin").stdout.strip()
  problems = [(problem, "warn") for problem in _profile.drift(where)] or [("nothing unpushed", "") if (where / ".git").exists() else ("not a git repo", "warn")]
  return [("profile", f"{short(where)} ({origin})", "") if origin else ("profile", f"{short(where)} (no remote, so no other machine gets it)", "warn"), *(("profile", text, level) for text, level in problems)]


def backend() -> list[tuple[str, str, str]]:
  """The default backend, the roles each of its models runs, and the role each reviewer asks for."""
  known, default = backends.load_backends()
  found, roles, models = agents.definitions(), {}, {}
  for name, definition in sorted(found.items()): roles.setdefault(definition.get("model"), []).append(name)
  for role, model in (known[default].spec.get("models", {}) if default in known else {}).items(): models.setdefault(model, []).append(role)
  return [("backend", f"{default} (of {', '.join(sorted(known))})", "") if default in known else ("backend", f"{default}, which [backends] does not define", "fail") if default else ("backend", f"none set (of {', '.join(sorted(known))}): `agent install --backend <name>`, or a review at a terminal asks", "warn"),
          ("models", "  ·  ".join(f"{model} ({', '.join(names)})" for model, names in models.items()) or "none", ""),
          ("reviewers", f"{len(found)}, asking for {'  ·  '.join(f"{role} ({', '.join(names)})" for role, names in sorted(roles.items()))}" if found else "none", "")]


def counts() -> list[tuple[str, str, str]]:
  """The standards in force here by where each comes from, and the note directories from here up to the repo root."""
  here = Path.cwd()
  origins = Counter(layer.origin for layers in inject.library_for(here).layers.values() for layer in layers)
  directories = [tree.label(directory) for directory in tree.chain(here) if notes.note_files(directory)]
  return [("standards", ", ".join(f"{origins[origin]} {origin}" for origin in ("bundled", "profile", "repo")), ""),
          ("notes", f"{len(directories)} on the path from here ({', '.join(directories)})" if directories else "none on the path from here", "")]


def findings() -> list[tuple[str, str, str]]:
  """Open review findings in the repo holding the working directory; reading them takes duckdb, which may be missing."""
  root = git.root(Path.cwd())
  if root is None: return [("findings", "none (not in a git repo)", "")]
  if not reviews.path(root, create=False).is_file(): return [("findings", f"none (no reviews in {short(root)})", "")]   # before duckdb, which a repo never reviewed does not need

  found = reviews.open_findings(root)
  files = {finding["file"] for finding in found}
  return [("findings", f"{len(found)} open in {len(files)} file{'' if len(files) == 1 else 's'} of {short(root)} (`agent sub reviews --open` lists them)", "warn") if found else ("findings", f"none open in {short(root)}", "")]


def claude() -> list[tuple[str, str, str]]:
  """Whether Claude Code's settings.json holds the hooks block exactly as agentkit bundles it."""
  settings = install.config_dir("claude") / "settings.json"
  if not settings.is_file(): return [("claude hooks", f"not in place (there is no {short(settings)})", "fail")]
  try: live = json.loads(settings.read_text(encoding="utf-8"))
  except ValueError as error: return [("claude hooks", f"unknown ({short(settings)} is not valid JSON, {error})", "fail")]

  block = live.get("hooks") if isinstance(live, dict) else None
  if block == json.loads((hub.BUNDLED / "settings.hooks.json").read_text(encoding="utf-8")): return [("claude hooks", f"in place ({short(settings)})", "")]
  return [("claude hooks", f"not in place ({short(settings)})", "fail") if block is None else ("claude hooks", f"a block other than the one agentkit bundles ({short(settings)})", "warn")]


def githooks() -> list[tuple[str, str, str]]:
  """Where git looks for hooks in every repo, and whether that is this hub's."""
  current = install.global_hooks_path()
  if not current: return [("git hooks", "unset (each repo runs only its own .git/hooks)", "")]
  return [("git hooks", f"this hub's (core.hooksPath {short(current)})", "") if install.ours(current) else ("git hooks", f"not this hub's (core.hooksPath {short(current)})", "warn")]


def errors() -> list[tuple[str, str, str]]:
  """How many hooks failed since .agents last changed, and the latest failure."""
  found = hooks.errors()
  if not found: return [("hook errors", "none since .agents last changed", "")]
  return [("hook errors", f"{len(found)} since .agents last changed (the latest from {found[-1][1]} at {found[-1][0][:16].replace('T', ' ')})", "warn"), ("hook errors", found[-1][4][:120], "")]


PARTS = {"agentkit": release, "profile": profile, "backend": backend, "standards": counts, "findings": findings, "claude hooks": claude, "git hooks": githooks, "hook errors": errors}


def rows() -> list[tuple[str, str, str]]:
  """Every part as (part, what it is, level), install-time to run-time, the level `warn` for something to look at and `fail` for something broken; a part that cannot be read says why, and the rest still show."""
  out = []
  for part, describe in PARTS.items():
    try: out += describe()
    except Exception as error: out.append((part, f"cannot be read, {type(error).__name__}: {error}", "fail"))   # noqa: BLE001 -- status describes what is broken rather than failing on it
  return out
