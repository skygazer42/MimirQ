from __future__ import annotations

import asyncio
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


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
        await asyncio.sleep(0)  # Sonar S7503
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

