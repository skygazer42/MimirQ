from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_learn_common_lines_endpoint_returns_candidates(monkeypatch):  # noqa: ANN001
    import app.api.v1.pipeline as pipeline_module

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    # Bypass permission enforcement for unit test (covered elsewhere).
    monkeypatch.setattr(pipeline_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id

    monkeypatch.setattr(pipeline_module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)
    monkeypatch.setattr(pipeline_module.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(
        pipeline_module,
        "_collect_common_lines_texts",
        lambda **_k: (
            2,
            [
                "ACME Confidential\n\nHello world\n",
                "ACME Confidential\n\nAnother document\n",
            ],
        ),
        raising=True,
    )

    class _DummyDB:
        pass

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(pipeline_module.router, prefix="/api/v1/pipeline")
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/learn-common-lines",
        json={
            "dataset_id": str(dataset_id),
            "limit_docs": 2,
            "min_docs": 2,
            "min_ratio": 1.0,
            "max_candidates": 10,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("dataset_id") == str(dataset_id)
    assert body.get("used_documents") == 2
    candidates = body.get("candidates") or []
    assert isinstance(candidates, list) and candidates
    assert any("acme confidential" in str(it.get("signature") or "") for it in candidates)
