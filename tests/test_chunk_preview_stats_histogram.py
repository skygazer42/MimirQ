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


def _build_client(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import preview_chunking
    from app.rag.chunking.factory import chunker_factory

    # preview_chunking enforces tenant membership via DB; bypass for this unit test.
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    monkeypatch.setattr(chunker_factory, "resolve_strategy", lambda s: s, raising=True)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            # Keep deterministic: treat parsed "pages" as chunks.
            return list(documents or [])

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda *_, **__: _Chunker(), raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        assert payload.get("action") == "parse_documents"
        file_path = Path(str(payload.get("file_path") or ""))
        text = file_path.read_text(encoding="utf-8")
        docs = [
            {"page_content": text + "\n# page 1", "metadata": {"page": 1, "start_char": 0}},
            {"page_content": text + "\n# page 2", "metadata": {"page": 2, "start_char": 0}},
            {"page_content": text + "\n# page 3", "metadata": {"page": 3, "start_char": 0}},
        ]
        return {"resolved_backend": "auto", "documents": docs}

    monkeypatch.setattr(documents_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/chunk-preview")(preview_chunking)
    return TestClient(app)


def test_chunk_preview_stats_includes_histogram(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.pdf", b"%PDF-1.4\nhello world", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    chunks = body.get("chunks") or []
    assert len(chunks) >= 1

    stats = body.get("stats") or {}
    hist = stats.get("histogram")
    assert isinstance(hist, list) and hist, "stats.histogram must be a non-empty list"

    total = 0
    for b in hist:
        assert isinstance(b, dict)
        assert isinstance(b.get("label"), str) and b["label"]
        assert b.get("min") is None or isinstance(b.get("min"), int)
        assert b.get("max") is None or isinstance(b.get("max"), int)
        assert isinstance(b.get("count"), int)
        total += int(b.get("count") or 0)

    assert total == len(chunks)
