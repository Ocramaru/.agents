"""Where the hub's own files are, and where this machine keeps its state.
A clone is both, in one folder; an install bundles the files inside the package and keeps its state in ~/.agents.

Author: Marco Cassar (@Ocramaru)
"""

import importlib.metadata
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
INSTALLED = (PACKAGE / "bundled").is_dir()   # a wheel carries the hub's files inside the package; a checkout has them beside it
BUNDLED = PACKAGE / "bundled" if INSTALLED else PACKAGE.parent   # standards, reviewers, templates and hooks as released, replaced by an upgrade
HOME = Path.home() / ".agents" if INSTALLED else PACKAGE.parent   # this machine's state and the hooks at their fixed paths; a clone is its own
CONFIG = BUNDLED / "config.toml"   # the hub's own settings, and so every key's default
TEMPLATES = BUNDLED / "templates"   # what `agent init` and `agent profile init` write, one folder each
LOCAL = HOME / "local.toml"   # this machine's settings and where its profile is, never committed


def source() -> dict:
  """Where uv installed agentkit from, as its direct_url.json records it: a `url`, with `vcs_info` for a git source; empty from an index."""
  try: return json.loads(importlib.metadata.distribution("agentkit").read_text("direct_url.json") or "{}")
  except (importlib.metadata.PackageNotFoundError, ValueError): return {}
