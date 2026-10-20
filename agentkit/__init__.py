"""Resolving standards and talking to subagents over whatever backend this machine has.

Author: Marco Cassar (@Ocramaru)
"""

import importlib.metadata
import tomllib

from agentkit import git, hub


def version() -> str:
  """The version and commit agentkit is at, as `0.1.0 (7f68331)`: an install's from its metadata and the commit uv recorded, a clone's from pyproject.toml and git."""
  if hub.INSTALLED: number, commit = importlib.metadata.version("agentkit"), hub.source().get("vcs_info", {}).get("commit_id", "")[:7]   # never git: the venv may sit inside someone's dotfiles repo
  else: number, commit = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] if (pyproject := hub.BUNDLED / "pyproject.toml").is_file() else "unknown", git.run(hub.BUNDLED, "rev-parse", "--short", "HEAD").stdout.strip()
  return f"{number} ({commit})" if commit else number
