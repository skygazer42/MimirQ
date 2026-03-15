from __future__ import annotations

import asyncio
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_chunk_preview_includes_original_text_cleaned_when_position_tags(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import preview_chunking
    from app.rag.chunking.factory import chunker_factory
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(chunker_factory, "resolve_strategy", lambda s: s, raising=True)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            # Deterministic: treat parsed "pages" as chunks.
            return list(documents or [])

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda *_a, **_k: _Chunker(), raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await asyncio.sleep(0)  # Sonar S7503
        assert payload.get("action") == "parse_documents"
        return {
            "resolved_backend": "auto",
            "documents": [
                {
                    "page_content": "Hello@@1\t0.1\t0.2\t0.3\t0.4##\n\nWorld",
                    "metadata": {"page": 1, "start_char": 0},
                }
            ],
        }

    monkeypatch.setattr(documents_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/chunk-preview")(preview_chunking)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.pdf", b"dummy", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert isinstance(body.get("original_text"), str)
    assert "@@" in body["original_text"]
    assert "##" in body["original_text"]

    assert isinstance(body.get("original_text_cleaned"), str)
    assert "@@" not in body["original_text_cleaned"]
    assert "##" not in body["original_text_cleaned"]
    assert "Hello" in body["original_text_cleaned"]

