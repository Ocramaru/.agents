"""Resolving standards and talking to subagents over whatever backend this machine has.

Author: Marco Cassar (@Ocramaru)
"""

import tomllib

from agentkit import profile


def version() -> str:
  """This checkout's version and commit, as `0.1.0 (7f68331)`, read from pyproject.toml so a clone needs no install."""
  number = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] if (pyproject := profile.HUB / "pyproject.toml").is_file() else "unknown"
  return f"{number} ({commit})" if (commit := profile.git(profile.HUB, "rev-parse", "--short", "HEAD").stdout.strip()) else number
