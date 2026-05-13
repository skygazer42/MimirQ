from __future__ import annotations

from pathlib import Path


def test_settings_status_probe_uses_httpx_not_requests() -> None:
    source = Path("app/api/v1/settings.py").read_text(encoding="utf-8")

    assert "import requests" not in source
    assert "requests.get(" not in source
    assert "httpx.Client" in source
