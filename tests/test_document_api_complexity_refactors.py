import importlib
import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from langchain_core.documents import Document

from app.api.schemas.document import DocumentParsePreview, DocumentStatus
from app.api.v1 import document_preview, document_processing
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError


class _Request:
    async def is_disconnected(self) -> bool:
        return False


class _Query:
    def __init__(self, document, *, chunk_exists: object = None) -> None:  # noqa: ANN001
        self._document = document
        self._chunk_exists = chunk_exists
        self._mode = "document"

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        if self._mode == "chunk_exists":
            return self._chunk_exists
        return self._document

    def limit(self, _value):  # noqa: ANN001, ANN201
        return self

    def all(self) -> list[tuple]:
        return []


class _DB:
    def __init__(self, document, *, chunk_exists: object = None) -> None:  # noqa: ANN001
        self.document = document
        self.chunk_exists = chunk_exists
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):  # noqa: ANN001, ANN201
        query = _Query(self.document, chunk_exists=self.chunk_exists)
        if model is not document_processing.DBDocument:
            query._mode = "chunk_exists"
        return query

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        self.rollbacks += 1


def _upload_file(name: str, content: bytes = b"payload") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content))


def _preview_form(**overrides: object) -> document_preview.PreviewDocumentFormFields:
    form = document_preview.PreviewDocumentFormFields(
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        dataset_id=None,
        pipeline=None,
    )
    for key, value in overrides.items():
        setattr(form, key, value)
    return form


def _gov_form(**overrides: object) -> document_preview.PreviewDocumentGovernanceOverridesFormFields:
    form = document_preview.PreviewDocumentGovernanceOverridesFormFields(
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
        setattr(form, key, value)
    return form


def _governance_effective(**overrides: object) -> SimpleNamespace:
    values = {
        "governance_enabled": False,
        "governance_remove_toc_lines": False,
        "governance_remove_noise_lines": False,
        "governance_unwrap_lines": False,
        "governance_remove_common_lines": False,
        "governance_remove_boilerplate": False,
        "governance_remove_images": "none",
        "governance_extract_frontmatter": False,
        "governance_strip_frontmatter": False,
        "governance_detect_language": False,
        "governance_language_min_chars": 0,
        "governance_normalize_urls": False,
        "governance_normalize_urls_strip_tracking": False,
        "governance_drop_duplicate_paragraphs": False,
        "governance_drop_duplicate_paragraphs_min_occurrences": 0,
        "governance_drop_duplicate_paragraphs_min_chars": 0,
        "governance_drop_duplicate_paragraphs_max_chars": 0,
        "governance_trim_references": False,
        "governance_extract_keywords": False,
        "governance_keywords_provider": "auto",
        "governance_keywords_top_k": 0,
        "governance_keywords_max_chars": 0,
        "governance_normalize_tables": False,
        "governance_strip_code_line_numbers": False,
        "governance_pii_anonymize": False,
        "governance_pii_mode": "mask",
        "governance_pii_mask": "***",
        "governance_secrets_redact": False,
        "governance_secrets_mode": "mask",
        "governance_secrets_mask": "***",
        "governance_max_blank_lines": 0,
        "governance_drop_outline_only": False,
        "governance_drop_outline_min_content_chars": 0,
        "governance_drop_outline_max_heading_ratio": 0.0,
        "governance_drop_low_density": False,
        "governance_drop_low_density_threshold": 0.0,
        "governance_unwrap_max_line_length": 0,
        "governance_noise_min_chars": 0,
        "governance_noise_ratio_threshold": 0.0,
        "governance_common_lines_min_docs": 0,
        "governance_common_lines_min_ratio": 0.0,
        "governance_regex_rules": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _make_retry_document(
    *,
    status: str = "failed",
    file_path: str,
    tenant_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    dataset_id: uuid.UUID | None = None,
    metadata: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        dataset_id=dataset_id or uuid.uuid4(),
        file_path=file_path,
        file_type="txt",
        filename="retry.txt",
        status=status,
        processing_progress=100 if status == "completed" else 0,
        current_stage=status,
        failed_stage="parse" if status == "failed" else None,
        error_code="boom" if status == "failed" else None,
        next_retry_at=None,
        error_message="old-error" if status == "failed" else None,
        processing_attempts=2,
        doc_metadata=dict(metadata or {}),
        chunk_count=5,
        total_characters=123,
    )


@pytest.mark.asyncio
async def test_preview_document_inline_path_preserves_auth_pipeline_governance_and_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = importlib.import_module("app.api.v1.documents")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    upload_root = tmp_path / "uploads"
    artifact_dir = upload_root / str(tenant_id) / ".magicpdf" / "artifact"
    artifact_dir.mkdir(parents=True)
    call_order: list[str] = []
    analytics_inputs: list[dict[str, object]] = []
    pipeline_calls: list[dict[str, object]] = []
    governance_calls: list[dict[str, object]] = []

    async def _save_upload(file, destination, *, max_bytes):  # noqa: ANN001, ANN202
        call_order.append("save")
        destination.write_bytes(b"preview")
        assert max_bytes == 512
        assert file.filename == "sanitized.md"
        return 7

    def _analytics(**kwargs):  # noqa: ANN003
        call_order.append(f"analytics:{len(analytics_inputs)}")
        analytics_inputs.append(kwargs)
        char_count = len(str(kwargs["markdown"]))
        return SimpleNamespace(
            to_dict=lambda: {
                "char_count": char_count,
                "line_count": 1,
                "heading_count": 0,
                "page_count": 1,
                "table_count": 0,
                "image_count": 0,
                "block_count": 1,
                "language": "en",
                "language_confidence": 1.0,
                "cjk_chars": 0,
                "latin_chars": char_count,
            }
        )

    def _resolve_pipeline_effective(**kwargs):  # noqa: ANN003
        call_order.append("resolve_pipeline_effective")
        pipeline_calls.append(kwargs)
        return _governance_effective(
            governance_enabled=True,
            governance_detect_language=True,
            governance_language_min_chars=4,
            governance_remove_noise_lines=True,
            governance_unwrap_lines=True,
            governance_regex_rules=[{"pattern": "raw", "repl": "clean"}],
        )

    def _clean_documents(documents, **kwargs):  # noqa: ANN001, ANN003
        call_order.append("clean_documents")
        governance_calls.append(kwargs)
        assert documents[0].page_content == "raw inline text"
        return (
            [
                Document(
                    page_content="clean inline text",
                    metadata={"page": 3, "cleaned": True},
                )
            ],
            {"removed": 1},
        )

    monkeypatch.setattr(document_preview.settings, "UPLOAD_DIR", str(upload_root), raising=False)
    monkeypatch.setattr(document_preview.settings, "MAX_FILE_SIZE", 512, raising=False)
    monkeypatch.setattr(document_preview.settings, "MAGIC_PDF_KEEP_ARTIFACTS", False, raising=False)
    monkeypatch.setattr(document_preview.settings, "TASK_JOB_TIMEOUT_SEC", 321, raising=False)
    monkeypatch.setattr(document_preview.settings, "ALLOWED_EXTENSIONS", ".md,.pdf", raising=False)
    monkeypatch.setattr(
        document_preview.DatasetService,
        "ensure_member",
        lambda *_args: call_order.append("ensure_member"),
        raising=True,
    )
    monkeypatch.setattr(
        document_preview.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(dataset_metadata={"dataset": "meta"}),
        raising=True,
    )
    monkeypatch.setattr(
        document_preview.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: call_order.append("assert_dataset_readable"),
        raising=True,
    )
    monkeypatch.setattr(document_preview, "save_upload_file", _save_upload, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_sanitize_filename",
        lambda name: call_order.append("sanitize") or "sanitized.md",
        raising=True,
    )
    monkeypatch.setattr(document_preview.parser_factory, "PLAIN_TEXT_EXTENSIONS", {".md", ".txt"}, raising=False)
    monkeypatch.setattr(
        document_preview.parser_factory,
        "resolve_backend",
        lambda file_ext, backend: call_order.append("resolve_backend") or "inline-backend",
        raising=True,
    )
    monkeypatch.setattr(
        document_preview.parser_factory,
        "parse_with_provenance",
        lambda *_args, **_kwargs: (
            [
                Document(
                    page_content="raw inline text",
                    metadata={"page": 2, "artifact_dir": str(artifact_dir), "nested": {"label": "a\x00b"}},
                    id="seg-1",
                )
            ],
            "inline-backend",
            {"stage": "inline"},
        ),
        raising=True,
    )
    monkeypatch.setattr(document_preview, "resolve_pipeline_effective", _resolve_pipeline_effective, raising=True)
    monkeypatch.setattr(document_preview, "compute_document_analytics", _analytics, raising=True)
    monkeypatch.setattr(
        document_preview,
        "build_governance_rules",
        lambda rules: call_order.append("build_rules") or rules,
        raising=True,
    )
    monkeypatch.setattr(documents_module.governance_processor, "clean_documents", _clean_documents, raising=True)

    result = await document_preview.preview_document(
        request=_Request(),
        file=_upload_file("notes.md"),
        form=_preview_form(
            dataset_id=str(dataset_id),
            pipeline='{"governance_enabled": true}',
        ),
        gov_overrides_form=_gov_form(
            governance_enabled=True,
            governance_remove_noise_lines=True,
        ),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=object(),
    )

    assert isinstance(result, DocumentParsePreview)
    assert result.model_dump(mode="json") == {
        "filename": "sanitized.md",
        "file_type": "md",
        "file_size": 7,
        "segments": [
            {
                "index": 0,
                "content": "clean inline text",
                "page_number": 3,
                "metadata": {"page": 3, "cleaned": True},
            }
        ],
        "parser_backend": "inline-backend",
        "analytics": {
            "raw": {
                "char_count": 15,
                "line_count": 1,
                "heading_count": 0,
                "page_count": 1,
                "table_count": 0,
                "image_count": 0,
                "block_count": 1,
                "language": "en",
                "language_confidence": 1.0,
                "cjk_chars": 0,
                "latin_chars": 15,
            },
            "cleaned": {
                "char_count": 17,
                "line_count": 1,
                "heading_count": 0,
                "page_count": 1,
                "table_count": 0,
                "image_count": 0,
                "block_count": 1,
                "language": "en",
                "language_confidence": 1.0,
                "cjk_chars": 0,
                "latin_chars": 17,
            },
        },
    }
    positions = {name: index for index, name in enumerate(call_order)}
    assert positions["ensure_member"] == 0
    assert positions["sanitize"] < positions["save"] < positions["resolve_backend"]
    assert positions["assert_dataset_readable"] < positions["resolve_pipeline_effective"]
    assert positions["analytics:0"] < positions["build_rules"] < positions["clean_documents"]
    assert positions["clean_documents"] < positions["analytics:1"]
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["dataset_metadata"] == {"dataset": "meta"}
    assert pipeline_calls[0]["document_metadata"] == {}
    assert pipeline_calls[0]["request_overrides"].governance_enabled is True
    assert pipeline_calls[0]["request_overrides"].governance_remove_noise_lines is True
    assert analytics_inputs[0]["markdown"] == "raw inline text"
    assert analytics_inputs[1]["markdown"] == "clean inline text"
    assert len(governance_calls) == 1
    assert governance_calls[0]["rules"] == [{"pattern": "raw", "repl": "clean"}]
    assert governance_calls[0]["remove_noise_lines"] is True
    assert governance_calls[0]["unwrap_lines"] is True
    assert governance_calls[0]["detect_language"] is True
    assert not artifact_dir.exists()


@pytest.mark.asyncio
async def test_preview_document_subprocess_path_preserves_payload_and_cleanup_safety(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = importlib.import_module("app.api.v1.documents")
    tenant_id = uuid.uuid4()
    upload_root = tmp_path / "uploads"
    safe_inside_without_marker = upload_root / str(tenant_id) / "other" / "artifact"
    safe_inside_without_marker.mkdir(parents=True)
    unsafe_outside_tenant = tmp_path / "outside" / ".magicpdf" / "artifact"
    unsafe_outside_tenant.mkdir(parents=True)
    worker_calls: list[dict[str, object]] = []

    async def _save_upload(_file, destination, *, max_bytes):  # noqa: ANN001, ANN202
        destination.write_bytes(b"pdf")
        assert max_bytes == 256
        return 11

    async def _run_subprocess_worker(**kwargs):  # noqa: ANN003, ANN202
        worker_calls.append(kwargs)
        return {
            "resolved_backend": "mineru",
            "pdf_quality": {"score": 0.9},
            "documents": [
                {
                    "page_content": "page one",
                    "metadata": {"page": 1, "artifact_dir": str(unsafe_outside_tenant)},
                    "id": "seg-1",
                },
                {
                    "page_content": "page two",
                    "metadata": {"page": 2, "artifact_dir": str(safe_inside_without_marker)},
                    "id": "seg-2",
                },
            ],
        }

    def _analytics(**kwargs):  # noqa: ANN003
        return SimpleNamespace(
            to_dict=lambda: {
                "char_count": len(str(kwargs["markdown"])),
                "line_count": 2,
                "heading_count": 0,
                "page_count": 2,
                "table_count": 0,
                "image_count": 0,
                "block_count": 2,
                "language": None,
                "language_confidence": None,
                "cjk_chars": None,
                "latin_chars": None,
            }
        )

    monkeypatch.setattr(document_preview.settings, "UPLOAD_DIR", str(upload_root), raising=False)
    monkeypatch.setattr(document_preview.settings, "MAX_FILE_SIZE", 256, raising=False)
    monkeypatch.setattr(document_preview.settings, "MAGIC_PDF_KEEP_ARTIFACTS", False, raising=False)
    monkeypatch.setattr(document_preview.settings, "TASK_JOB_TIMEOUT_SEC", 45, raising=False)
    monkeypatch.setattr(document_preview.settings, "ALLOWED_EXTENSIONS", ".pdf", raising=False)
    monkeypatch.setattr(document_preview.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(document_preview.DatasetService, "get_dataset", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(document_preview, "save_upload_file", _save_upload, raising=True)
    monkeypatch.setattr(documents_module, "_sanitize_filename", lambda _name: "sanitized.pdf", raising=True)
    monkeypatch.setattr(document_preview, "compute_document_analytics", _analytics, raising=True)
    monkeypatch.setattr(
        document_preview,
        "resolve_pipeline_effective",
        lambda **_kwargs: _governance_effective(),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "run_subprocess_worker", _run_subprocess_worker, raising=True)

    result = await document_preview.preview_document(
        request=_Request(),
        file=_upload_file("scan.pdf"),
        form=_preview_form(),
        gov_overrides_form=_gov_form(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=object(),
    )

    assert result.model_dump(mode="json") == {
        "filename": "sanitized.pdf",
        "file_type": "pdf",
        "file_size": 11,
        "segments": [
            {
                "index": 0,
                "content": "page one",
                "page_number": 1,
                "metadata": {"page": 1, "artifact_dir": str(unsafe_outside_tenant)},
            },
            {
                "index": 1,
                "content": "page two",
                "page_number": 2,
                "metadata": {"page": 2, "artifact_dir": str(safe_inside_without_marker)},
            },
        ],
        "parser_backend": "mineru",
        "analytics": {
            "raw": {
                "char_count": 18,
                "line_count": 2,
                "heading_count": 0,
                "page_count": 2,
                "table_count": 0,
                "image_count": 0,
                "block_count": 2,
                "language": None,
                "language_confidence": None,
                "cjk_chars": None,
                "latin_chars": None,
            },
            "cleaned": {
                "char_count": 18,
                "line_count": 2,
                "heading_count": 0,
                "page_count": 2,
                "table_count": 0,
                "image_count": 0,
                "block_count": 2,
                "language": None,
                "language_confidence": None,
                "cjk_chars": None,
                "latin_chars": None,
            },
        },
    }
    assert len(worker_calls) == 1
    assert worker_calls[0]["tenant_id"] == tenant_id
    assert worker_calls[0]["payload"] == {
        "action": "parse_documents",
        "tenant_id": str(tenant_id),
        "account_id": "acct-1",
        "file_path": worker_calls[0]["payload"]["file_path"],
        "parser_backend": "auto",
        "mode": "preview",
    }
    assert str(worker_calls[0]["payload"]["file_path"]).endswith("/input.pdf")
    assert str(worker_calls[0]["payload"]["file_path"]).startswith(str(upload_root / str(tenant_id) / "preview"))
    assert callable(worker_calls[0]["disconnect_check"])
    assert worker_calls[0]["timeout_sec"] == 45.0
    assert safe_inside_without_marker.exists()
    assert unsafe_outside_tenant.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "production", "status_code", "detail"),
    [
        (SubprocessCancelled(), False, 499, "Client closed request"),
        (
            SubprocessWorkerError("bad input", details={"type": "ValueError"}),
            False,
            400,
            "Invalid input: bad input",
        ),
        (
            SubprocessWorkerError("backend crashed", details={"type": "RuntimeError"}),
            False,
            500,
            "Failed to parse document: backend crashed",
        ),
        (
            SubprocessWorkerError("backend crashed", details={"type": "RuntimeError"}),
            True,
            500,
            "Failed to parse document",
        ),
    ],
)
async def test_preview_document_maps_worker_errors_without_leaking_production_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raised: Exception,
    production: bool,
    status_code: int,
    detail: str,
) -> None:
    documents_module = importlib.import_module("app.api.v1.documents")
    tenant_id = uuid.uuid4()
    upload_root = tmp_path / "uploads"

    async def _save_upload(_file, destination, *, max_bytes):  # noqa: ANN001, ANN202
        destination.write_bytes(b"pdf")
        assert max_bytes == 128
        return 3

    async def _raise(**_kwargs):  # noqa: ANN003, ANN202
        raise raised

    monkeypatch.setattr(document_preview.settings, "UPLOAD_DIR", str(upload_root), raising=False)
    monkeypatch.setattr(document_preview.settings, "MAX_FILE_SIZE", 128, raising=False)
    monkeypatch.setattr(document_preview.settings, "ALLOWED_EXTENSIONS", ".pdf", raising=False)
    monkeypatch.setattr(document_preview.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(document_preview, "save_upload_file", _save_upload, raising=True)
    monkeypatch.setattr(documents_module, "_sanitize_filename", lambda _name: "sanitized.pdf", raising=True)
    monkeypatch.setattr(documents_module, "run_subprocess_worker", _raise, raising=True)
    monkeypatch.setattr(document_preview, "is_production_env", lambda: production, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await document_preview.preview_document(
            request=_Request(),
            file=_upload_file("scan.pdf"),
            form=_preview_form(),
            gov_overrides_form=_gov_form(),
            tenant_id=tenant_id,
            account_id="acct-1",
            db=object(),
        )

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail == detail


@pytest.mark.asyncio
async def test_retry_document_processing_enforces_membership_then_write_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = document_processing._documents_module()
    source = tmp_path / "retry.txt"
    source.write_text("hello", encoding="utf-8")
    document = _make_retry_document(file_path=str(source))
    db = _DB(document)
    call_order: list[str] = []

    def _ensure_member(*_args, **_kwargs):  # noqa: ANN002, ANN003
        call_order.append("ensure_member")

    def _deny(*_args, **_kwargs):  # noqa: ANN002, ANN003
        call_order.append("assert_writable")
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", _ensure_member, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_writable_for_lifecycle", _deny, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await document_processing.retry_document_processing(
            document_id=document.id,
            background_tasks=BackgroundTasks(),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "denied"
    assert call_order == ["ensure_member", "assert_writable"]
    assert db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "file_path", "force", "expected_detail"),
    [
        ("pending", "uploads/retry.txt", False, "Cannot retry a pending document"),
        ("completed", "uploads/retry.txt", False, "Document is already completed (use force=true to reprocess)"),
        ("failed", "manual://doc", False, "Document file is not reprocessable"),
    ],
)
async def test_retry_document_processing_rejects_non_retryable_states(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    file_path: str,
    force: bool,
    expected_detail: str,
) -> None:
    documents_module = document_processing._documents_module()
    document = _make_retry_document(
        status=status,
        file_path=file_path,
        metadata={"active_pipeline_ready": False},
    )
    db = _DB(document)

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_is_reprocessable_pending_document", lambda _document: False, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await document_processing.retry_document_processing(
            document_id=document.id,
            background_tasks=BackgroundTasks(),
            force=force,
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == expected_detail


@pytest.mark.asyncio
async def test_retry_document_processing_skip_if_unchanged_is_idempotent_and_returns_exact_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = document_processing._documents_module()
    source = tmp_path / "retry.txt"
    source.write_text("hello", encoding="utf-8")
    document = _make_retry_document(
        status="completed",
        file_path=str(source),
        metadata={
            "content_sha256": "sha-1",
            "file_sha256": "sha-1",
            "pipeline_hash": "stable-pipeline",
            "active_pipeline_hash": "stable-pipeline",
            "active_pipeline_ready": True,
        },
    )
    document.current_stage = "completed"
    document.error_code = None
    document.error_message = None
    db = _DB(document, chunk_exists=True)
    audit_events: list[dict[str, object]] = []

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_compute_pipeline_hash", lambda _meta: "stable-pipeline", raising=True)
    monkeypatch.setattr(
        documents_module,
        "audit_log_event",
        lambda *_args, **kwargs: audit_events.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        documents_module,
        "enqueue_document_processing",
        lambda **_kwargs: pytest.fail("enqueue should not be called for unchanged retry"),
        raising=True,
    )

    result = await document_processing.retry_document_processing(
        document_id=document.id,
        background_tasks=BackgroundTasks(),
        force=True,
        skip_if_unchanged=True,
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert DocumentStatus.model_validate(result).model_dump(mode="json") == {
        "id": str(document.id),
        "status": "completed",
        "processing_progress": 100,
        "current_stage": "completed",
        "failed_stage": None,
        "error_code": None,
        "processing_attempts": 2,
        "next_retry_at": None,
        "error_message": None,
    }
    assert audit_events == [
        {
            "tenant_id": document.tenant_id,
            "actor_id": "acct-1",
            "action": "document.retry.skipped",
            "resource_type": "document",
            "resource_id": str(document.id),
            "details": {"reason": "unchanged", "pipeline_hash": "stable-pipeline"},
        }
    ]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_retry_document_processing_preserves_existing_versions_and_stable_job_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = document_processing._documents_module()
    source = tmp_path / "retry.txt"
    source.write_text("hello", encoding="utf-8")
    document = _make_retry_document(
        status="failed",
        file_path=str(source),
        metadata={
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline_hash": "active-pipeline",
            "active_pipeline_hash": "active-pipeline",
            "active_pipeline_ready": True,
        },
    )
    db = _DB(document)
    enqueue_calls: list[dict[str, object]] = []
    reconcile_calls: list[dict[str, object]] = []

    async def _enqueue(**kwargs):  # noqa: ANN003, ANN202
        enqueue_calls.append(kwargs)
        return "task-123"

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_compute_pipeline_hash", lambda _meta: "next-pipeline", raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _enqueue, raising=True)
    monkeypatch.setattr(
        documents_module,
        "reconcile_document_index_channels",
        lambda *_args, **kwargs: reconcile_calls.append(kwargs),
        raising=True,
    )

    result = await document_processing.retry_document_processing(
        document_id=document.id,
        background_tasks=BackgroundTasks(),
        force=True,
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert DocumentStatus.model_validate(result).model_dump(mode="json") == {
        "id": str(document.id),
        "status": "pending",
        "processing_progress": 0,
        "current_stage": "queued",
        "failed_stage": None,
        "error_code": None,
        "processing_attempts": 2,
        "next_retry_at": None,
        "error_message": None,
    }
    assert document.doc_metadata["retry_cleanup"] == {
        "version": "1",
        "force": True,
        "pipeline_hash": "next-pipeline",
        "scope": "pipeline",
        "doc_pipeline_key": f"{document.id}:next-pipeline",
    }
    assert document.doc_metadata["task_id"] == "task-123"
    assert enqueue_calls == [
        {
            "tenant_id": document.tenant_id,
            "document_id": document.id,
            "requested_by": "acct-1",
            "job_id": f"doc:{document.tenant_id}:{document.id}:next-pipeline",
        }
    ]
    assert len(reconcile_calls) == 1
    assert reconcile_calls[0]["pipeline_hash"] == "next-pipeline"
    assert reconcile_calls[0]["reset_enabled_to_pending"] is True
    assert reconcile_calls[0]["commit"] is True


@pytest.mark.asyncio
async def test_retry_document_processing_object_store_fallback_cleans_temp_file_after_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = document_processing._documents_module()
    tenant_id = uuid.uuid4()
    document = _make_retry_document(
        status="failed",
        tenant_id=tenant_id,
        file_path="s3://bucket/retry.txt",
        metadata={
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline_hash": "pipeline-a",
            "active_pipeline_hash": "pipeline-a",
            "active_pipeline_ready": True,
        },
    )
    db = _DB(document)
    background_tasks = BackgroundTasks()
    download_calls: list[dict[str, object]] = []
    observed_paths: list[Path] = []

    class _Store:
        def stat_object(self, *, object_name: str) -> None:
            assert object_name == "tenant/retry.txt"

        def download_object_to_path(self, *, object_name: str, destination: Path, max_bytes: int) -> None:
            download_calls.append(
                {
                    "object_name": object_name,
                    "destination": destination,
                    "max_bytes": max_bytes,
                }
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("downloaded", encoding="utf-8")

    async def _no_task(**_kwargs):  # noqa: ANN003, ANN202
        return None

    async def _process(*, file_path: Path, **_kwargs):  # noqa: ANN003, ANN202
        observed_paths.append(file_path)
        assert file_path.exists()
        raise RuntimeError("processing failed")

    monkeypatch.setattr(documents_module.settings, "UPLOAD_DIR", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(documents_module.settings, "MAX_FILE_SIZE", 1024, raising=False)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(documents_module, "is_object_storage_uri", lambda _raw: True, raising=True)
    monkeypatch.setattr(
        documents_module,
        "resolve_document_object_reference",
        lambda *_args, **_kwargs: (_Store(), SimpleNamespace(object_name="tenant/retry.txt")),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _no_task, raising=True)
    monkeypatch.setattr(documents_module, "_task_queue_required", lambda: False, raising=True)
    monkeypatch.setattr(documents_module, "run_document_processing_limited", _process, raising=True)
    monkeypatch.setattr(
        documents_module,
        "reconcile_document_index_channels",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    result = await document_processing.retry_document_processing(
        document_id=document.id,
        background_tasks=background_tasks,
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert DocumentStatus.model_validate(result).model_dump(mode="json") == {
        "id": str(document.id),
        "status": "pending",
        "processing_progress": 0,
        "current_stage": "queued",
        "failed_stage": None,
        "error_code": None,
        "processing_attempts": 2,
        "next_retry_at": None,
        "error_message": None,
    }
    assert len(background_tasks.tasks) == 1

    with pytest.raises(RuntimeError, match="processing failed"):
        await background_tasks()

    assert len(download_calls) == 1
    assert observed_paths
    assert not observed_paths[0].exists()
