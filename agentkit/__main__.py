"""`python -m agentkit`, which is what bin/agent execs.

Author: Marco Cassar (@Ocramaru)
"""

import os
import sys

from agentkit.cli import main

if __name__ == "__main__":
  try: sys.exit(main())
  except BrokenPipeError:   # the reader stopped reading, as `| head` does: not an error
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())   # so the flush at exit has somewhere to go
    sys.exit(0)
