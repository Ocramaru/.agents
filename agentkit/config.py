"""The layered config (the hub's `config.toml`, the profile's, this machine's `local.toml`, a repo's `.agents/agents.toml`) and writing one key of it."""

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path

from agentkit import hub, profile

HEADER = "# This machine's install. Not tracked: where your profile lives is local.\n"


def section(name: str, repo: Path | None = None, add: tuple[str, ...] = ()) -> dict:
  """One config section: the hub's config.toml, the profile's, this machine's local.toml, then `repo`'s .agents/agents.toml and its .local/agents.toml, each key replacing the last except those in `add`, which accumulate.
  `AGENTS_PROFILE=""` leaves out the profile and local.toml, so a test reads only the config it is given."""
  settings: dict = {}
  for layer in (hub.CONFIG, profile.file("config.toml"), None if os.environ.get("AGENTS_PROFILE") == "" else hub.LOCAL, *((Path(repo) / hub.AGENTS_DIR / "agents.toml", Path(repo) / hub.AGENTS_DIR / hub.LOCAL_DIR / "agents.toml") if repo else ())):
    if not layer or not layer.is_file(): continue
    for key, value in tomllib.loads(layer.read_text(encoding="utf-8")).get(name, {}).items(): settings[key] = settings.get(key, []) + ([value] if isinstance(value, str) else value) if key in add else value   # a lone string is a list of one
  return settings


def write(file: Path, table: str, key: str, value: str | None) -> None:
  """Set `key` in `[table]` of a TOML file to a string, or drop it for None, changing only that line so the rest stays as written; a new local.toml starts with its header.

  JSON's string escaping is TOML's, so any value is quoted validly.
  """
  line = "" if value is None else f"{key} = {json.dumps(value)}\n"
  text = file.read_text(encoding="utf-8") if file.is_file() else HEADER if file == hub.LOCAL else ""
  if text and not text.endswith("\n"): text += "\n"   # a header on the last line is still a header
  found = re.search(rf"(?ms)^\[{re.escape(table)}\][ \t]*(?:#[^\n]*)?\n(.*?)(?=^\[|\Z)", text)
  if found is None and value is None: return

  if found is None: text = f"{text.rstrip()}\n\n[{table}]\n{line}".lstrip("\n")
  else:
    body = found.group(1)
    if (start := re.search(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=", body)) is None: body = f"{line}{body}"
    else:
      lines = body[start.start():].splitlines(keepends=True)
      for end in range(1, len(lines) + 1):   # the value runs through the first line that closes it, a multi-line array's included
        try: tomllib.loads("".join(lines[:end])); break
        except tomllib.TOMLDecodeError: continue
      else: end = 1   # a value that never closes is left to doctor, and only its first line replaced
      body = body[:start.start()] + line + "".join(lines[end:])
    text = text[:found.start(1)] + body + text[found.end(1):]
  (target := file.resolve()).parent.mkdir(parents=True, exist_ok=True)   # through a link, so the link stays one
  handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")   # beside it, so the replace is a rename on one filesystem
  try:
    with os.fdopen(handle, "w", encoding="utf-8") as stream: stream.write(text)
    os.chmod(temporary, target.stat().st_mode & 0o777 if target.exists() else 0o644)
    os.replace(temporary, target)   # the old file or the new one, never half of either
  except BaseException:
    Path(temporary).unlink(missing_ok=True)
    raise
