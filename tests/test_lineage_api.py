from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_lineage_chunk_endpoint_returns_service_payload(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.lineage as lineage_api

    chunk_id = uuid.uuid4()
    expected = {
        "schema": "mimirq.lineage.chunk.v1",
        "chunk_id": str(chunk_id),
        "document": {"document_id": "doc-1"},
        "connector": {"connector_id": "github_repo"},
        "acl": {"mode": "tenant"},
        "pipeline": {"pipeline_hash": "abc"},
        "retrieval_usage": {"schema": "mimirq.chunk_retrieval_lineage.v1"},
    }

    monkeypatch.setattr(
        lineage_api,
        "build_chunk_lineage_payload",
        lambda **_kwargs: expected,
        raising=True,
    )
    monkeypatch.setattr(
        lineage_api,
        "_load_chunk_lineage_dependencies",
        lambda *_a, **_k: {"chunk": object(), "document": object(), "permissions": [], "retrieval_usage": {"schema": "mimirq.chunk_retrieval_lineage.v1"}},
        raising=True,
    )

    def _override_get_db():  # noqa: ANN202
        yield object()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: uuid.UUID("00000000-0000-0000-0000-000000000001")
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.include_router(lineage_api.router, prefix="/api/v1/lineage")
    client = TestClient(app)

    res = client.get(f"/api/v1/lineage/chunk/{chunk_id}")
    assert res.status_code == 200
    assert res.json() == expected
