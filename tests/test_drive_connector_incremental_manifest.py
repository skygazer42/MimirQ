from __future__ import annotations

import pytest

from tests.helpers.async_utils import yield_control
from tests.test_connector_saved_state_resume import _import_connectors_with_lightweight_stubs


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict | None = None) -> None:
        self.status_code = int(status_code)
        self._payload = dict(payload or {})

    def json(self):  # noqa: ANN201
        return dict(self._payload)


@pytest.mark.asyncio
async def test_drive_fetch_file_sync_token_prefers_version_modified_time_and_file_id() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    class _FakeClient:
        async def get(self, *_a, **_k):  # noqa: ANN202
            await yield_control()
            return _FakeResponse(
                status_code=200,
                payload={
                    "id": "file-123",
                    "version": "42",
                    "modifiedTime": "2026-03-10T00:00:00Z",
                },
            )

    token = await connectors._drive_fetch_file_sync_token(
        client=_FakeClient(),
        file_id="file-123",
        source_url="https://drive.google.com/file/d/file-123/view",
        headers={"Authorization": "Bearer token"},
    )

    assert token == "version:42|modified_time:2026-03-10T00:00:00Z|file_id:file-123"


@pytest.mark.asyncio
async def test_drive_fetch_file_sync_token_falls_back_to_hash_when_metadata_is_unavailable() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    class _FakeClient:
        async def get(self, *_a, **_k):  # noqa: ANN202
            await yield_control()
            return _FakeResponse(status_code=403, payload={"error": "forbidden"})

    source_url = "https://drive.google.com/file/d/file-404/view"
    fallback = connectors._drive_fallback_sync_token(file_id="file-404", source_url=source_url)
    token = await connectors._drive_fetch_file_sync_token(
        client=_FakeClient(),
        file_id="file-404",
        source_url=source_url,
        headers={"Authorization": "Bearer token"},
    )

    assert token == fallback
    assert token.startswith("hash:")
