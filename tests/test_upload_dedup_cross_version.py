from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail
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

    def refresh(self, obj) -> None:  # noqa: ANN001
        # Our unit test uses a dummy DB; mimic a few DB defaults needed by the response_model.
        if getattr(obj, "chunk_count", None) is None:
            obj.chunk_count = 0
        if getattr(obj, "total_characters", None) is None:
            obj.total_characters = 0
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        return None


def test_upload_dedup_cross_version_reuses_existing_doc_and_reprocesses(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import upload_document
    from app.core.config import settings
    from app.models.document import Document as DBDocument

    monkeypatch.setattr(settings, "UPLOAD_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    dup_id = uuid.uuid4()

    payload = b"hello"
    sha = hashlib.sha256(payload).hexdigest()
    now = datetime.now(UTC)

    dup = DBDocument(
        id=dup_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="doc.txt",
        file_type="txt",
        file_size=len(payload),
        file_path=str(tmp_path / "existing.txt"),
        owner_id="test-account",
        access_mode=None,
        status="completed",
        processing_progress=100,
        doc_metadata={
            "file_sha256": sha,
            "pipeline_hash": "oldhash",
            "active_pipeline_hash": "oldhash",
            "active_pipeline_ready": True,
        },
        created_at=now,
        updated_at=now,
    )
    dup.chunk_count = 1
    dup.total_characters = len(payload)

    class _Dataset:
        def __init__(self, dataset_id: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id
            self.dataset_metadata = {}

    # Avoid real DB lookups in unit test.
    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *_args, **_kwargs: _Dataset(dataset_id), raising=True)

    # Ensure exact-dedup (same sha + same pipeline_hash) does not trigger.
    monkeypatch.setattr(documents_module, "_find_duplicate_document", lambda *_args, **_kwargs: None, raising=True)

    # Cross-version dedup should hit by sha only (new helper is introduced by the feature).
    monkeypatch.setattr(documents_module, "_find_duplicate_document_by_sha", lambda *_args, **_kwargs: dup, raising=False)

    calls = {"retry": 0}

    async def _fake_retry(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        calls["retry"] += 1
        dup.status = "pending"
        dup.processing_progress = 0
        dup.current_stage = "queued"
        dup.error_message = None
        return {
            "id": dup.id,
            "status": dup.status,
            "processing_progress": dup.processing_progress,
            "current_stage": dup.current_stage,
            "error_message": dup.error_message,
        }

    monkeypatch.setattr(documents_module, "retry_document_processing", _fake_retry, raising=True)

    async def _fake_enqueue(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        return "task-123"

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fake_enqueue, raising=True)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    # Mirror the real API contract: metadata should be exposed under `metadata` (alias of ORM `doc_metadata`).
    app.post("/api/v1/documents/upload", status_code=201, response_model=DocumentDetail)(upload_document)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.txt", payload, "text/plain")},
        data={
            "dataset_id": str(dataset_id),
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            # Force a different pipeline_hash than dup's active version.
            "pipeline": json.dumps({"chunk_size": 123, "chunk_overlap": 20}),
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("id") == str(dup_id)
    assert calls["retry"] == 1

