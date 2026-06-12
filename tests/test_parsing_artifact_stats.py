from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


def test_parsing_workspace_persists_and_returns_artifact_stats(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%dummy\n")

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

    # Relax backend validation for unit test.
    monkeypatch.setattr(parsing_module.parser_factory, "resolve_backend", lambda *_a, **_k: "basic", raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        return {
            "resolved_backend": "basic",
            "pdf_quality": {
                "score": 0.9,
                "text_quality_score": 0.9,
                "format_consistency_score": 0.9,
                "table_quality_score": 0.9,
                "is_scanned": False,
                "page_count": 2.0,
            },
            "documents": [
                {
                    "page_content": "Hello@@1\t0\t1\t0\t1##\n\nWorld@@1\t0\t1\t0\t1##",
                    "metadata": {"page": 1},
                },
                {"page_content": "<table>...</table>", "metadata": {"content_type": "table"}},
                {"page_content": "image", "metadata": {"doc_type_kwd": "image"}},
            ],
        }

    monkeypatch.setattr(parsing_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    class _DummyQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return None

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery()

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
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
    assert res.status_code == 200, res.text
    body = res.json()

    stats = body.get("stats") or {}
    assert stats.get("page_count") == 2
    assert stats.get("table_count") == 1
    assert stats.get("image_count") == 1
    assert stats.get("block_count") == 2

    # Persisted in document metadata (for list/search/dashboard use).
    assert int(dummy_doc.doc_metadata.get("page_count") or 0) == 2
    assert int(dummy_doc.doc_metadata.get("table_count") or 0) == 1
    assert int(dummy_doc.doc_metadata.get("image_count") or 0) == 1
    assert int(dummy_doc.doc_metadata.get("block_count") or 0) == 2


def test_compute_parsing_artifact_stats_counts_markdown_images_without_parser_metadata() -> None:
    from app.parsing.artifact_stats import compute_parsing_artifact_stats  # noqa: WPS433

    stats = compute_parsing_artifact_stats(
        documents=[],
        original_markdown="![Image](layout://image)@@5\t80\t188\t30\t263##",
        markdown="![](/api/v1/documents/image/first)\n\n![](/api/v1/documents/image/second)",
        pdf_quality={"page_count": 5},
    )

    assert stats["image_count"] == 2
    assert stats["block_count"] == 1
