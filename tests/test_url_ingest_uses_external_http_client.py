from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_download_url_to_path_uses_external_http_client(monkeypatch, tmp_path):
    import app.api.utils.url_ingest as ui

    calls = {"internal": 0, "external": 0}

    class _FakePool:
        async def get_client(self):  # noqa: ANN201
            await asyncio.sleep(0)  # Sonar S7503
            calls["internal"] += 1
            return object()

        async def get_external_client(self):  # noqa: ANN201
            await asyncio.sleep(0)  # Sonar S7503
            calls["external"] += 1
            return object()

    monkeypatch.setattr(ui, "get_http_client_pool", lambda: _FakePool())

    with pytest.raises(HTTPException) as excinfo:
        await ui.download_url_to_path("", Path(tmp_path) / "out.bin")

    assert excinfo.value.status_code == 400
    assert calls["external"] == 1
    assert calls["internal"] == 0

