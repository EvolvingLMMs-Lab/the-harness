"""python -m harness_mcp_server: the same as harness mcp."""

import sys

from .cli import main

sys.exit(main(sys.argv[1:]))
