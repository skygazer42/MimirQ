import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from langchain_core.documents import Document
from starlette.requests import Request

from app.api.v1 import documents as documents_module
from app.api.v1 import parsing as parsing_module
from app.main import _expand_dev_cors_origins, app, lifespan
from app.parsing.processors.support import recovery as recovery_module
from app.services.preview_cache import ParseCacheEntry

preview_module = documents_module.document_chunk_preview


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


def _preview_params(**overrides: object) -> preview_module.ChunkPreviewRequestFields:
    params = preview_module.ChunkPreviewRequestFields(
        chunk_size=1000,
        chunk_overlap=200,
        include_original_text=True,
        include_review_signals=False,
        include_chunks=True,
        original_text_max_chars=100000,
        max_chunks=0,
        use_parse_cache=True,
        parser_backend="basic",
        chunk_strategy="langchain_recursive",
        child_ratio=None,
        min_child_size=None,
        separator_preset=None,
        separator=None,
        keep_separator=None,
        separator_max_chunk_size=None,
        dataset_id=None,
        pipeline=None,
        governance_enabled=None,
        governance_remove_toc_lines=None,
        governance_remove_noise_lines=None,
        governance_unwrap_lines=None,
        governance_remove_common_lines=None,
        governance_unwrap_max_line_length=None,
        governance_noise_min_chars=None,
        governance_noise_ratio_threshold=None,
        governance_common_lines_min_docs=None,
        governance_common_lines_min_ratio=None,
    )
    for key, value in overrides.items():
        setattr(params, key, value)
    return params


def test_expand_dev_cors_origins_adds_local_aliases_without_touching_remote_origins() -> None:
    expanded = _expand_dev_cors_origins(["http://localhost:3000", "https://example.com"])

    assert "https://example.com" in expanded
    assert "http://localhost:3000" in expanded
    assert "http://127.0.0.1:3000" in expanded
    assert "http://0.0.0.0:3000" in expanded
    assert "http://localhost:3001" in expanded
    assert "http://127.0.0.1:3100" in expanded


@pytest.mark.asyncio
async def test_lifespan_preserves_startup_and_shutdown_order(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    events: list[str] = []

    class _DB:
        def close(self) -> None:
            events.append("db.close")

    async def _init_queue() -> None:
        events.append("init_queue")

    async def _close_http() -> None:
        events.append("close_http")

    async def _close_queue() -> None:
        events.append("close_queue")

    fake_dify = types.SimpleNamespace(
        start_dify_external_knowledge_warmup=lambda: events.append("dify_warmup"),
    )

    monkeypatch.setattr(main_module.settings, "UPLOAD_DIR", "/tmp/mimirq-tests", raising=False)
    monkeypatch.setattr(main_module.settings, "TABLE_STORE_DIR", None, raising=False)
    monkeypatch.setattr(main_module.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(main_module.settings, "DB_RUNTIME_MIGRATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(main_module.settings, "DB_CREATE_ALL_ON_STARTUP", True, raising=False)
    monkeypatch.setattr(main_module.settings, "ENABLE_METRICS_LOG", False, raising=False)
    monkeypatch.setattr(main_module.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(main_module.settings, "LANGSMITH_TRACING_ENABLED", False, raising=False)
    monkeypatch.setattr(main_module.settings, "PROMETHEUS_ENABLED", False, raising=False)
    monkeypatch.setattr(main_module.settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(main_module.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(main_module, "apply_runtime_migrations", lambda _engine: events.append("migrate"), raising=True)
    monkeypatch.setattr(
        main_module.Base.metadata,
        "create_all",
        lambda *, bind: events.append("create_all"),
        raising=True,
    )
    monkeypatch.setattr(main_module, "SessionLocal", lambda: _DB(), raising=True)
    monkeypatch.setattr(
        main_module,
        "bootstrap_initial_admin_if_configured",
        lambda _db: events.append("bootstrap") or False,
        raising=True,
    )
    monkeypatch.setattr(main_module, "init_queue", _init_queue, raising=True)
    monkeypatch.setattr(
        main_module, "_warmup_retrieval_tokenizer", lambda: events.append("warmup_tokenizer"), raising=True
    )
    monkeypatch.setattr(main_module, "_start_runtime_warmup", lambda: events.append("warmup_runtime"), raising=True)
    monkeypatch.setattr(main_module, "close_http_client_pool", _close_http, raising=True)
    monkeypatch.setattr(main_module, "close_queue", _close_queue, raising=True)
    monkeypatch.setattr(main_module.engine, "dispose", lambda: events.append("dispose"), raising=True)
    monkeypatch.setattr(main_module, "shutdown_otel", lambda: events.append("shutdown_otel"), raising=True)
    monkeypatch.setitem(sys.modules, "app.api.v1.integrations_dify", fake_dify)

    async with lifespan(app):
        events.append("yield")

    assert events == [
        "migrate",
        "create_all",
        "migrate",
        "bootstrap",
        "db.close",
        "init_queue",
        "warmup_tokenizer",
        "warmup_runtime",
        "dify_warmup",
        "yield",
        "close_http",
        "close_queue",
        "dispose",
        "shutdown_otel",
    ]


def test_build_pdf_fallback_candidates_preserves_order_and_basic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parsing_module.settings, "MINERU_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "MINERU_API_TOKEN", "token", raising=False)
    monkeypatch.setattr(parsing_module.settings, "MINERU_LOCAL_SERVER_URL", "", raising=False)
    monkeypatch.setattr(parsing_module.settings, "DEEPSEEK_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "SILICONFLOW_API_KEY", "key", raising=False)
    monkeypatch.setattr(parsing_module.settings, "QIANFAN_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "QIANFAN_OCR_API_URL", "https://ocr.example", raising=False)
    monkeypatch.setattr(parsing_module.settings, "ETL4LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "ETL4LLM_API_URL", "https://etl.example", raising=False)
    monkeypatch.setattr(parsing_module.settings, "DEEPDOC_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "DOCLING_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "MAGIC_PDF_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module.settings, "MARKITDOWN_ENABLED", True, raising=False)
    monkeypatch.setattr(parsing_module, "magicpdf_service_configured", lambda _url: True, raising=True)

    assert parsing_module._build_pdf_fallback_candidates() == [
        "mineru",
        "deepseek_ocr",
        "qianfan_ocr",
        "etl4llm",
        "deepdoc",
        "docling",
        "magicpdf",
        "markitdown",
        "basic",
    ]


class _PreviewPipeline:
    governance_enabled = False
    chunk_strategy_params: dict[str, object] = {}
    chunk_merge_small_min_chars = 0
    governance_regex_rules: list[object] = []

    def __getattr__(self, _name: str) -> object:
        return 0


def test_preview_chunking_by_sha_preserves_offsets_metadata_and_dataset_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    account_id = "acct-1"
    readable_calls: list[tuple[str, str]] = []

    class _Chunker:
        def split_documents(self, _documents: list[Document]) -> list[Document]:
            return [
                Document(
                    page_content="cde",
                    metadata={"page": 1, "page_index": 0, "start_char": 2, "end_char": 5, "origin": "first"},
                ),
                Document(
                    page_content="xy",
                    metadata={"page": 2, "page_index": 1, "start_char": 1, "end_char": 3, "origin": "second"},
                ),
            ]

    monkeypatch.setattr(preview_module.settings, "PREVIEW_PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(preview_module.settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(preview_module.settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 10, raising=False)
    monkeypatch.setattr(preview_module.settings, "PREVIEW_PARSE_CACHE_VERSION", "v1", raising=False)
    monkeypatch.setattr(preview_module.settings, "CHUNK_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(preview_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        preview_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, dataset_metadata={}),
        raising=True,
    )
    monkeypatch.setattr(
        preview_module.DatasetService,
        "assert_dataset_readable",
        lambda _db, _ds, acct: readable_calls.append(("readable", acct)),
        raising=True,
    )
    monkeypatch.setattr(
        preview_module,
        "resolve_pipeline_effective",
        lambda **_kwargs: _PreviewPipeline(),
        raising=True,
    )
    monkeypatch.setattr(preview_module.chunker_factory, "resolve_strategy", lambda _strategy: "langchain_recursive")
    monkeypatch.setattr(preview_module.chunker_factory, "get_chunker", lambda *_args, **_kwargs: _Chunker())
    monkeypatch.setattr(preview_module, "_ensure_preview_page_indices", lambda _documents: None, raising=True)
    monkeypatch.setattr(
        preview_module.preview_parse_cache,
        "get",
        lambda _key, *, ttl_sec: (
            ParseCacheEntry(
                created_at_monotonic=1.0,
                created_at_wall=1.0,
                file_sha256="a" * 64,
                parser_backend="basic",
                resolved_backend="basic",
                documents=[
                    {"page_content": "abcdef", "metadata": {"page": 1, "page_index": 0}, "id": "doc-1"},
                    {"page_content": "wxyz", "metadata": {"page": 2, "page_index": 1}, "id": "doc-2"},
                ],
                total_chars=10,
            ),
            17,
        ),
        raising=True,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.rag.chunking.quality_scorer",
        types.SimpleNamespace(
            score_chunk_semantic_quality=lambda content, *, tokens_est, prev_token_set: ({}, prev_token_set or set()),
        ),
    )

    response = preview_module.preview_chunking_by_sha(
        request=_request(),
        response=Response(),
        file_fields=preview_module.ChunkPreviewByShaFileFields(
            file_sha256="a" * 64,
            file_type="txt",
            filename="demo.txt",
            file_size=10,
        ),
        params=_preview_params(dataset_id=str(dataset_id)),
        tenant_id=tenant_id,
        account_id=account_id,
        db=object(),
    )

    assert readable_calls == [("readable", account_id)]
    assert response.parse_cache_hit is True
    assert response.parse_cache_age_ms == 17
    assert response.total_characters == len("abcdef\nwxyz")
    assert response.chunks[0].start_index == 2
    assert response.chunks[0].end_index == 5
    assert response.chunks[0].metadata["origin"] == "first"
    assert response.chunks[1].start_index == 8
    assert response.chunks[1].end_index == 10
    assert response.chunks[1].metadata["origin"] == "second"


@pytest.mark.asyncio
async def test_parse_workspace_document_requested_backend_fallback_preserves_502_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    source_path = tmp_path / "sample.pdf"
    source_path.write_bytes(b"%PDF-1.7")

    class _DB:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _obj: object) -> None:
            return None

        def query(self, _model: object) -> "_DB":
            return self

        def filter(self, *_args: object, **_kwargs: object) -> "_DB":
            return self

        def first(self) -> None:
            return None

    class _Request:
        async def is_disconnected(self) -> bool:
            return False

    doc = SimpleNamespace(
        id=document_id,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        file_path=str(source_path),
        file_type="pdf",
        status="pending",
        processing_progress=0,
        current_stage="queued",
        error_message=None,
        doc_metadata={"workspace": "parsing", "parser_backend_requested": "mineru"},
    )
    db = _DB()

    monkeypatch.setattr(
        parsing_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService, "assert_dataset_writable", lambda *_args, **_kwargs: None, raising=True
    )
    monkeypatch.setattr(parsing_module, "_get_workspace_document", lambda *_args, **_kwargs: doc, raising=True)
    monkeypatch.setattr(parsing_module, "is_object_storage_uri", lambda _path: False, raising=True)
    monkeypatch.setattr(parsing_module, "_assert_path_under_tenant_root", lambda **_kwargs: None, raising=True)
    monkeypatch.setattr(parsing_module.parser_factory, "resolve_backend", lambda _ext, backend: backend, raising=True)

    async def _run_subprocess_worker(**_kwargs: object) -> dict[str, object]:
        return {
            "resolved_backend": "docling",
            "documents": [{"page_content": "body", "metadata": {}, "id": "doc-1"}],
            "provenance": {"worker": "subprocess"},
        }

    monkeypatch.setattr(
        parsing_module,
        "run_subprocess_worker",
        _run_subprocess_worker,
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await parsing_module.parse_workspace_document(
            document_id=document_id,
            request=_Request(),
            parser_backend="mineru",
            image_caption_enabled=False,
            image_ocr_enabled=False,
            vlm_correction_enabled=None,
            tenant_id=tenant_id,
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == {
        "message": "Requested parser backend 'mineru' fell back to 'docling'",
        "diagnostics": {
            "requested_backend": "mineru",
            "resolved_backend": "docling",
            "provenance": {"worker": "subprocess"},
        },
    }
    assert doc.status == "failed"
    assert doc.current_stage == "failed"
    assert doc.error_message == "Requested parser backend 'mineru' fell back to 'docling'"
    assert doc.doc_metadata["parser_backend_requested"] == "mineru"
    assert doc.doc_metadata["parser_backend"] == "docling"
    assert doc.doc_metadata["parse_diagnostics"]["resolved_backend"] == "docling"
    assert db.commits == 2


def test_apply_pending_retry_cleanup_rejects_stale_pipeline_requests_without_mutation() -> None:
    document_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    db_document = SimpleNamespace(
        doc_metadata={
            "pipeline_hash": "current-hash",
            "retry_cleanup": {
                "version": "1",
                "scope": "pipeline",
                "pipeline_hash": "stale-hash",
                "doc_pipeline_key": f"{document_id}:stale-hash",
            },
        },
        chunk_count=9,
        total_characters=42,
    )

    status = recovery_module.apply_pending_retry_cleanup(
        SimpleNamespace(),
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        indexer_factory=lambda _db: None,
    )

    assert status == "invalid"
    assert db_document.doc_metadata["retry_cleanup"]["pipeline_hash"] == "stale-hash"
    assert db_document.chunk_count == 9
    assert db_document.total_characters == 42
