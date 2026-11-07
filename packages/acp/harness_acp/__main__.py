"""python -m harness_acp: the same as harness acp."""

import sys

from .cli import main

sys.exit(main(sys.argv[1:]))
