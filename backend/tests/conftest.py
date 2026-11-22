"""pytest fixtures: path setup so tests run with `python -I -m pytest`."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND / "app") not in sys.path:
    sys.path.insert(0, str(BACKEND / "app"))
