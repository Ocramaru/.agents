"""Check the install on this machine, which tests cannot see.
Tests run against temporary trees, and an unregistered hook, a missing PATH entry or a renamed standard fails silently.

Author: Marco Cassar (@Ocramaru)
"""

import importlib.util
import json
import os
import re
import shutil
import tomllib
from pathlib import Path

from agentkit import agents, backends, config, git, guard, hooks, hub, inject, install, issue, mapblock, notes, profile, tree
from agentkit.frontmatter import load
from agentkit.standards import Library
MODES = ("full", "context", "none")   # what agents.toml `inject` may say


def checks() -> list[tuple[bool, str, str]]:
  """Every check as (ok, what was checked, what to do about it), roughly install-time to run-time."""
  out = []

  found = shutil.which("agent")
  out.append((bool(found and Path(found).resolve() == install.CLI.resolve()), f"`agent` on PATH -> {found or 'not found'}", "`uv tool update-shell` puts uv's bin on PATH; the hooks call the first `agent` there" if hub.INSTALLED else "run `agent install`, and put ~/.local/bin on PATH"))
  if hub.INSTALLED: out.append((not (stale := install.stale()), f"hooks, githooks, commands and AGENTS.md in {hub.HOME} match this install", f"{len(stale)} missing or changed, {stale[0].relative_to(hub.BUNDLED)} among them; run `agent install`" if stale else ""))

  ours = hub.BUNDLED / "settings.hooks.json"
  settings = install.config_dir("claude") / "settings.json"
  try:   # a hand-edited settings.json may not parse, which is a finding, not a crash
    wanted = json.loads(ours.read_text(encoding="utf-8")) if ours.is_file() else None
    live = json.loads(settings.read_text(encoding="utf-8")).get("hooks") if settings.is_file() else None
    fix = "run `agent install` to rewrite it" if wanted else f"{ours} is missing from the hub"
  except json.JSONDecodeError as error: wanted, live, fix = None, None, f"not valid JSON: {error}"
  out.append((wanted is not None and live == wanted, f"hooks block in {settings.name} matches settings.hooks.json", fix))

  for hook in sorted((hub.HOME / "hooks").glob("*.sh")): out.append((os.access(hook, os.X_OK), f"{hook.name} is executable", f"chmod +x {hook}"))

  commands = sorted((hub.HOME / "commands").glob("*.md"))
  for target, subdirectory in install.COMMANDS.items():
    directory = install.config_dir(target) / subdirectory
    if not directory.parent.is_dir(): continue
    for command in commands: out.append(((link := directory / command.name).is_symlink() and link.resolve() == command.resolve(), f"{target}: /{command.stem} installed", "run `agent install`"))

  library = Library()
  for name, standard in sorted(library.docs.items()):
    for field in ("related", "extends"):
      for reference in standard.list(field): out.append((reference in library.layers, f"standard {name} {field} {reference}", f"{reference} does not exist; fix the {field} in {standard.path.name}"))
    out.append((bool(standard.get("description")), f"standard {name} has a description", "add one; it is what shows when the body is not loaded"))

  for definition_file in sorted((hub.BUNDLED / "agents").glob("*.md")):
    definition = load(definition_file)
    for reference in definition.list("standards"): out.append((reference in library.layers, f"agent {definition.name} judges against {reference}", f"{reference} does not exist; fix the standards list in {definition_file.name}"))

  here = Path.cwd()
  note_dirs = tree.find_note_dirs(here)   # walked once, since over a large tree it is the slow part

  # a hand-edited config that does not parse is reported, and every check below waits until it does
  broken, root = [], tree.git_root(here)
  for file in dict.fromkeys(path for path in [hub.CONFIG, profile.file("config.toml"), hub.LOCAL, *(directory / tree.LINKS for directory in [*note_dirs, *((root / ".agents", root / ".agents" / ".local") if root else ())])] if path and path.is_file()):
    try: tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error: broken.append((False, f"{file} parses as TOML", f"fix it: {error}"))
  if broken: return out + broken

  for agents_dir in note_dirs:
    links = tree.toml(agents_dir)
    for name in inject.flatten_applies(links.get("applies") or {}): out.append((name in library.layers, f"{agents_dir.parent.name}/agents.toml applies -> {name}", f"no standard named {name}; check the spelling in {agents_dir / 'agents.toml'}"))
    if (mode := links.get("inject")) is not None: out.append((mode in MODES, f"{agents_dir.parent.name}/agents.toml inject = {mode!r}", f"inject must be one of {', '.join(MODES)}"))   # any other value falls through to the default unreported

  known, default = backends.load_backends()
  out.append((default in known, f"default backend {default} is one of [backends]" if default else "a default backend is set, so reviews have somewhere to run", f"fix `default` under [backends] in config.toml; known: {', '.join(known)}" if default else "`agent install` at a terminal asks, or `agent install --backend <name>`"))

  roles = {definition.get("model") for definition in agents.definitions().values()}
  for name, backend in sorted(known.items()):
    missing = sorted(roles - set(backend.spec.get("models", {})))
    out.append((not missing, f"backend {name} has a model for every reviewer's role", f"add {', '.join(missing)} to [backends.{name}] models in config.toml"))
    if backend.kind != "cli": continue
    executable = (backend.spec.get("argv") or [""])[0]
    out.append((bool(executable and shutil.which(executable)), f"backend {name} -> {executable or '(no argv)'}", f"install {executable}, or drop it" if executable else f"give backend {name} an argv under [backends.{name}] in config.toml"))

  formatter = guard.precommit_formatter(config.section("guard", tree.git_root(here)), here)   # catches a formatter hook added to a repo later
  out.append((not (formatter and (here / ".git" / "hooks" / "pre-commit").is_file()), "no commit hook here runs a formatter", f"pre-commit is installed and its config runs {formatter}; drop the hook or the config entry"))

  editor_settings = here / ".vscode" / "settings.json"
  # the value, not the key, and not a line commented out: a regex, since the file is JSONC
  out.append((not (editor_settings.is_file() and bool(re.search(r'^(?!\s*//).*"(editor\.)?formatOnSave"\s*:\s*true', editor_settings.read_text(encoding="utf-8", errors="replace"), re.MULTILINE))), "no editor format-on-save configured here", f"formatOnSave is set in {editor_settings}; a hook cannot see an editor, so it has to go"))

  out.append((bool(shutil.which("jq")), "jq on PATH, which every hook parses its payload with", "install jq (on a Mac: brew install jq); without it no hook does anything"))
  out.append((bool(shutil.which("uv")), "uv on PATH, so the hub manages its own venv", "install uv; without it `agent sub review` cannot reach duckdb"))
  # `agent issue` drafts without gh; gh is how it finds an issue already filed, and how `--list` reads them
  out.append((bool(shutil.which("gh") and issue.gh("auth", "status").returncode == 0), "gh authenticated, so `agent issue` can find an issue already filed", "install gh and run `gh auth login`; without it `agent issue` cannot see what is already filed, and `agent issue --list` cannot read it"))

  errors = hooks.errors()   # a crashing hook only shows in the log
  out.append((not errors, "no hook errors since .agents last changed", f"{len(errors)} logged, the latest from {errors[-1][1]}: {errors[-1][4][:120]}; `agent hooks` lists them" if errors else ""))

  # a profile reaches other machines only once pushed, and nothing else checks that
  if (where := profile.path()) is not None:
    out.append((where.is_dir(), f"profile at {where}", "agent profile use <dir>, or fix the path in local.toml"))
    for problem in profile.drift(where) if where.is_dir() else []: out.append((False, f"profile: {problem}", "agent update" if "behind" in problem else f"commit and push in {where}, or your other machines miss it"))

    # a profile holds how you work and your models, so its repo is private; gh can say so only for GitHub
    origin = git.run(where, "remote", "get-url", "origin").stdout.strip() if where.is_dir() else ""
    if "github.com" in origin and (repository := issue.named(origin)) and (seen := issue.gh("repo", "view", repository, "--json", "isPrivate", "--jq", ".isPrivate")).returncode == 0:
      out.append((seen.stdout.strip() == "true", f"profile remote {repository} is private", f"it is public, and a profile holds how you work and your models: gh repo edit {repository} --visibility private --accept-visibility-change-consequences"))

  out.append((importlib.util.find_spec("duckdb") is not None, "duckdb present, reviews can be kept", "`uv sync` in ~/.agents; everything but `agent sub review` works without it"))

  for agents_dir in note_dirs:
    out += context_size(agents_dir, here)
    for note in notes.note_files(agents_dir): out.append((mapblock.apply(text := note.read_text(encoding="utf-8")) == text, f"map current in {note.relative_to(here)}", f"agent remap {agents_dir}"))
  return out


def context_size(agents_dir: Path, base: Path) -> list[tuple[bool, str, str]]:
  """What a directory's context sends to every edit beneath it, and what it keeps back; never a failure."""
  context = agents_dir / "context.md"
  if not context.is_file(): return []

  body = load(context).body
  sent = len(tree.brief(body, config.section("inject")["map_over"]).encode())
  offered = [part for part, globs in tree.parts(agents_dir, "context") if not globs]
  return [(True, f"{agents_dir.relative_to(base) if agents_dir.is_relative_to(base) else agents_dir}/context.md {f"sends {sent} bytes" if sent >= len(body.encode()) else f"sends its map, {sent} of {len(body.encode())} bytes"}{f", {len(offered)} part{'' if len(offered) == 1 else 's'} to read on demand" if offered else ""}", "")]
