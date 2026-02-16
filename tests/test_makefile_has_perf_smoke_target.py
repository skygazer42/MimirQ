from __future__ import annotations

import re
from pathlib import Path


def test_makefile_has_perf_smoke_target() -> None:
    contents = Path("Makefile").read_text(encoding="utf-8")
    assert re.search(r"^perf-smoke:", contents, flags=re.MULTILINE)
