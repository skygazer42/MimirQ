import hashlib
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import documents as documents_module
from app.core.database import get_db
from app.services.preview_cache import ParseCacheEntry, preview_parse_cache

chunk_preview_module = documents_module.document_chunk_preview


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _build_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, uuid.UUID, str]:
    tenant_id = uuid.uuid4()
    account_id = "test-account"

    monkeypatch.setattr(
        chunk_preview_module.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(chunk_preview_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(chunk_preview_module.settings, "MAX_FILE_SIZE", 1024 * 1024, raising=False)
    monkeypatch.setattr(chunk_preview_module.settings, "PREVIEW_PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(chunk_preview_module.settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(chunk_preview_module.settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 8, raising=False)
    monkeypatch.setattr(chunk_preview_module.settings, "PREVIEW_PARSE_CACHE_VERSION", "test-v1", raising=False)
    monkeypatch.setattr(chunk_preview_module, "_materialize_extracted_images_for_preview", lambda docs, tenant_id: docs, raising=True)
    monkeypatch.setattr(chunk_preview_module, "_materialize_local_images_for_preview", lambda docs, tenant_id: docs, raising=True)

    def _parse_with_provenance(*_args, **_kwargs):  # noqa: ANN202
        return [Document(page_content="alpha beta", metadata={"page": 1, "page_index": 0})], "stub-parser", None

    monkeypatch.setattr(
        chunk_preview_module.parser_factory,
        "parse_with_provenance",
        _parse_with_provenance,
        raising=True,
    )

    preview_parse_cache.clear()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id
    app.include_router(chunk_preview_module.router, prefix="/api/v1/documents")
    return TestClient(app), tenant_id, account_id


def test_chunk_preview_upload_omits_original_text_when_max_chars_zero(monkeypatch, tmp_path: Path) -> None:
    client, _tenant_id, _account_id = _build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/v1/documents/chunk-preview",
        params={
            "chunk_size": "100",
            "chunk_overlap": "0",
            "include_chunks": "false",
            "include_original_text": "true",
            "original_text_max_chars": "0",
        },
        data={
            "chunk_strategy": "langchain_recursive",
            "parser_backend": "auto",
        },
        files={"file": ("doc.md", b"alpha beta", "text/markdown")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["original_text"] is None
    assert payload["original_text_included"] is False
    assert payload["original_text_truncated"] is False


def test_chunk_preview_by_sha_matches_upload_when_max_chars_zero(monkeypatch, tmp_path: Path) -> None:
    client, tenant_id, account_id = _build_client(monkeypatch, tmp_path)
    sha = hashlib.sha256(b"alpha beta").hexdigest()
    cache_key = f"parse:{tenant_id}:{account_id}:{sha}:.md:auto:test-v1"
    preview_parse_cache.set(
        cache_key,
        ParseCacheEntry(
            created_at_monotonic=time.monotonic(),
            created_at_wall=time.time(),
            file_sha256=sha,
            parser_backend="auto",
            resolved_backend="stub-parser",
            documents=[{"page_content": "alpha beta", "metadata": {"page": 1, "page_index": 0}}],
            total_chars=len("alpha beta"),
        ),
        ttl_sec=60,
        max_entries=8,
    )

    response = client.post(
        "/api/v1/documents/chunk-preview/by-sha",
        params={
            "chunk_size": "100",
            "chunk_overlap": "0",
            "include_chunks": "false",
            "include_original_text": "true",
            "original_text_max_chars": "0",
        },
        data={
            "file_sha256": sha,
            "file_type": "md",
            "filename": "doc.md",
            "chunk_strategy": "langchain_recursive",
            "parser_backend": "auto",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["original_text"] is None
    assert payload["original_text_included"] is False
    assert payload["original_text_truncated"] is False
