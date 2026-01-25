from __future__ import annotations

from pathlib import Path
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


def _build_client(monkeypatch, *, parsed_pages: int = 1):  # noqa: ANN001
    from app.api.v1.documents import preview_chunking
    from app.services.dataset_service import DatasetService
    import app.api.v1.documents as documents_module
    from app.rag.chunking.factory import chunker_factory

    monkeypatch.setattr(DatasetService, "ensure_member", lambda db, tenant_id, account_id: None, raising=True)
    monkeypatch.setattr(chunker_factory, "resolve_strategy", lambda s: s, raising=True)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            # Keep test deterministic: treat parsed "pages" as chunks.
            return list(documents or [])

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda strategy, chunk_size, chunk_overlap: _Chunker(), raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        assert payload.get("action") == "parse_documents"
        file_path = Path(str(payload.get("file_path") or ""))
        text = file_path.read_text(encoding="utf-8")
        pages = max(1, int(parsed_pages or 1))
        docs = []
        if pages == 1:
            docs = [
                {
                    "page_content": text,
                    "metadata": {"page": 1, "start_char": 0},
                }
            ]
        else:
            # Make per-page content distinct so start offsets are deterministic.
            for i in range(pages):
                docs.append(
                    {
                        "page_content": f"{text}\n\n# page {i + 1}",
                        "metadata": {"page": i + 1, "start_char": 0},
                    }
                )
        return {
            "resolved_backend": "auto",
            "documents": docs,
        }

    monkeypatch.setattr(documents_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.post("/api/v1/documents/chunk-preview")(preview_chunking)
    return TestClient(app)


def test_documents_chunk_preview_returns_tokens_est_and_original_text_flags(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_token"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["params"]["unit"] == "tokens"
    assert body["original_text_included"] is True
    assert body["original_text_truncated"] is False
    assert body["original_text_max_chars"] == 100000
    assert body["chunks"]
    assert isinstance(body["chunks"][0].get("tokens_est"), int)


def test_documents_chunk_preview_omits_original_text_when_too_large(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    big = ("a" * 100001).encode("utf-8")
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("big.txt", big, "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("original_text") is None
    assert body["original_text_included"] is False
    assert body["original_text_truncated"] is True
    assert body["original_text_max_chars"] == 100000


def test_documents_chunk_preview_allows_small_token_chunk_size(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=50&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_token"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["params"]["unit"] == "tokens"


def test_documents_chunk_preview_separator_ignores_overlap(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=200",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "separator",
            "separator_preset": "paragraph",
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["params"]["chunk_overlap"] == 0
    assert any("ignores chunk_overlap" in w for w in (body.get("warnings") or []))


def test_documents_chunk_preview_can_disable_original_text(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10&include_original_text=false",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("original_text") is None
    assert body.get("original_text_included") is False
    assert body.get("original_text_truncated") is False


def test_documents_chunk_preview_truncates_chunks_when_max_chunks(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch, parsed_pages=5)

    payload = ("hello world " * 20).encode("utf-8")
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10&max_chunks=2",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["chunks_truncated"] is True
    assert body["chunks_max_count"] == 2
    assert body["total_chunks"] == 2
    assert body["total_chunks_full"] == 5
    assert len(body["chunks"]) == 2
