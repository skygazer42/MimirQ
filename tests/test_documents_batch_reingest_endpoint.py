import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentBatchRetryResponse
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


def test_documents_batch_reingest_calls_patch_and_retry(monkeypatch):  # noqa: ANN001
    from types import SimpleNamespace

    from app.api.v1.document_batches import batch_reingest_documents
    from app.services import document_batch_operations, document_metadata_operations, document_processing_operations

    tenant_id = uuid.uuid4()
    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()

    # Avoid auth/DB logic in unit test.
    monkeypatch.setattr(
        document_batch_operations.dataset_service,
        "ensure_member",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    calls = {"patch": 0, "retry": 0}

    def _fake_patch(**kwargs):  # noqa: ANN001, ANN202
        calls["patch"] += 1
        return None

    async def _fake_retry(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        calls["retry"] += 1
        return SimpleNamespace(status="pending")

    monkeypatch.setattr(document_metadata_operations, "patch_pipeline", _fake_patch, raising=True)
    monkeypatch.setattr(document_processing_operations, "retry_document", _fake_retry, raising=True)

    class _DummyDB:
        pass

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.post("/api/v1/documents/batch/reingest", response_model=DocumentBatchRetryResponse)(batch_reingest_documents)

    client = TestClient(app)
    res = client.post(
        "/api/v1/documents/batch/reingest",
        json={
            "document_ids": [str(doc1), str(doc2)],
            "patch": {"chunk_size": 123, "chunk_overlap": 20},
            "replace": True,
            "force": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["queued"] == 2
    assert calls["patch"] == 2
    assert calls["retry"] == 2
