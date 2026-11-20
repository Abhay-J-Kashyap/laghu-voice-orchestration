import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_CANDIDATES = [os.environ.get("LAGHU_DIR", ""), str(ROOT / "vendor" / "laghu")]


@pytest.fixture(scope="session")
def laghu_dir() -> Path:
    """Laghu's code (enough for the text tests; the weights are needed only for test_laghu_real)."""
    for c in _CANDIDATES:
        if c and (Path(c) / "devanagari_text.py").exists():
            return Path(c)
    pytest.skip("Laghu not found: run scripts/get_laghu.py")
