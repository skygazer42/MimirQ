from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db


def test_upload_document_quota_exceeded_cleans_up_staged_file(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    import app.services.tenant_quota_service as tq
    from app.api.v1.documents import upload_document

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DEDUP_ENABLED", False, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self, dataset_id0: uuid.UUID) -> None:
            self.id = dataset_id0
            self.dataset_metadata = {}

    monkeypatch.setattr(
        documents_module,
        "_resolve_writable_dataset",
        lambda *_args, **_kwargs: _Dataset(dataset_id),
        raising=True,
    )

    def _raise_quota(*_args, **_kwargs) -> None:  # noqa: ANN001
        raise HTTPException(status_code=429, detail="Tenant storage quota exceeded")

    monkeypatch.setattr(tq, "enforce_tenant_upload_quotas", _raise_quota, raising=True)

    def _override_get_db():  # noqa: ANN202
        yield object()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.post("/api/v1/documents/upload", status_code=201)(upload_document)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        data={
            "dataset_id": str(dataset_id),
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline": json.dumps({"chunk_size": 333}),
        },
    )
    assert res.status_code == 429, res.text

    # The handler should delete the staged file when quota enforcement rejects the upload.
    upload_dir = (Path(str(tmp_path)) / str(tenant_id)).resolve(strict=False)
    assert list(upload_dir.glob("*.txt")) == []
