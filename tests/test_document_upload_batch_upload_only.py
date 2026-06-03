from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


class _DummyDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def test_upload_batch_upload_only_stores_document_without_enqueueing_processing(monkeypatch, tmp_path: Path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    import app.api.v1.document_upload as document_upload
    import app.services.tenant_quota_service as tenant_quota_service
    from app.core.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DEDUP_ENABLED", False, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self, dataset_id0: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id0
            self.dataset_metadata = {}

    monkeypatch.setattr(
        documents_module,
        "_resolve_writable_dataset",
        lambda *_args, **_kwargs: _Dataset(dataset_id),
        raising=True,
    )
    monkeypatch.setattr(tenant_quota_service, "enforce_tenant_upload_quotas", lambda *_args, **_kwargs: None)

    def _unexpected_create_run(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("upload_only must not create an ingestion run")

    async def _unexpected_enqueue(**_kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        raise AssertionError("upload_only must not enqueue document processing")

    monkeypatch.setattr(documents_module.IngestionRunService, "create_run", _unexpected_create_run, raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _unexpected_enqueue, raising=True)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.include_router(document_upload.router, prefix="/api/v1/documents")
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/upload-batch",
        files=[("files", ("source.txt", b"hello", "text/plain"))],
        data={
            "dataset_id": str(dataset_id),
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "upload_only": "true",
        },
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["successful_count"] == 1
    assert body["successful"][0]["filename"] == "source.txt"
    assert body["successful"][0]["status"] == "pending"

    document = dummy_db.added[0]
    assert getattr(document, "dataset_id") == dataset_id
    assert getattr(document, "status") == "pending"
    assert getattr(document, "doc_metadata")["ingest_stage"] == "uploaded_only"
    assert Path(str(getattr(document, "file_path"))).exists()
