
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentBatchRetryResponse
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


def test_documents_batch_reingest_calls_patch_and_retry(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import batch_reingest_documents

    tenant_id = uuid.uuid4()
    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()

    # Avoid auth/DB logic in unit test.
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    calls = {"patch": 0, "retry": 0}

    async def _fake_patch(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        calls["patch"] += 1
        return None

    async def _fake_retry(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        calls["retry"] += 1
        return {
            "id": kwargs.get("document_id"),
            "status": "pending",
            "processing_progress": 0,
            "current_stage": "queued",
            "error_message": None,
        }

    monkeypatch.setattr(documents_module, "patch_document_pipeline", _fake_patch, raising=True)
    monkeypatch.setattr(documents_module, "retry_document_processing", _fake_retry, raising=True)

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

