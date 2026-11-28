from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.v1.documents import batch_upload
from app.services.parsing import mineru


@pytest.mark.parametrize("upstream_status", [401, 403])
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/batch-upload/apply-urls", {"files": [{"name": "qa.pdf", "data_id": "qa"}]}),
        ("GET", "/batch-upload/status/qa", None),
    ],
)
def test_rejected_mineru_credentials_make_batch_endpoints_unavailable(
    monkeypatch: pytest.MonkeyPatch, upstream_status: int, method: str, path: str, payload: dict | None
) -> None:
    monkeypatch.setattr(mineru.settings, "MINERU_ENABLED", True)
    monkeypatch.setattr(mineru.settings, "MINERU_API_TOKEN", "synthetic-qa-token")
    upstream_request = httpx.Request("GET", "https://mineru.net/api/v4")
    upstream_response = httpx.Response(upstream_status, request=upstream_request)
    request_with_retry = AsyncMock(
        side_effect=httpx.HTTPStatusError("Provider rejected credentials", request=upstream_request, response=upstream_response)
    )
    monkeypatch.setattr(mineru, "get_http_client_pool", lambda: SimpleNamespace(request_with_retry=request_with_retry))
    monkeypatch.setattr(batch_upload, "mineru_service", mineru.MinerUService())
    monkeypatch.setattr(batch_upload, "_require_batch_member", lambda **_: "owner")

    app = FastAPI()
    app.include_router(batch_upload.router)
    app.dependency_overrides[get_tenant_id] = lambda: UUID(int=1)
    app.dependency_overrides[get_current_account_id] = lambda: "qa-owner"
    with TestClient(app) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 503
    assert "invalid MINERU_API_TOKEN" in response.json()["detail"]
    request_with_retry.assert_awaited_once()


def test_mineru_batch_is_processing_while_a_file_is_converting() -> None:
    status = mineru.MinerUService._normalize_batch_status(
        {"extract_result": [{"state": "done"}, {"state": "converting"}]}
    )

    assert status["status"] == "processing"
    assert status["completed_files"] == 1
    assert status["progress"] == 50
