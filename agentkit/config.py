"""The layered config (the hub's `config.toml`, the profile's, this machine's `local.toml`, a repo's `.agents/agents.toml`) and writing one key of it."""

import json
import os
import re
import tomllib
from pathlib import Path

from agentkit import hub, profile

HEADER = "# This machine's install. Not tracked: where your profile lives is local.\n"


def section(name: str, repo: Path | None = None, add: tuple[str, ...] = ()) -> dict:
  """One config section: the hub's config.toml, the profile's, this machine's local.toml, then `repo`'s .agents/agents.toml and its .local/agents.toml, each key replacing the last except those in `add`, which accumulate.
  `AGENTS_PROFILE=""` leaves out the profile and local.toml, so a test reads only the config it is given."""
  settings: dict = {}
  for layer in (hub.CONFIG, profile.file("config.toml"), None if os.environ.get("AGENTS_PROFILE") == "" else hub.LOCAL, *((Path(repo) / ".agents" / "agents.toml", Path(repo) / ".agents" / ".local" / "agents.toml") if repo else ())):
    if not layer or not layer.is_file(): continue
    for key, value in tomllib.loads(layer.read_text(encoding="utf-8")).get(name, {}).items(): settings[key] = settings.get(key, []) + ([value] if isinstance(value, str) else value) if key in add else value   # a lone string is a list of one
  return settings


def write(file: Path, table: str, key: str, value: str) -> None:
  """Set `key` in `[table]` of a TOML file to a string, changing only that line so the rest stays as written; a new local.toml starts with its header.

  JSON's string escaping is TOML's, so any value is quoted validly.
  """
  line = f"{key} = {json.dumps(value)}"
  text = file.read_text(encoding="utf-8") if file.is_file() else HEADER if file == hub.LOCAL else ""
  if text and not text.endswith("\n"): text += "\n"   # a header on the last line is still a header
  found = re.search(rf"(?ms)^\[{re.escape(table)}\][ \t]*(?:#[^\n]*)?\n(.*?)(?=^\[|\Z)", text)

  if found is None: text = f"{text.rstrip()}\n\n[{table}]\n{line}\n".lstrip("\n")
  else:
    body = found.group(1)
    body = (re.sub(rf"(?m)^[ \t]*{re.escape(key)}\s*=.*$", lambda _: line, body, count=1) if re.search(rf"(?m)^[ \t]*{re.escape(key)}\s*=", body)
            else f"{line}\n{body}")
    text = text[:found.start(1)] + body + text[found.end(1):]
  file.parent.mkdir(parents=True, exist_ok=True)
  file.write_text(text, encoding="utf-8")
