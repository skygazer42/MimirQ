from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
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


def _build_client(  # noqa: ANN001
    monkeypatch,
    *,
    parsed_pages: int = 1,
    include_page_meta: bool = True,
    duplicate_page_meta: bool = False,
    duplicate_page_content: bool = False,
    start_char_overrides: list[int] | None = None,
    inline_text_parse_enabled: bool = False,
):
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.api.v1.documents import preview_chunking, preview_chunking_by_sha
    from app.rag.chunking.factory import chunker_factory
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", inline_text_parse_enabled, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)
    monkeypatch.setattr(chunker_factory, "resolve_strategy", lambda s: s, raising=True)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            # Keep test deterministic: treat parsed "pages" as chunks.
            return list(documents or [])

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda *_, **__: _Chunker(), raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        assert payload.get("action") == "parse_documents"
        file_path = Path(str(payload.get("file_path") or ""))
        text = file_path.read_text(encoding="utf-8")
        pages = max(1, int(parsed_pages or 1))
        docs = []
        def _meta_for_page(i: int) -> dict:  # noqa: ANN001
            meta = {"start_char": 0}
            if start_char_overrides and i < len(start_char_overrides):
                meta["start_char"] = int(start_char_overrides[i])
            if include_page_meta:
                meta["page"] = 1 if duplicate_page_meta else (i + 1)
            return meta

        if pages == 1:
            docs = [{"page_content": text, "metadata": _meta_for_page(0)}]
        else:
            for i in range(pages):
                content = text if duplicate_page_content else f"{text}\n\n# page {i + 1}"
                docs.append({"page_content": content, "metadata": _meta_for_page(i)})
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
    app.post("/api/v1/documents/chunk-preview/by-sha")(preview_chunking_by_sha)
    return TestClient(app)


def test_documents_chunk_preview_markdown_uses_inline_parse_not_subprocess(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module

    client = _build_client(monkeypatch, inline_text_parse_enabled=True)

    async def _fail_run_subprocess_worker(**_kwargs):  # noqa: ANN202
        raise AssertionError("markdown preview should not start subprocess worker")

    monkeypatch.setattr(documents_module, "run_subprocess_worker", _fail_run_subprocess_worker, raising=True)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.md", b"# Title\n\nhello world", "text/markdown")},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["parser_backend"] == "markdown"
    assert body["chunks"]


def test_documents_chunk_preview_returns_tokens_est_and_original_text_flags(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_token"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    assert isinstance(res.headers.get("server-timing"), str) and "total" in res.headers.get("server-timing", "")
    body = res.json()
    assert isinstance(body.get("file_sha256"), str) and len(body["file_sha256"]) == 64
    assert body.get("parse_cache_hit") in (True, False)
    assert body.get("preview_duration_ms") is None or isinstance(body.get("preview_duration_ms"), int)
    assert body.get("upload_duration_ms") is None or isinstance(body.get("upload_duration_ms"), int)
    assert body.get("parse_duration_ms") is None or isinstance(body.get("parse_duration_ms"), int)
    assert isinstance(body.get("governance_duration_ms"), int)
    assert isinstance(body.get("chunking_duration_ms"), int)
    assert isinstance(body.get("stats_duration_ms"), int)
    assert body["params"]["unit"] == "tokens"
    assert body["original_text_included"] is True
    assert body["original_text_truncated"] is False
    assert body["original_text_max_chars"] == 100000
    assert body["chunks"]
    assert isinstance(body["chunks"][0].get("tokens_est"), int)


def test_documents_chunk_preview_returns_token_stats_when_chunks_omitted(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200&include_chunks=false",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()

    # include_chunks=false should keep payload small but still return token distribution stats.
    assert body.get("chunks") == []
    tok = body.get("chunking_stats_tokens")
    assert isinstance(tok, dict)
    assert tok.get("unit") == "tokens"
    assert isinstance(tok.get("median"), int)
    hist = tok.get("histogram")
    assert isinstance(hist, list) and hist


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
    patches = body.get("recommendation_patches") or []
    assert any(p.get("id") == "increase_original_text_max_chars" for p in patches)


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


def test_documents_chunk_preview_review_signals_optional(monkeypatch):  # noqa: ANN001
    """include_review_signals should gate extra per-chunk signal fields."""
    from langchain_core.documents import Document

    from app.rag.chunking.factory import chunker_factory

    client = _build_client(monkeypatch)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            # Two overlapping duplicate chunks.
            return [
                Document(page_content="a" * 200, metadata={"page": 1, "start_char": 0}),
                Document(page_content="a" * 200, metadata={"page": 1, "start_char": 50}),
            ]

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda *_, **__: _Chunker(), raising=True)

    res0 = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res0.status_code == 200
    body0 = res0.json()
    assert body0.get("review_signals") is None

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10&include_review_signals=true",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    rs = body.get("review_signals")
    assert isinstance(rs, dict)
    assert rs.get("basis") == "all"
    assert rs.get("short_indices") == []
    assert rs.get("duplicate_indices") == [0, 1]
    assert rs.get("overlap_indices") == [1]
    assert rs.get("gap_indices") == []
    assert (rs.get("overlap_prev_by_index") or {}).get("1") == 150


def test_documents_chunk_preview_review_signals_parent_child_basis(monkeypatch):  # noqa: ANN001
    from langchain_core.documents import Document

    from app.rag.chunking.factory import chunker_factory

    client = _build_client(monkeypatch)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            return [
                Document(
                    page_content="p" * 200,
                    metadata={"page": 1, "start_char": 0, "chunk_role": "parent", "parent_id": "p1"},
                ),
                Document(
                    page_content="c" * 100,
                    metadata={"page": 1, "start_char": 50, "chunk_role": "child", "parent_id": "p1"},
                ),
            ]

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda *_, **__: _Chunker(), raising=True)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200&include_review_signals=true",
        data={"parser_backend": "auto", "chunk_strategy": "parent_child"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    rs = body.get("review_signals")
    assert isinstance(rs, dict)
    assert rs.get("basis") == "child"
    assert rs.get("gap_indices") == [1]
    assert (rs.get("gap_before_by_index") or {}).get("1") == 50


def test_documents_chunk_preview_exposes_optional_hierarchy_basis_field(monkeypatch):  # noqa: ANN001
    from langchain_core.documents import Document

    from app.rag.chunking.factory import chunker_factory

    client = _build_client(monkeypatch)

    class _Chunker:
        def split_documents(self, documents):  # noqa: ANN001, ANN202
            return [
                Document(
                    page_content="p" * 200,
                    metadata={
                        "page": 1,
                        "start_char": 0,
                        "hierarchy_basis": "parent_child",
                        "hierarchy_level": "parent",
                    },
                ),
                Document(
                    page_content="c" * 100,
                    metadata={
                        "page": 1,
                        "start_char": 50,
                        "hierarchy_basis": "parent_child",
                        "hierarchy_level": "child",
                    },
                ),
            ]

    monkeypatch.setattr(chunker_factory, "get_chunker", lambda *_, **__: _Chunker(), raising=True)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200",
        data={"parser_backend": "auto", "chunk_strategy": "parent_child"},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["chunks"][0].get("hierarchy_basis") == "parent_child"
    assert body["chunks"][1].get("hierarchy_basis") == "parent_child"


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


def test_documents_chunk_preview_parse_cache_hit(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.preview_cache import preview_parse_cache

    preview_parse_cache.clear()

    fixed_tenant_id = uuid.uuid4()
    client = _build_client(monkeypatch)
    client.app.dependency_overrides[get_tenant_id] = lambda: fixed_tenant_id

    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 600, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_DOC_CHARS", 2_000_000, raising=False)

    payload = b"hello world"
    res1 = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1.get("parse_cache_hit") is False

    res2 = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2.get("parse_cache_hit") is True
    assert isinstance(body2.get("parse_cache_age_ms"), int) and body2["parse_cache_age_ms"] >= 0
    assert body2.get("parse_duration_ms") == 0


def test_documents_chunk_preview_parse_cache_version_busts_cache(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.preview_cache import preview_parse_cache

    preview_parse_cache.clear()

    fixed_tenant_id = uuid.uuid4()
    client = _build_client(monkeypatch)
    client.app.dependency_overrides[get_tenant_id] = lambda: fixed_tenant_id

    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 600, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_DOC_CHARS", 2_000_000, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1", raising=False)

    payload = b"hello world"
    warm = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert warm.status_code == 200
    assert warm.json().get("parse_cache_hit") is False

    hit = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert hit.status_code == 200
    assert hit.json().get("parse_cache_hit") is True

    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v2", raising=False)
    bust = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert bust.status_code == 200
    assert bust.json().get("parse_cache_hit") is False


def test_documents_chunk_preview_by_sha_cache_miss(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.preview_cache import preview_parse_cache

    preview_parse_cache.clear()

    client = _build_client(monkeypatch)

    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 600, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 32, raising=False)

    res = client.post(
        "/api/v1/documents/chunk-preview/by-sha?chunk_size=100&chunk_overlap=10",
        data={
            "file_sha256": "0" * 64,
            "file_type": "txt",
            "filename": "doc.txt",
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
        },
    )
    assert res.status_code == 404


def test_documents_chunk_preview_by_sha_hit(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.preview_cache import preview_parse_cache

    preview_parse_cache.clear()

    fixed_tenant_id = uuid.uuid4()
    client = _build_client(monkeypatch)
    client.app.dependency_overrides[get_tenant_id] = lambda: fixed_tenant_id

    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 600, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(settings, "PREVIEW_PARSE_CACHE_MAX_DOC_CHARS", 2_000_000, raising=False)

    payload = b"hello world"
    warm = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert warm.status_code == 200
    warm_body = warm.json()
    sha = warm_body.get("file_sha256")
    assert isinstance(sha, str) and len(sha) == 64

    res = client.post(
        "/api/v1/documents/chunk-preview/by-sha?chunk_size=100&chunk_overlap=10",
        data={
            "file_sha256": sha,
            "file_type": "txt",
            "filename": "doc.txt",
            "file_size": 11,
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("parse_cache_hit") is True
    assert body.get("parse_duration_ms") == 0
    assert body.get("upload_duration_ms") == 0
    assert body.get("file_sha256") == sha


def test_documents_chunk_preview_strategy_params_for_separator(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "separator",
            "separator_preset": "paragraph",
            "keep_separator": "true",
            "separator_max_chunk_size": "0",
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("params", {}).get("strategy_params"), dict)
    sp = body["params"]["strategy_params"]
    assert sp.get("separator_preset") == "paragraph"
    assert isinstance(sp.get("separator"), str) and sp.get("separator")
    assert sp.get("keep_separator") in (True, False)


def test_documents_chunk_preview_strategy_params_for_parent_child(monkeypatch):  # noqa: ANN001
    from app.rag.chunking.factory import chunker_factory

    client = _build_client(monkeypatch)

    captured = {}

    class _PCChunker:
        def __init__(self, child_ratio: float, min_child_size: int):  # noqa: ANN001
            self.child_ratio = float(child_ratio)
            self.min_child_size = int(min_child_size)
            # Deterministic "effective" params for API echo.
            self.child_size = int(min_child_size)
            self.child_overlap = 0

        def split_documents(self, documents):  # noqa: ANN001, ANN202
            return list(documents or [])

    def _get_chunker(strategy, chunk_size, chunk_overlap, **kwargs):  # noqa: ANN001, ANN202
        captured["strategy"] = strategy
        captured["chunk_size"] = chunk_size
        captured["chunk_overlap"] = chunk_overlap
        captured["kwargs"] = dict(kwargs)
        return _PCChunker(
            child_ratio=float(kwargs.get("child_ratio")),
            min_child_size=int(kwargs.get("min_child_size")),
        )

    monkeypatch.setattr(chunker_factory, "get_chunker", _get_chunker, raising=True)
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=100",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "parent_child",
            "child_ratio": "0.25",
            "min_child_size": "300",
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    assert captured.get("strategy") == "parent_child"
    assert captured.get("kwargs", {}).get("child_ratio") == pytest.approx(0.25)
    assert captured.get("kwargs", {}).get("min_child_size") == 300

    body = res.json()
    sp = body["params"]["strategy_params"]
    assert sp.get("child_ratio") == pytest.approx(0.25)
    assert sp.get("min_child_size") == 300
    assert sp.get("child_size") == 300
    assert sp.get("child_overlap") == 0


def test_documents_chunk_preview_strategy_params_from_pipeline_parent_child(monkeypatch):  # noqa: ANN001
    from app.rag.chunking.factory import chunker_factory

    client = _build_client(monkeypatch)

    captured = {}

    class _PCChunker:
        def __init__(self, child_ratio: float, min_child_size: int):  # noqa: ANN001
            self.child_ratio = float(child_ratio)
            self.min_child_size = int(min_child_size)
            self.child_size = int(min_child_size)
            self.child_overlap = 0

        def split_documents(self, documents):  # noqa: ANN001, ANN202
            return list(documents or [])

    def _get_chunker(strategy, chunk_size, chunk_overlap, **kwargs):  # noqa: ANN001, ANN202
        captured["strategy"] = strategy
        captured["kwargs"] = dict(kwargs)
        return _PCChunker(
            child_ratio=float(kwargs.get("child_ratio")),
            min_child_size=int(kwargs.get("min_child_size")),
        )

    monkeypatch.setattr(chunker_factory, "get_chunker", _get_chunker, raising=True)
    pipeline = json.dumps({"chunk_strategy_params": {"child_ratio": 0.25, "min_child_size": 300}})
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=100",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "parent_child",
            "pipeline": pipeline,
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    assert captured.get("strategy") == "parent_child"
    assert captured.get("kwargs", {}).get("child_ratio") == pytest.approx(0.25)
    assert captured.get("kwargs", {}).get("min_child_size") == 300

    body = res.json()
    sp = body["params"]["strategy_params"]
    assert sp.get("child_ratio") == pytest.approx(0.25)
    assert sp.get("min_child_size") == 300


def test_documents_chunk_preview_strategy_params_explicit_overrides_pipeline_parent_child(monkeypatch):  # noqa: ANN001
    from app.rag.chunking.factory import chunker_factory

    client = _build_client(monkeypatch)

    captured = {}

    class _PCChunker:
        def __init__(self, child_ratio: float, min_child_size: int):  # noqa: ANN001
            self.child_ratio = float(child_ratio)
            self.min_child_size = int(min_child_size)
            self.child_size = int(min_child_size)
            self.child_overlap = 0

        def split_documents(self, documents):  # noqa: ANN001, ANN202
            return list(documents or [])

    def _get_chunker(strategy, chunk_size, chunk_overlap, **kwargs):  # noqa: ANN001, ANN202
        captured["strategy"] = strategy
        captured["kwargs"] = dict(kwargs)
        return _PCChunker(
            child_ratio=float(kwargs.get("child_ratio")),
            min_child_size=int(kwargs.get("min_child_size")),
        )

    monkeypatch.setattr(chunker_factory, "get_chunker", _get_chunker, raising=True)
    pipeline = json.dumps({"chunk_strategy_params": {"child_ratio": 0.5, "min_child_size": 200}})
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=100",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "parent_child",
            "pipeline": pipeline,
            "child_ratio": "0.25",
            "min_child_size": "300",
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    assert captured.get("strategy") == "parent_child"
    assert captured.get("kwargs", {}).get("child_ratio") == pytest.approx(0.25)
    assert captured.get("kwargs", {}).get("min_child_size") == 300

    body = res.json()
    sp = body["params"]["strategy_params"]
    assert sp.get("child_ratio") == pytest.approx(0.25)
    assert sp.get("min_child_size") == 300


def test_documents_chunk_preview_strategy_params_from_pipeline_separator(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    pipeline = json.dumps(
        {
            "chunk_strategy_params": {
                "separator_preset": "custom",
                "separator": "\\n\\n",
                "keep_separator": False,
                "separator_max_chunk_size": 0,
            }
        }
    )
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "separator",
            "pipeline": pipeline,
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    sp = body["params"]["strategy_params"]
    assert sp.get("separator_preset") == "custom"
    assert sp.get("separator") == "\n\n"
    assert sp.get("keep_separator") is False


def test_documents_chunk_preview_ignores_parent_child_params_for_other_strategies(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "child_ratio": "0.25",
            "min_child_size": "300",
        },
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert any("ignored" in str(w) and "child_ratio" in str(w) for w in (body.get("warnings") or []))
    assert body.get("params", {}).get("strategy_params") == {}


def test_documents_chunk_preview_rebases_offsets_when_page_missing(monkeypatch):  # noqa: ANN001
    """
    Regression: parsers may emit multiple Documents without a `metadata.page` field.

    Chunk preview joins docs with "\\n"; start_index must be rebased by doc order, not by page (None).
    """
    client = _build_client(monkeypatch, parsed_pages=2, include_page_meta=False)
    payload = b"hello world " * 10

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body.get("chunks") or []) == 2
    first = body["chunks"][0]
    second = body["chunks"][1]
    assert first["start_index"] == 0
    assert second["start_index"] == len(first["content"]) + 1


def test_documents_chunk_preview_rebases_offsets_when_page_duplicated(monkeypatch):  # noqa: ANN001
    """
    Regression: some parsers can emit duplicate page numbers (e.g. multiple segments per page).

    start_index must not collide just because `metadata.page` is the same.
    """
    client = _build_client(monkeypatch, parsed_pages=2, include_page_meta=True, duplicate_page_meta=True)
    payload = b"hello world " * 10

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=100&chunk_overlap=10",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body.get("chunks") or []) == 2
    first = body["chunks"][0]
    second = body["chunks"][1]
    assert first["start_index"] == 0
    assert second["start_index"] == len(first["content"]) + 1


def test_documents_chunk_preview_recommendation_patch_for_duplicates(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch, parsed_pages=2, duplicate_page_content=True)

    payload = b"hello world " * 10
    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", payload, "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    patches = body.get("recommendation_patches") or []
    found = [p for p in patches if p.get("id") == "enable_governance_drop_duplicate_paragraphs"]
    assert found, patches
    assert found[0].get("target") == "pipeline"
    assert (found[0].get("patch") or {}).get("governance_drop_duplicate_paragraphs") is True


def test_documents_chunk_preview_recommendation_patch_for_overlap_waste(monkeypatch):  # noqa: ANN001
    # Force overlap by shifting page 2 start_char so it begins at index 0 (complete overlap).
    text = "hello world " * 10
    doc_base = len(f"{text}\n\n# page 1") + 1  # join uses "\\n"
    client = _build_client(monkeypatch, parsed_pages=2, start_char_overrides=[0, -doc_base])

    res = client.post(
        "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=400",
        data={"parser_backend": "auto", "chunk_strategy": "langchain_recursive"},
        files={"file": ("doc.txt", text.encode("utf-8"), "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    patches = body.get("recommendation_patches") or []
    found = [p for p in patches if p.get("id") in ("tune_overlap", "reduce_overlap")]
    assert found, patches
    assert found[0].get("target") == "preview"
    assert isinstance((found[0].get("patch") or {}).get("chunk_overlap"), int)
