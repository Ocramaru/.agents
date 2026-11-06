"""Check the install on this machine, which tests cannot see.
Tests run against temporary trees, and an unregistered hook, a missing PATH entry or a renamed standard fails silently.
"""

import importlib.util
import json
import os
import re
import shutil
import tomllib
from pathlib import Path

from agentkit import agents, backends, config, gh, git, guard, hooks, hub, inject, install, mapblock, notes, profile, standards, tree, words
from agentkit.frontmatter import load
from agentkit.standards import Library


def checks() -> list[tuple[bool, str, str]]:
  """Every check as (ok, what was checked, what to do about it), roughly install-time to run-time."""
  out = []

  found = shutil.which("agent", path=install.shell_path())   # the `agent` a shell finds, not this venv's, which `uv run` puts first
  out.append((bool(found and Path(found).resolve() == install.CLI.resolve()), f"`agent` on PATH -> {found or 'not found'}", "`uv tool update-shell` puts uv's bin on PATH; the hooks call the `agent` that `agent install` recorded" if hub.INSTALLED else "run `agent install`, and put ~/.local/bin on PATH"))
  if hub.INSTALLED: out.append((not (stale := [*(source.relative_to(hub.BUNDLED) for source in install.stale()), *(copy.relative_to(hub.HOME) for copy in install.dropped())]), f"hooks, githooks, commands and AGENTS.md in {hub.HOME} match this install", f"{len(stale)} missing, changed or no longer bundled, {stale[0]} among them; run `agent install`" if stale else ""))

  settings = install.config_dir("claude") / "settings.json"
  try:   # a hand-edited settings.json may not parse, which is a finding, not a crash
    wanted = install.claude_block() if hub.HOOKS_BLOCK.is_file() else None
    loaded = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    live = loaded.get("hooks") if isinstance(loaded, dict) else None
    fix = f"{settings} is not a JSON object; fix it, then run `agent install`" if not isinstance(loaded, dict) else "run `agent install` to bring them up to date" if wanted else f"{hub.HOOKS_BLOCK} is missing from the hub"
  except json.JSONDecodeError as error: wanted, live, fix = None, None, f"not valid JSON: {error}"
  except tomllib.TOMLDecodeError as error: wanted, live, fix = None, None, f"a config.toml does not parse, so whether Read is in the matcher is unknown: {error}"   # [inject] read shapes the block
  except OSError as error: wanted, live, fix = None, None, f"cannot be read: {error}"   # unreadable, or a link that loops
  out.append((wanted is not None and install.partition(live)[0] == wanted, f"the hub's hooks in Claude Code's {settings.name} match settings.hooks.json, as [inject] read shapes it", fix))   # by the script each runs, so a hook of the user's beside them is no drift

  for hook in sorted([*(hub.HOME / "hooks").glob("*.sh"), hub.HOME / "githooks" / "_dispatch"]): out.append((os.access(hook, os.X_OK), f"{hook.name} is executable", f"chmod +x {hook}"))   # every githook links to _dispatch

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
  for name, layers in sorted(library.layers.items()):
    for layer in layers:   # a family's folder names its members, so latex/robotics.md is latex or latex.<field>
      if (family := layer.doc.path.parent.name) != "standards": out.append((name == family or name.startswith(f"{family}."), f"standard {name} is named for its folder {family}/", f"name it {family} or {family}.<field> in {layer.doc.path}"))
  for agents_md, directory in standards.tables().items(): out.append((standards.table(agents_md, directory) == agents_md.read_text(encoding="utf-8"), f"standards table current in {agents_md}", f"agent remap {agents_md}"))

  for definition_file in sorted(hub.REVIEWERS.glob("*.md")):
    definition = load(definition_file)
    for reference in definition.list("standards"): out.append((reference in library.layers, f"agent {definition.name} judges against {reference}", f"{reference} does not exist; fix the standards list in {definition_file.name}"))

  here, root = Path.cwd(), git.root(Path.cwd())
  note_dirs = list(dict.fromkeys([*tree.chain(here), *tree.find_note_dirs(here)])) if root else []   # walked once, since over a large tree it is the slow part
  if not root: out.append((True, "no repo here, so no notes were walked; run `agent doctor` inside a repo to check one", ""))   # the machine, the hub and the profile are still checked
  base = (root or here).parent   # a path is shown from the repo's own name down: my_repo/src/.agents/agents.toml
  shown = lambda path: path.relative_to(base) if path.is_relative_to(base) else path

  # a hand-edited config that does not parse is reported, and every check below waits until it does
  broken = []
  for file in dict.fromkeys(path for path in [hub.CONFIG, profile.file("config.toml"), hub.LOCAL, *(directory / tree.AGENTS_TOML for directory in note_dirs)] if path and path.is_file()):
    try: tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error: broken.append((False, f"{file} parses as TOML", f"fix it: {error}"))
    except OSError as error: broken.append((False, f"{file} can be read", f"cannot be read: {error}"))
  if broken: return out + broken

  for agents_dir in note_dirs:
    agents_toml, where = tree.agents_toml(agents_dir), shown(agents_dir / tree.AGENTS_TOML)
    for name in inject.flatten_applies(agents_toml.get("applies") or {}): out.append((name in library.layers, f"{where} applies -> {name}", f"no standard named {name}; check the spelling in {agents_dir / tree.AGENTS_TOML}"))
    if (mode := agents_toml.get("inject")) is not None: out.append((mode in tree.INJECT_MODES, f"{where} inject = {mode!r}", f"inject must be one of {', '.join(tree.INJECT_MODES)}"))   # any other value falls through to the default unreported

  known, default = backends.load_backends()
  out.append((default in known, f"default backend {default} is one of [backends]" if default else "a default backend is set, so headless reviews (post-commit, doc-check) can run", f"fix `default` under [backends] in config.toml; known: {', '.join(known)}" if default else f"`agent install --backend <{'|'.join(known)}>`"))

  roles = {definition.get("model") for definition in agents.definitions().values()}
  for name, backend in sorted(known.items()):
    missing = sorted(roles - set(backend.spec.get("models", {})))
    out.append((not missing, f"backend {name} has a model for every reviewer's role", f"add {', '.join(missing)} to [backends.{name}] models in config.toml"))
    if backend.kind != "cli": continue
    executable = (backend.spec.get("argv") or [""])[0]
    out.append((bool(executable and shutil.which(executable)), f"backend {name} -> {executable or '(no argv)'}", f"install {executable}, or drop it" if executable else f"give backend {name} an argv under [backends.{name}] in config.toml"))

  formatter = guard.precommit_formatter(config.section("guard", git.root(here)), here)   # catches a formatter hook added to a repo later
  out.append((not (formatter and (here / ".git" / "hooks" / "pre-commit").is_file()), "no commit hook here runs a formatter", f"pre-commit is installed and its config runs {formatter}; drop the hook or the config entry"))

  editor_settings = here / ".vscode" / "settings.json"
  # the value, not the key, and not a line commented out: a regex, since the file is JSONC
  out.append((not (editor_settings.is_file() and bool(re.search(r'^(?!\s*//).*"(editor\.)?formatOnSave"\s*:\s*true', editor_settings.read_text(encoding="utf-8", errors="replace"), re.MULTILINE))), "no editor format-on-save configured here", f"formatOnSave is set in {editor_settings}; a hook cannot see an editor, so it has to go"))

  out.append((bool(shutil.which("jq")), "jq on PATH, which every hook parses its payload with", "install jq (on a Mac: brew install jq); without it no hook does anything"))
  out.append((bool(shutil.which("uv")), "uv on PATH, so the hub manages its own venv", "install uv; without it `agent sub review` cannot reach duckdb"))
  # `agent issue` drafts without gh; gh is how it finds an issue already filed, and how `--list` reads them
  out.append((bool(shutil.which("gh") and gh.run("auth", "status").returncode == 0), "gh authenticated, so `agent issue` can find an issue already filed", "install gh and run `gh auth login`; without it `agent issue` cannot see what is already filed, and `agent issue --list` cannot read it"))

  errors = hooks.errors()   # a crashing hook only shows in the log
  out.append((not errors, "no hook errors since .agents last changed", f"{len(errors)} logged, the latest from {errors[-1][1]}: {errors[-1][4][:120]}; `agent hooks` lists them" if errors else ""))

  # a profile reaches other machines only once pushed, and nothing else checks that
  if (where := profile.path()) is not None:
    out.append((where.is_dir(), f"profile at {where}", "agent profile use <dir>, or fix the path in local.toml"))
    for problem in profile.drift(where) if where.is_dir() else []: out.append((False, f"profile: {problem}", "agent update" if "behind" in problem else f"commit and push in {where}, or your other machines miss it"))

    # a profile holds how you work and your models, so its repo is private; gh can say so only for GitHub
    origin = git.run(where, "remote", "get-url", "origin").stdout.strip() if where.is_dir() else ""
    if "github.com" in origin and (repository := gh.repository(origin)) and (seen := gh.run("repo", "view", repository, "--json", "isPrivate", "--jq", ".isPrivate")).returncode == 0:
      out.append((seen.stdout.strip() == "true", f"profile remote {repository} is private", f"it is public, and a profile holds how you work and your models: gh repo edit {repository} --visibility private --accept-visibility-change-consequences"))

  out.append((importlib.util.find_spec("duckdb") is not None, "duckdb present, reviews can be kept", "`uv sync` in ~/.agents; everything but `agent sub review` works without it"))

  for agents_dir in note_dirs:
    out += context_size(agents_dir, base)
    for note in notes.note_files(agents_dir):
      try: out.append((mapblock.apply(text := note.read_text(encoding="utf-8")) == text, f"map current in {shown(note)}", f"agent remap {agents_dir}"))
      except OSError as error: out.append((False, f"map current in {shown(note)}", f"cannot be read: {error}"))
  return out


def context_size(agents_dir: Path, base: Path) -> list[tuple[bool, str, str]]:
  """What a directory's context sends to every edit beneath it, and what it keeps back; never a failure."""
  context = agents_dir / "context.md"
  if not context.is_file(): return []

  body = load(context).body
  whole, sent = len(body.encode()), len(tree.brief(body, config.section("inject")["map_over"]).encode())
  offered = [part for part, globs in tree.parts(agents_dir, "context") if not globs]

  where = agents_dir.relative_to(base) if agents_dir.is_relative_to(base) else agents_dir
  sends = f"sends {sent} bytes" if sent >= whole else f"sends its map, {sent} of {whole} bytes"
  parts = f", {words.count(len(offered), 'part')} to read on demand" if offered else ""
  return [(True, f"{where}/context.md {sends}{parts}", "")]
