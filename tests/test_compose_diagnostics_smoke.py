from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_compose_diagnostics_smoke() -> None:
    script = Path("scripts/compose_diagnostics.py")
    assert script.exists()

    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--skip-docker", "--skip-health"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict)
    assert "services" in payload
    assert "health" in payload
    assert "ports" in payload
