from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


def test_documents_preview_includes_analytics_raw_and_cleaned(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()

    class _DummyDB:
        pass

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        assert payload.get("action") == "parse_documents"
        return {
            "resolved_backend": "basic",
            "pdf_quality": {"page_count": 12},
            "documents": [
                {
                    "page_content": "# Title\\n\\nHello\\n@@1\\t0\\t0\\t1\\t1##\\n",
                    "metadata": {"page": 1, "content_type": "table"},
                }
            ],
        }

    def _fake_clean_documents(items, **_kwargs):  # noqa: ANN001, ANN202
        assert isinstance(items, list)
        cleaned = [
            Document(
                page_content="# Title\\n\\nCLEANED\\n@@1\\t0\\t0\\t1\\t1##\\n",
                metadata=dict(getattr(items[0], "metadata", {}) or {}),
            )
        ]
        return cleaned, {}

    monkeypatch.setattr(documents_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)
    monkeypatch.setattr(documents_module.governance_processor, "clean_documents", _fake_clean_documents, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/preview")(documents_module.preview_document)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/preview",
        data={"parser_backend": "basic", "governance_enabled": "true"},
        files={"file": ("demo.pdf", b"%PDF-1.4\\n%dummy\\n", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert "analytics" in body
    assert isinstance(body["analytics"], dict)
    assert "raw" in body["analytics"]
    assert "cleaned" in body["analytics"]
    assert body["analytics"]["raw"]["page_count"] == 12
    assert body["analytics"]["raw"]["table_count"] == 1
    assert body["analytics"]["raw"]["heading_count"] == 1
    assert body["analytics"]["cleaned"]["char_count"] != body["analytics"]["raw"]["char_count"]


def test_documents_preview_text_uses_inline_parser(monkeypatch, tmp_path):  # noqa: ANN001, ARG001
    import app.api.v1.document_preview as document_preview_module
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()

    class _DummyDB:
        pass

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    def _raise_subprocess_called(**_kwargs):  # noqa: ANN202
        raise AssertionError("TXT preview should not invoke subprocess worker")

    def _fake_parse_with_provenance(source_path, *, parser_backend, tenant_id, document_id):  # noqa: ANN001, ANN202
        assert source_path.suffix == ".txt"
        assert parser_backend == "text"
        assert tenant_id
        assert document_id
        return (
            [
                Document(
                    page_content=source_path.read_text(encoding="utf-8"),
                    metadata={"parser_backend": "text"},
                )
            ],
            "text",
            {"source": "inline-test"},
        )

    monkeypatch.setattr(settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "run_subprocess_worker", _raise_subprocess_called, raising=True)
    monkeypatch.setattr(
        document_preview_module.parser_factory,
        "parse_with_provenance",
        _fake_parse_with_provenance,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/preview")(documents_module.preview_document)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/preview",
        data={"parser_backend": "auto"},
        files={"file": ("demo.txt", b"plain preview", "text/plain")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["parser_backend"] == "text"
    assert body["segments"][0]["content"] == "plain preview"
    assert body["segments"][0]["metadata"]["parser_backend"] == "text"
