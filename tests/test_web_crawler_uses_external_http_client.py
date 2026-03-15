from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_web_crawler_fetch_uses_external_http_client(monkeypatch):
    import app.services.web_crawler as wc

    calls = {"internal": 0, "external": 0}

    class _FakePool:
        async def get_client(self):  # noqa: ANN201
            await yield_control()
            calls["internal"] += 1
            return object()

        async def get_external_client(self):  # noqa: ANN201
            await yield_control()
            calls["external"] += 1
            return object()

    monkeypatch.setattr(wc, "get_http_client_pool", lambda: _FakePool())

    with pytest.raises(HTTPException) as excinfo:
        await wc._fetch_page_text(  # noqa: SLF001
            "",
            headers={},
            timeout_sec=1.0,
            max_bytes=1024,
            follow_redirects=False,
        )

    assert excinfo.value.status_code == 400
    assert calls["external"] == 1
    assert calls["internal"] == 0

