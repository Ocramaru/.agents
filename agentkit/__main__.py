"""`agent`, the console script an install puts on PATH, and `python -m agentkit`, which is what bin/agent execs."""

import os
import sys

from agentkit import cli


def main() -> None:
  """Run the command line and exit with its code."""
  try: sys.exit(cli.main())
  except BrokenPipeError:   # the reader stopped reading, as `| head` does: not an error
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())   # so the flush at exit has somewhere to go
    sys.exit(0)


if __name__ == "__main__": main()
