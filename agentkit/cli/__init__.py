"""The `agent` command. Each module registers its commands with `command` as it is imported.

Author: Marco Cassar (@Ocramaru)
"""

from agentkit.command import run as main
from agentkit.cli import notes, setup, sub  # noqa: F401  imported to register their commands

__all__ = ["main"]
