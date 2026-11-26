"""Source paths for public checks; no optional benchmark configuration."""
from pathlib import Path
import os
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
# Tests never ask PyPI for a newer release (harness/update.py).
os.environ.setdefault("HARNESS_UPDATE_CHECK", "0")
