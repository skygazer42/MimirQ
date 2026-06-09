from __future__ import annotations

import os


def test_ensure_local_no_proxy_preserves_existing_entries(monkeypatch):
    from app.core.local_proxy import ensure_local_no_proxy

    monkeypatch.setenv("NO_PROXY", "ci-service.example")
    monkeypatch.delenv("no_proxy", raising=False)

    ensure_local_no_proxy()

    assert set((os.getenv("NO_PROXY") or "").split(",")) >= {
        "ci-service.example",
        "localhost",
        "127.0.0.1",
        "::1",
    }
    assert set((os.getenv("no_proxy") or "").split(",")) >= {
        "localhost",
        "127.0.0.1",
        "::1",
    }
