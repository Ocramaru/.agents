"""Where the hub's own files are, where this machine keeps its state, and which version of the hub this is.
A clone is both, in one folder; an install bundles the files inside the package and keeps its state in ~/.agents.
"""

import importlib.metadata
import json
import tomllib
from pathlib import Path

from agentkit import git

PACKAGE = Path(__file__).resolve().parent
INSTALLED = (PACKAGE / "bundled").is_dir()   # a wheel carries the hub's files inside the package; a checkout has them beside it
BUNDLED = PACKAGE / "bundled" if INSTALLED else PACKAGE.parent   # standards, reviewers, templates and hooks as released, replaced by an upgrade
HOME = Path.home() / ".agents" if INSTALLED else PACKAGE.parent   # this machine's state and the hooks at their fixed paths; a clone is its own
CONFIG = BUNDLED / "config.toml"   # the hub's own settings, and so every key's default
STANDARDS = BUNDLED / "standards"   # the starter standards, one file each; a profile's of the same name replace them
REVIEWERS = BUNDLED / "agents"   # the reviewer definitions, one file each, in a folder the hub calls `agents`
TEMPLATES = BUNDLED / "templates"   # what `agent init` and `agent profile init` write, one folder each
LOCAL = HOME / "local.toml"   # this machine's settings and where its profile is, never committed


def source() -> dict:
  """Where uv installed agentkit from, as its direct_url.json records it: a `url`, with `vcs_info` for a git source; empty from an index."""
  try: return json.loads(importlib.metadata.distribution("agentkit").read_text("direct_url.json") or "{}")
  except (importlib.metadata.PackageNotFoundError, ValueError): return {}


def version() -> str:
  """The version and commit agentkit is at, as `0.1.0 (7f68331)`: an install's from its metadata and the commit uv recorded, a clone's from pyproject.toml and git."""
  if INSTALLED: number, commit = importlib.metadata.version("agentkit"), source().get("vcs_info", {}).get("commit_id", "")[:7]   # never git: the venv may sit inside someone's dotfiles repo
  else: number, commit = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] if (pyproject := BUNDLED / "pyproject.toml").is_file() else "unknown", git.run(BUNDLED, "rev-parse", "--short", "HEAD").stdout.strip()
  return f"{number} ({commit})" if commit else number
