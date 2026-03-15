from __future__ import annotations

import asyncio
import uuid

import fitz  # PyMuPDF
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.parsing.subprocess_runner import SubprocessWorkerError


def test_parsing_workspace_parse_returns_diagnostics_on_failure(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    # Create a tiny PDF so diagnostics can sample page text.
    pdf_path = tmp_path / "demo.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = uuid.uuid4()
            self.filename = "demo.pdf"
            self.file_type = "pdf"
            self.file_path = str(pdf_path)
            self.status = "pending"
            self.processing_progress = 0
            self.current_stage = "parsing"
            self.error_message = None
            self.total_characters = 0
            self.chunk_count = 0
            self.doc_metadata = {"workspace": "parsing", "parser_backend_requested": "auto"}

    dummy_doc = _DummyDoc()

    monkeypatch.setattr(parsing_module, "_get_workspace_document", lambda *_a, **_k: dummy_doc, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "_assert_path_under_tenant_root", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "is_minio_uri", lambda *_a, **_k: False, raising=True)

    # Force a subprocess failure so we can assert the error payload.
    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await asyncio.sleep(0)  # Sonar S7503
        raise SubprocessWorkerError("boom", details={"type": "RuntimeError"})

    monkeypatch.setattr(parsing_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    class _DummyDB:
        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def query(self, _model):  # noqa: ANN001
            class _Q:  # noqa: D401
                def filter(self, *_a, **_k):  # noqa: ANN001
                    return self

                def first(self):  # noqa: ANN001
                    return None

            return _Q()

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

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
    app.include_router(parsing_module.router, prefix="/api/v1/parsing")
    client = TestClient(app)

    res = client.post(f"/api/v1/parsing/documents/{doc_id}/parse")
    assert res.status_code == 500, res.text
    body = res.json()
    detail = body.get("detail") or {}
    assert isinstance(detail, dict)
    assert "diagnostics" in detail
    diagnostics = detail.get("diagnostics") or {}
    assert diagnostics.get("file_type") == ".pdf"
    assert diagnostics.get("parser_backend_requested") in ("auto", "basic", "docling", "deepdoc")

