
import contextlib
import hashlib
import json
import re
import shutil
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    ChunkPreviewItem,
    ChunkPreviewParams,
    ChunkPreviewResponse,
    ChunkPreviewReviewSignals,
    ChunkPreviewStats,
)
from app.api.utils.upload import save_upload_file_with_hash
from app.api.v1.documents import (
    CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
    DATA_IMAGE_PREFIX,
    MINIO_IMAGE_REF_RE,
    POSITION_TAG_RE,
    PREVIEW_IMAGE_REF_RE,
    _coerce_bool_preview,
    _coerce_float_preview,
    _coerce_int_preview,
    _decode_escaped_input_preview,
    _filter_chunker_kwargs_for_strategy,
    _parse_pipeline_json,
    _sanitize_filename,
    _to_pipeline_options,
    logger,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.env import is_production_env
from app.core.token_utils import estimate_tokens, num_tokens_from_string
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.strategies.separator import SeparatorChunker
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services.dataset_service import DatasetService
from app.services.document_preview_utils import (
    _compute_chunk_coverage_metrics_from_ranges,
    _compute_chunk_length_histogram,
    _compute_chunk_preview_quality,
    _compute_chunk_preview_review_signals,
    _ensure_preview_page_indices,
    _materialize_extracted_images_for_preview,
    _materialize_local_images_for_preview,
    _merge_small_chunks_preview,
)
from app.services.pipeline_config import resolve_pipeline_effective
from app.services.preview_cache import ParseCacheEntry, preview_parse_cache, preview_parse_locks

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@dataclass
class ChunkPreviewRequestFields:
    chunk_size: int = 1000
    chunk_overlap: int = 200
    include_original_text: bool = True
    include_review_signals: bool = Query(False)
    include_chunks: bool = Query(True)
    original_text_max_chars: int = 100000
    max_chunks: int = 0
    use_parse_cache: bool = Query(True)

    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)

    child_ratio: float | None = Form(None)
    min_child_size: int | None = Form(None)
    separator_preset: str | None = Form(None)
    separator: str | None = Form(None)
    keep_separator: bool | None = Form(None)
    separator_max_chunk_size: int | None = Form(None)

    dataset_id: str | None = Form(None)
    pipeline: str | None = Form(None)
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)


@dataclass
class ChunkPreviewByShaFileFields:
    file_sha256: str = Form(...)
    file_type: str | None = Form(None)
    filename: str | None = Form(None)
    file_size: int | None = Form(None)


def _should_inline_preview_parse(file_ext: str) -> bool:
    if not bool(getattr(settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", True)):
        return False
    ext = str(file_ext or "").strip().lower()
    return ext == ".md" or ext in parser_factory.PLAIN_TEXT_EXTENSIONS


def _serialize_preview_parse_documents(documents: list[Document]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in documents or []:
        metadata = getattr(doc, "metadata", None) or {}
        try:
            safe_metadata = json.loads(json.dumps(metadata, ensure_ascii=False, default=str))
        except Exception:
            safe_metadata = {}
        out.append(
            {
                "page_content": str(getattr(doc, "page_content", "") or ""),
                "metadata": safe_metadata if isinstance(safe_metadata, dict) else {},
                "id": str(getattr(doc, "id", "") or "") or None,
            }
        )
    return out


def _should_include_original_preview_text(*, include_original_text: bool, original_text_max_chars: int) -> bool:
    return bool(include_original_text) and int(original_text_max_chars or 0) > 0


def _is_original_preview_text_truncated(
    *,
    include_original: bool,
    original_text_value: str | None,
    total_characters: int,
    original_text_max_chars: int,
) -> bool:
    return bool(
        include_original
        and original_text_value is None
        and total_characters > int(original_text_max_chars or 0)
    )


@router.post("/chunk-preview", response_model=ChunkPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def preview_chunking(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(...)],
    params: Annotated[ChunkPreviewRequestFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Chunk preview endpoint.

    Upload a file and preview chunking with the given parameters (no DB writes).
    Returns chunk results with positions for frontend highlighting.
    """
    from app.api.v1 import documents as documents_module

    DatasetService.ensure_member(db, tenant_id, account_id)
    file.filename = _sanitize_filename(file.filename)

    chunk_size = params.chunk_size
    chunk_overlap = params.chunk_overlap
    include_original_text = params.include_original_text
    include_review_signals = params.include_review_signals
    include_chunks = params.include_chunks
    original_text_max_chars = params.original_text_max_chars
    max_chunks = params.max_chunks
    use_parse_cache = params.use_parse_cache
    parser_backend = params.parser_backend
    chunk_strategy = params.chunk_strategy
    child_ratio = params.child_ratio
    min_child_size = params.min_child_size
    separator_preset = params.separator_preset
    separator = params.separator
    keep_separator = params.keep_separator
    separator_max_chunk_size = params.separator_max_chunk_size
    dataset_id = params.dataset_id
    pipeline = params.pipeline
    governance_enabled = params.governance_enabled
    governance_remove_toc_lines = params.governance_remove_toc_lines
    governance_remove_noise_lines = params.governance_remove_noise_lines
    governance_unwrap_lines = params.governance_unwrap_lines
    governance_remove_common_lines = params.governance_remove_common_lines
    governance_unwrap_max_line_length = params.governance_unwrap_max_line_length
    governance_noise_min_chars = params.governance_noise_min_chars
    governance_noise_ratio_threshold = params.governance_noise_ratio_threshold
    governance_common_lines_min_docs = params.governance_common_lines_min_docs
    governance_common_lines_min_ratio = params.governance_common_lines_min_ratio
    preview_started = time.perf_counter()
    parse_cache_hit = False
    parse_cache_age_ms: int | None = None
    file_sha256: str | None = None
    upload_duration_ms: int | None = None
    parse_duration_ms: int | None = 0
    governance_duration_ms: int = 0
    chunking_duration_ms: int = 0
    stats_duration_ms: int = 0

    try:
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    min_chunk_size = 50 if resolved_chunk_strategy == "langchain_token" else 100
    if chunk_size < min_chunk_size or chunk_size > 4000:
        raise HTTPException(status_code=400, detail=f"chunk_size must be between {min_chunk_size} and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if resolved_chunk_strategy != "separator" and chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL)

    effective_chunk_overlap = 0 if resolved_chunk_strategy == "separator" else chunk_overlap

    warnings_out: list[str] = []
    if resolved_chunk_strategy == "separator" and chunk_overlap != effective_chunk_overlap:
        warnings_out.append("separator strategy ignores chunk_overlap; using 0")

    if (child_ratio is not None or min_child_size is not None) and resolved_chunk_strategy != "parent_child":
        warnings_out.append(
            f"strategy params child_ratio/min_child_size ignored for chunk_strategy={resolved_chunk_strategy}"
        )
    chunker_kwargs: dict[str, Any] = {}
    separator_config: dict[str, Any] | None = None
    strategy_params_out: dict[str, Any] = {}

    if original_text_max_chars < 0 or original_text_max_chars > 2_000_000:
        raise HTTPException(status_code=400, detail="original_text_max_chars must be between 0 and 2000000")
    include_original = _should_include_original_preview_text(
        include_original_text=bool(include_original_text),
        original_text_max_chars=int(original_text_max_chars or 0),
    )

    if max_chunks < 0 or max_chunks > 20000:
        raise HTTPException(status_code=400, detail="max_chunks must be between 0 and 20000")

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)
    run_dir = upload_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"
    file_size: int = 0

    try:
        _upload_started = time.perf_counter()
        file_size, file_sha256 = await save_upload_file_with_hash(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)
        upload_duration_ms = int(max(0.0, (time.perf_counter() - _upload_started) * 1000.0))
        file_size = int(file_size or 0)
        if file_size <= 0:
            with contextlib.suppress(OSError):
                file_size = int(temp_path.stat().st_size)

        dataset_meta: dict = {}
        if dataset_id:
            try:
                ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
                DatasetService.assert_dataset_readable(db, ds, account_id)
                dataset_meta = dict(getattr(ds, "dataset_metadata", None) or {})
            except HTTPException:
                raise
            except Exception:
                dataset_meta = {}
        pipeline_options = _to_pipeline_options(
            pipeline=_parse_pipeline_json(pipeline),
            governance_enabled=governance_enabled,
            governance_remove_toc_lines=governance_remove_toc_lines,
            governance_remove_noise_lines=governance_remove_noise_lines,
            governance_unwrap_lines=governance_unwrap_lines,
            governance_remove_common_lines=governance_remove_common_lines,
            governance_unwrap_max_line_length=governance_unwrap_max_line_length,
            governance_noise_min_chars=governance_noise_min_chars,
            governance_noise_ratio_threshold=governance_noise_ratio_threshold,
            governance_common_lines_min_docs=governance_common_lines_min_docs,
            governance_common_lines_min_ratio=governance_common_lines_min_ratio,
        )
        pipeline_effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=pipeline_options,
        )
        pipeline_strategy_params: dict[str, Any] = dict(getattr(pipeline_effective, "chunk_strategy_params", {}) or {})
        if resolved_chunk_strategy == "parent_child":
            merged = dict(pipeline_strategy_params or {})
            if child_ratio is not None:
                merged["child_ratio"] = child_ratio
            if min_child_size is not None:
                merged["min_child_size"] = min_child_size

            if "child_ratio" in merged:
                r = _coerce_float_preview(merged.get("child_ratio"))
                if r is None:
                    raise HTTPException(status_code=400, detail="child_ratio must be a float")
                if r < 0.05 or r > 1.0:
                    raise HTTPException(status_code=400, detail="child_ratio must be between 0.05 and 1.0")
                chunker_kwargs["child_ratio"] = float(r)

            if "min_child_size" in merged:
                m = _coerce_int_preview(merged.get("min_child_size"))
                if m is None:
                    raise HTTPException(status_code=400, detail="min_child_size must be an int")
                if m < 50 or m > 4000:
                    raise HTTPException(status_code=400, detail="min_child_size must be between 50 and 4000")
                if m > int(chunk_size or 0):
                    warnings_out.append("min_child_size > chunk_size; clamping to chunk_size")
                    m = int(chunk_size or 0)
                chunker_kwargs["min_child_size"] = int(m)
        elif resolved_chunk_strategy == "separator":
            merged = dict(pipeline_strategy_params or {})
            if separator_preset is not None:
                merged["separator_preset"] = separator_preset
            if separator is not None:
                merged["separator"] = separator
            if keep_separator is not None:
                merged["keep_separator"] = keep_separator
            if separator_max_chunk_size is not None:
                merged["separator_max_chunk_size"] = separator_max_chunk_size

            preset = str(merged.get("separator_preset") or "").strip() or "paragraph"
            if preset != "custom":
                sep_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
                if sep_value is None:
                    raise HTTPException(status_code=400, detail=f"Invalid separator_preset: {preset}")
            else:
                raw = merged.get("separator")
                if raw is None:
                    raw = merged.get("separator_custom")
                sep_value = str(raw or "")
                if not sep_value:
                    sep_value = "\n\n"
                sep_value = _decode_escaped_input_preview(sep_value)

            keep_sep = merged.get("keep_separator")
            keep_sep_norm = _coerce_bool_preview(keep_sep)
            keep_sep_bool = True if keep_sep_norm is None else bool(keep_sep_norm)

            max_chunk_size = merged.get("separator_max_chunk_size")
            if max_chunk_size is None:
                max_chunk_size = merged.get("max_chunk_size")
            max_chunk_size_int = int(_coerce_int_preview(max_chunk_size) or 0)

            separator_config = {
                "preset": preset,
                "separator": sep_value,
                "keep_separator": keep_sep_bool,
                "separator_max_chunk_size": max_chunk_size_int,
            }
        else:
            chunker_kwargs = _filter_chunker_kwargs_for_strategy(resolved_chunk_strategy, pipeline_strategy_params)
        extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
        combined_rules = build_governance_rules(extra_rules) if extra_rules else None
        governance_kwargs = {
            **({"rules": combined_rules} if combined_rules else {}),
            "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
            "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
            "unwrap_lines": pipeline_effective.governance_unwrap_lines,
            "remove_common_lines": False,
            "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
            "remove_images": pipeline_effective.governance_remove_images,
            "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
            "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
            "detect_language": pipeline_effective.governance_detect_language,
            "language_min_chars": pipeline_effective.governance_language_min_chars,
            "normalize_urls": pipeline_effective.governance_normalize_urls,
            "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
            "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
            "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
            "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
            "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
            "trim_references": pipeline_effective.governance_trim_references,
            "extract_keywords": pipeline_effective.governance_extract_keywords,
            "keywords_provider": pipeline_effective.governance_keywords_provider,
            "keywords_top_k": pipeline_effective.governance_keywords_top_k,
            "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
            "normalize_tables": pipeline_effective.governance_normalize_tables,
            "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
            "pii_anonymize": pipeline_effective.governance_pii_anonymize,
            "pii_mode": pipeline_effective.governance_pii_mode,
            "pii_mask": pipeline_effective.governance_pii_mask,
            "secrets_redact": pipeline_effective.governance_secrets_redact,
            "secrets_mode": pipeline_effective.governance_secrets_mode,
            "secrets_mask": pipeline_effective.governance_secrets_mask,
            "max_blank_lines": pipeline_effective.governance_max_blank_lines,
            "drop_outline_only": pipeline_effective.governance_drop_outline_only,
            "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
            "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
            "drop_low_density": pipeline_effective.governance_drop_low_density,
            "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
            "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
            "noise_min_chars": pipeline_effective.governance_noise_min_chars,
            "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
            "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
            "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
        }

        if resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
            parse_duration_ms = None
            _integrated_started = time.perf_counter()
            result = await documents_module.run_subprocess_worker(
                tenant_id=tenant_id,
                payload={
                    "action": "integrated_chunk",
                    "tenant_id": str(tenant_id),
                    "account_id": str(account_id),
                    "file_path": str(temp_path),
                    "strategy": resolved_chunk_strategy,
                    "mode": "preview",
                },
                disconnect_check=request.is_disconnected,
                timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
            )
            chunking_duration_ms = int(max(0.0, (time.perf_counter() - _integrated_started) * 1000.0))
            chunks = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (result.get("documents") or [])
                if isinstance(item, dict)
            ]
            resolved_backend = "integrated"
            documents = []
            if pipeline_effective.governance_enabled:
                _gov_started = time.perf_counter()
                chunks, _stats = governance_processor.clean_documents(chunks, **governance_kwargs)
                governance_duration_ms += int(max(0.0, (time.perf_counter() - _gov_started) * 1000.0))
        else:
            parsed_docs_payload: list[dict[str, Any]] | None = None
            resolved_backend = str(parser_backend)

            cache_enabled = bool(getattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", False))
            cache_ttl_sec = int(getattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 0) or 0)
            cache_max_entries = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 0) or 0)
            cache_max_doc_chars = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_DOC_CHARS", 0) or 0)
            cache_version = str(getattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1") or "v1").strip() or "v1"

            async def _parse_uncached_preview_documents() -> tuple[list[dict[str, Any]], str]:
                nonlocal parse_duration_ms
                _parse_started = time.perf_counter()
                if _should_inline_preview_parse(file_ext):
                    parsed_documents, backend, _provenance = parser_factory.parse_with_provenance(
                        temp_path,
                        parser_backend=parser_backend,
                        tenant_id=str(tenant_id),
                    )
                    parsed_documents = _materialize_extracted_images_for_preview(
                        parsed_documents, tenant_id=tenant_id, account_id=account_id
                    )
                    parsed_documents = _materialize_local_images_for_preview(
                        parsed_documents, tenant_id=tenant_id, account_id=account_id
                    )
                    parse_duration_ms = int(max(0.0, (time.perf_counter() - _parse_started) * 1000.0))
                    return _serialize_preview_parse_documents(parsed_documents), str(backend or parser_backend)

                parsed = await documents_module.run_subprocess_worker(
                    tenant_id=tenant_id,
                    payload={
                        "action": "parse_documents",
                        "tenant_id": str(tenant_id),
                        "account_id": str(account_id),
                        "file_path": str(temp_path),
                        "parser_backend": parser_backend,
                        "mode": "preview",
                    },
                    disconnect_check=request.is_disconnected,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
                parse_duration_ms = int(max(0.0, (time.perf_counter() - _parse_started) * 1000.0))
                return [
                    item for item in (parsed.get("documents") or []) if isinstance(item, dict)
                ], str(parsed.get("resolved_backend") or parser_backend)

            cache_key: str | None = None
            if cache_enabled and bool(use_parse_cache) and bool(file_sha256) and cache_ttl_sec > 0 and cache_max_entries > 0:
                cache_key = (
                    f"parse:{str(tenant_id)}:{str(account_id)}:{str(file_sha256)}:{str(file_ext)}:"
                    f"{str(parser_backend or '').strip().lower()}:{cache_version}"
                )
                cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
                if cached is not None:
                    parse_cache_hit = True
                    parse_cache_age_ms = age_ms
                    parsed_docs_payload = list(cached.documents or [])
                    resolved_backend = str(cached.resolved_backend or parser_backend)

            if parsed_docs_payload is None:
                lock = preview_parse_locks.get(cache_key) if cache_key else None
                if lock is not None:
                    async with lock:
                        cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
                        if cached is not None:
                            parse_cache_hit = True
                            parse_cache_age_ms = age_ms
                            parsed_docs_payload = list(cached.documents or [])
                            resolved_backend = str(cached.resolved_backend or parser_backend)
                            parse_duration_ms = 0

                        if parsed_docs_payload is None:
                            parsed_docs_payload, resolved_backend = await _parse_uncached_preview_documents()
                            if cache_key and cache_enabled and bool(use_parse_cache) and cache_ttl_sec > 0 and cache_max_entries > 0:
                                total_chars = sum(len(str(it.get("page_content") or "")) for it in (parsed_docs_payload or []))
                                if cache_max_doc_chars <= 0 or total_chars <= cache_max_doc_chars:
                                    preview_parse_cache.set(
                                        cache_key,
                                        ParseCacheEntry(
                                            created_at_monotonic=time.monotonic(),
                                            created_at_wall=time.time(),
                                            file_sha256=str(file_sha256 or ""),
                                            parser_backend=str(parser_backend or ""),
                                            resolved_backend=str(resolved_backend or ""),
                                            documents=list(parsed_docs_payload or []),
                                            total_chars=int(total_chars),
                                        ),
                                        ttl_sec=cache_ttl_sec,
                                        max_entries=cache_max_entries,
                                    )
                else:
                    parsed_docs_payload, resolved_backend = await _parse_uncached_preview_documents()
                    if cache_key and cache_enabled and bool(use_parse_cache) and cache_ttl_sec > 0 and cache_max_entries > 0:
                        total_chars = sum(len(str(it.get("page_content") or "")) for it in (parsed_docs_payload or []))
                        if cache_max_doc_chars <= 0 or total_chars <= cache_max_doc_chars:
                            preview_parse_cache.set(
                                cache_key,
                                ParseCacheEntry(
                                    created_at_monotonic=time.monotonic(),
                                    created_at_wall=time.time(),
                                    file_sha256=str(file_sha256 or ""),
                                    parser_backend=str(parser_backend or ""),
                                    resolved_backend=str(resolved_backend or ""),
                                    documents=list(parsed_docs_payload or []),
                                    total_chars=int(total_chars),
                                ),
                                ttl_sec=cache_ttl_sec,
                                max_entries=cache_max_entries,
                            )

            documents = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (parsed_docs_payload or [])
                if isinstance(item, dict)
            ]
            if pipeline_effective.governance_enabled:
                _gov_started = time.perf_counter()
                documents, _stats = governance_processor.clean_documents(documents, **governance_kwargs)
                governance_duration_ms += int(max(0.0, (time.perf_counter() - _gov_started) * 1000.0))

            _ensure_preview_page_indices(documents)

            if resolved_chunk_strategy == "separator":
                if separator_config is None:
                    raise ValueError("separator chunk strategy requires separator_config")
                preset = str(separator_config.get("preset") or "paragraph")
                sep_value = str(separator_config.get("separator") or "\n\n")
                keep_sep_bool = bool(separator_config.get("keep_separator"))
                max_chunk_size_int = int(separator_config.get("separator_max_chunk_size") or 0)
                chunker = SeparatorChunker(
                    chunk_size=chunk_size,
                    chunk_overlap=effective_chunk_overlap,
                    separator=sep_value,
                    keep_separator=keep_sep_bool,
                    max_chunk_size=max_chunk_size_int,
                )
                strategy_params_out = {
                    "separator_preset": preset,
                    "separator": sep_value,
                    "keep_separator": keep_sep_bool,
                    "separator_max_chunk_size": max_chunk_size_int,
                }
            else:
                chunker = chunker_factory.get_chunker(
                    resolved_chunk_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=effective_chunk_overlap,
                    **chunker_kwargs,
                )
                strategy_params_out = dict(chunker_kwargs)
                if resolved_chunk_strategy == "parent_child":
                    with contextlib.suppress(Exception):
                        strategy_params_out = {
                            "child_ratio": float(chunker.child_ratio),
                            "min_child_size": int(chunker.min_child_size),
                            "child_size": int(chunker.child_size),
                            "child_overlap": int(chunker.child_overlap),
                        }
            _chunk_started = time.perf_counter()
            chunks = chunker.split_documents(documents)
            chunking_duration_ms = int(max(0.0, (time.perf_counter() - _chunk_started) * 1000.0))

        merge_min = max(0, int(getattr(pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
        if merge_min > 0 and documents and chunks:
            chunks = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=merge_min)

        min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
        if min_chars > 0 and chunks:
            before = len(chunks)
            original_chunks = chunks
            filtered = []
            for c in original_chunks:
                content = (c.page_content or "").strip()
                if len(content) >= min_chars:
                    filtered.append(c)
                    continue
                meta = c.metadata or {}
                if (
                    meta.get("img_id")
                    or meta.get("image_id")
                    or meta.get("image_url")
                    or PREVIEW_IMAGE_REF_RE.search(content)
                    or MINIO_IMAGE_REF_RE.search(content)
                    or (DATA_IMAGE_PREFIX in content.lower())
                ):
                    filtered.append(c)
            kept_short_fallback = False
            if not filtered and original_chunks:
                longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
                filtered = [longest]
                kept_short_fallback = True
            chunks = filtered
            dropped = before - len(chunks)
            if kept_short_fallback:
                kept_len = len((chunks[0].page_content or "").strip()) if chunks else 0
                logger.info(
                    "Chunk preview kept 1 short chunk (%s chars) because all chunks were shorter than %s chars",
                    kept_len,
                    min_chars,
                )
            elif dropped:
                logger.info("Chunk preview dropped %s short chunks (<%s chars)", dropped, min_chars)

        total_chunks_full = len(chunks)
        chunks_truncated = False
        if int(max_chunks or 0) > 0 and len(chunks) > int(max_chunks):
            chunks_truncated = True
            warnings_out.append(f"chunks truncated to max_chunks={int(max_chunks)} (full={total_chunks_full})")
            chunks = chunks[: int(max_chunks)]

        page_texts: list[dict[str, object]] = []
        integrated_chunk_start_map: dict[int, int] = {}
        page_start_map: dict[object, int] = {}
        page_index_start_map: dict[int, int] = {}
        total_characters = 0
        original_text_value: str | None = None

        if documents:
            current_pos = 0
            for doc in documents:
                text = doc.page_content or ""
                meta = doc.metadata or {}
                page_num = meta.get("page") or meta.get("page_number")
                page_index = meta.get("page_index")
                page_texts.append(
                    {
                        "text": text,
                        "page": page_num,
                        "page_index": page_index,
                        "start": current_pos,
                        "end": current_pos + len(text),
                    }
                )
                current_pos += len(text) + 1

            total_characters = sum(len(str(p.get("text") or "")) for p in page_texts) + max(0, len(page_texts) - 1)
            page_index_start_map = {
                int(item.get("page_index")): int(item.get("start") or 0)
                for item in page_texts
                if item.get("page_index") is not None
            }
            for item in page_texts:
                p = item.get("page")
                if p is None:
                    continue
                if p not in page_start_map:
                    page_start_map[p] = int(item.get("start") or 0)
            if include_original and total_characters <= int(original_text_max_chars or 0):
                original_text_value = "\n".join([str(p.get("text") or "") for p in page_texts]) if page_texts else ""
        else:
            total_characters = sum(len(c.page_content or "") for c in chunks) + (2 * (len(chunks) - 1) if chunks else 0)

            parts: list[str] | None = None
            if include_original and total_characters <= int(original_text_max_chars or 0):
                parts = []

            current_pos = 0
            for idx, chunk in enumerate(chunks):
                text = chunk.page_content or ""
                if parts is not None:
                    parts.append(text)
                integrated_chunk_start_map[idx] = current_pos
                current_pos += len(text) + 2

            if parts is not None:
                original_text_value = "\n\n".join(parts) if parts else ""

        _stats_started = time.perf_counter()
        from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

        unit: Literal["chars", "tokens"] = "tokens" if resolved_chunk_strategy == "langchain_token" else "chars"
        chunk_items: list[ChunkPreviewItem] = []
        chunk_ranges: list[tuple[int, int]] = []
        length_samples: list[int] = []
        token_lengths: list[int] = []
        total_len = 0
        total_tokens_est = 0
        short_threshold = 40 if unit == "tokens" else 120
        short_count = 0
        seen_hashes: set[str] = set()
        duplicate_count = 0
        auto_counts: Counter[str] = Counter()
        semantic_quality_enabled = bool(include_chunks) or bool(include_review_signals)
        semantic_quality_max_chunks = 512
        prev_token_set: set[str] | None = None
        needs_review_count = 0

        for idx, chunk in enumerate(chunks):
            content = chunk.page_content or ""
            meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            if not isinstance(chunk.metadata, dict):
                chunk.metadata = meta
            page_num = meta.get("page") or meta.get("page_number")
            page_index = meta.get("page_index")
            local_start = meta.get("start_char")
            local_end = meta.get("end_char")

            doc_base: int | None = None
            if idx in integrated_chunk_start_map:
                start_idx = integrated_chunk_start_map[idx]
            else:
                if page_index is not None:
                    try:
                        doc_base = page_index_start_map.get(int(page_index))
                    except Exception:
                        doc_base = None
                if doc_base is None and page_num is not None:
                    doc_base = page_start_map.get(page_num)

                if doc_base is None:
                    if meta.get("start_char") is not None:
                        start_idx = int(meta.get("start_char"))
                    else:
                        start_idx = 0
                else:
                    try:
                        local = int(local_start) if local_start is not None else 0
                    except Exception:
                        local = 0
                    start_idx = int(doc_base) + local

            end_idx = start_idx + len(content)
            if local_end is not None and idx not in integrated_chunk_start_map:
                try:
                    end_local = int(local_end)
                except Exception:
                    end_local = None
                if end_local is not None:
                    end_idx = end_local if doc_base is None else int(doc_base) + end_local
            if end_idx < start_idx:
                end_idx = start_idx + len(content)
            if end_idx > start_idx:
                chunk_ranges.append((start_idx, end_idx))
            tokens_est = 0
            if content:
                tokens_est = (
                    num_tokens_from_string(content)
                    if resolved_chunk_strategy == "langchain_token"
                    else estimate_tokens(content)
                )

            if semantic_quality_enabled and idx < semantic_quality_max_chunks:
                with contextlib.suppress(Exception):
                    scores, cur_token_set = score_chunk_semantic_quality(
                        content,
                        tokens_est=int(tokens_est or 0),
                        prev_token_set=prev_token_set,
                    )
                    meta["semantic_quality"] = scores
                    if bool(scores.get("needs_review")):
                        meta["needs_review"] = True
                        needs_review_count += 1
                    prev_token_set = cur_token_set

            total_tokens_est += int(tokens_est or 0)
            if int(tokens_est or 0) > 0:
                token_lengths.append(int(tokens_est or 0))
            unit_len = int(tokens_est or 0) if unit == "tokens" else len(content)
            length_samples.append(unit_len)
            total_len += unit_len
            if unit_len > 0 and unit_len < short_threshold:
                short_count += 1

            stripped = content.strip()
            if stripped:
                digest = hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest()
                if digest in seen_hashes:
                    duplicate_count += 1
                else:
                    seen_hashes.add(digest)

            if resolved_chunk_strategy == "auto":
                selected = meta.get("chunk_strategy_selected")
                if isinstance(selected, str) and selected.strip():
                    auto_counts[selected.strip().lower()] += 1

            if bool(include_chunks) or bool(include_review_signals):
                chunk_items.append(
                    ChunkPreviewItem(
                        index=idx,
                        content=content,
                        length=len(content),
                        hierarchy_basis=(
                            str(meta.get("hierarchy_basis")).strip()
                            if meta.get("hierarchy_basis") is not None
                            else None
                        ),
                        tokens_est=tokens_est,
                        start_index=start_idx,
                        end_index=end_idx,
                        page_number=page_num,
                        metadata=chunk.metadata,
                    )
                )

        if semantic_quality_enabled and needs_review_count > 0:
            warnings_out.append(f"{int(needs_review_count)} chunks flagged needs_review (semantic heuristics)")

        sorted_lengths = sorted(length_samples)
        token_stats: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths
            from app.services.dataset_profile_utils import CHUNK_TOKEN_BINS

            token_stats = compute_chunking_stats_from_lengths(
                token_lengths,
                short_threshold=40,
                duplicate_count=int(duplicate_count),
                unit="tokens",
                bins=CHUNK_TOKEN_BINS,
            )
        if sorted_lengths:
            def _pct(p: int) -> int:
                if not sorted_lengths:
                    return 0
                pp = max(0, min(100, int(p)))
                pos = int((pp / 100.0) * (len(sorted_lengths) - 1))
                pos = max(0, min(len(sorted_lengths) - 1, pos))
                return int(sorted_lengths[pos] or 0)

            coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
            histogram = _compute_chunk_length_histogram(sorted_lengths, unit=unit, target_bins=8)
            stats = ChunkPreviewStats(
                unit=unit,
                count=len(sorted_lengths),
                total=int(total_len),
                min=int(sorted_lengths[0]),
                max=int(sorted_lengths[-1]),
                avg=int(round(total_len / len(sorted_lengths))) if sorted_lengths else 0,
                median=_pct(50),
                p10=_pct(10),
                p90=_pct(90),
                p95=_pct(95),
                total_tokens_est=int(total_tokens_est),
                short_count=int(short_count),
                duplicate_count=int(duplicate_count),
                histogram=histogram,
                **coverage,
            )
        else:
            coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
            stats = ChunkPreviewStats(unit=unit, **coverage)
        stats_duration_ms = int(max(0.0, (time.perf_counter() - _stats_started) * 1000.0))

        auto_selected_strategy: str | None = None
        if resolved_chunk_strategy == "auto" and auto_counts:
            auto_selected_strategy = auto_counts.most_common(1)[0][0]

        original_text_truncated_val = _is_original_preview_text_truncated(
            include_original=include_original,
            original_text_value=original_text_value,
            total_characters=int(total_characters or 0),
            original_text_max_chars=int(original_text_max_chars or 0),
        )
        original_text_cleaned_value: str | None = None
        if original_text_value is not None and "@@" in original_text_value and "##" in original_text_value:
            if POSITION_TAG_RE.search(original_text_value):
                original_text_cleaned_value = POSITION_TAG_RE.sub("", original_text_value)
        quality_gate, recommendations, recommendation_patches = _compute_chunk_preview_quality(
            stats=stats,
            total_chunks=len(chunks),
            total_characters=int(total_characters or 0),
            chunk_size=int(chunk_size or 0),
            chunk_overlap=int(effective_chunk_overlap or 0),
            original_text_included=original_text_value is not None,
            original_text_truncated=original_text_truncated_val,
            original_text_max_chars=int(original_text_max_chars or 0),
        )

        review_signals: ChunkPreviewReviewSignals | None = None
        if bool(include_review_signals):
            signals_strategy = auto_selected_strategy or resolved_chunk_strategy
            with contextlib.suppress(Exception):
                review_signals = _compute_chunk_preview_review_signals(
                    chunk_items=chunk_items,
                    unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
                    strategy=str(signals_strategy or ""),
                )

        preview_duration_ms_val = int(max(0.0, (time.perf_counter() - preview_started) * 1000.0))
        with contextlib.suppress(Exception):
            timing_parts: list[str] = []
            if upload_duration_ms is not None:
                timing_parts.append(f"upload;dur={int(upload_duration_ms)}")
            if parse_duration_ms is not None:
                timing_parts.append(f"parse;dur={int(parse_duration_ms)}")
            timing_parts.append(f"govern;dur={int(governance_duration_ms)}")
            timing_parts.append(f"chunk;dur={int(chunking_duration_ms)}")
            timing_parts.append(f"stats;dur={int(stats_duration_ms)}")
            timing_parts.append(f"total;dur={int(preview_duration_ms_val)}")
            if timing_parts:
                response.headers["Server-Timing"] = ", ".join(timing_parts)

        return ChunkPreviewResponse(
            filename=file.filename,
            file_type=file_ext.lstrip("."),
            file_size=file_size,
            file_sha256=file_sha256,
            parse_cache_hit=bool(parse_cache_hit),
            parse_cache_age_ms=parse_cache_age_ms,
            preview_duration_ms=preview_duration_ms_val,
            upload_duration_ms=upload_duration_ms,
            parse_duration_ms=parse_duration_ms,
            governance_duration_ms=int(governance_duration_ms),
            chunking_duration_ms=int(chunking_duration_ms),
            stats_duration_ms=int(stats_duration_ms),
            total_chunks=len(chunks),
            total_chunks_full=int(total_chunks_full),
            chunks_truncated=bool(chunks_truncated),
            chunks_max_count=int(max_chunks or 0),
            total_characters=total_characters,
            params=ChunkPreviewParams(
                chunk_size=chunk_size,
                chunk_overlap=effective_chunk_overlap,
                unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
                strategy_params=strategy_params_out,
            ),
            chunks=(chunk_items if bool(include_chunks) else []),
            stats=stats,
            chunking_stats_tokens=token_stats,
            auto_selected_strategy=auto_selected_strategy,
            warnings=warnings_out,
            review_signals=review_signals,
            quality_gate=quality_gate,
            recommendations=recommendations,
            recommendation_patches=recommendation_patches,
            original_text=original_text_value,
            original_text_cleaned=original_text_cleaned_value,
            original_text_included=original_text_value is not None,
            original_text_truncated=original_text_truncated_val,
            original_text_max_chars=int(original_text_max_chars or 0),
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy,
        )

    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.error("Subprocess worker failed during chunk preview: %s", str(e)[:200])
        msg = (str(e) or "").strip()
        if not msg:
            details = e.details or {}
            msg = str(details.get("message") or details.get("type") or e.__class__.__name__).strip()
        msg = msg[:200]
        detail = "Failed to preview chunking" if is_production_env() else f"Failed to preview chunking: {msg}"
        raise HTTPException(status_code=500, detail=detail) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error during chunk preview: %s", str(e)[:200])
        msg = (str(e) or "").strip()
        if not msg:
            msg = e.__class__.__name__
        msg = msg[:200]
        detail = "Failed to preview chunking" if is_production_env() else f"Failed to preview chunking: {msg}"
        raise HTTPException(status_code=500, detail=detail) from e
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


@router.post("/chunk-preview/by-sha", response_model=ChunkPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def preview_chunking_by_sha(
    request: Request,
    response: Response,
    file_fields: Annotated[ChunkPreviewByShaFileFields, Depends()],
    params: Annotated[ChunkPreviewRequestFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    file_sha256 = file_fields.file_sha256
    file_type = file_fields.file_type
    filename = file_fields.filename
    file_size = file_fields.file_size
    chunk_size = params.chunk_size
    chunk_overlap = params.chunk_overlap
    include_original_text = params.include_original_text
    include_review_signals = params.include_review_signals
    include_chunks = params.include_chunks
    original_text_max_chars = params.original_text_max_chars
    max_chunks = params.max_chunks
    use_parse_cache = params.use_parse_cache
    parser_backend = params.parser_backend
    chunk_strategy = params.chunk_strategy
    child_ratio = params.child_ratio
    min_child_size = params.min_child_size
    separator_preset = params.separator_preset
    separator = params.separator
    keep_separator = params.keep_separator
    separator_max_chunk_size = params.separator_max_chunk_size
    dataset_id = params.dataset_id
    pipeline = params.pipeline
    governance_enabled = params.governance_enabled
    governance_remove_toc_lines = params.governance_remove_toc_lines
    governance_remove_noise_lines = params.governance_remove_noise_lines
    governance_unwrap_lines = params.governance_unwrap_lines
    governance_remove_common_lines = params.governance_remove_common_lines
    governance_unwrap_max_line_length = params.governance_unwrap_max_line_length
    governance_noise_min_chars = params.governance_noise_min_chars
    governance_noise_ratio_threshold = params.governance_noise_ratio_threshold
    governance_common_lines_min_docs = params.governance_common_lines_min_docs
    governance_common_lines_min_ratio = params.governance_common_lines_min_ratio

    preview_started = time.perf_counter()
    parse_cache_hit = False
    parse_cache_age_ms: int | None = None
    upload_duration_ms: int = 0
    parse_duration_ms: int = 0
    governance_duration_ms: int = 0
    chunking_duration_ms: int = 0
    stats_duration_ms: int = 0
    warnings_out: list[str] = []

    sha = (file_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(status_code=400, detail="file_sha256 must be a 64-char hex string")

    raw_type = (file_type or "").strip().lower().lstrip(".")
    if not raw_type and filename:
        raw_type = Path(str(filename)).suffix.lower().lstrip(".")
    if not raw_type:
        raise HTTPException(status_code=400, detail="file_type is required")
    file_ext = f".{raw_type}"
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")

    safe_name = _sanitize_filename(filename or f"{sha[:8]}{file_ext}")

    try:
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    min_chunk_size = 50 if resolved_chunk_strategy == "langchain_token" else 100
    if chunk_size < min_chunk_size or chunk_size > 4000:
        raise HTTPException(status_code=400, detail=f"chunk_size must be between {min_chunk_size} and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if resolved_chunk_strategy != "separator" and chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL)

    effective_chunk_overlap = 0 if resolved_chunk_strategy == "separator" else chunk_overlap
    if resolved_chunk_strategy == "separator" and chunk_overlap != effective_chunk_overlap:
        warnings_out.append("separator strategy ignores chunk_overlap; using 0")

    if (child_ratio is not None or min_child_size is not None) and resolved_chunk_strategy != "parent_child":
        warnings_out.append(
            f"strategy params child_ratio/min_child_size ignored for chunk_strategy={resolved_chunk_strategy}"
        )
    chunker_kwargs: dict[str, Any] = {}
    separator_config: dict[str, Any] | None = None
    strategy_params_out: dict[str, Any] = {}

    if original_text_max_chars < 0 or original_text_max_chars > 2_000_000:
        raise HTTPException(status_code=400, detail="original_text_max_chars must be between 0 and 2000000")
    include_original = _should_include_original_preview_text(
        include_original_text=bool(include_original_text),
        original_text_max_chars=int(original_text_max_chars or 0),
    )

    if resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail="Integrated pipeline strategies do not support by-sha preview; please upload the file",
        )

    cache_enabled = bool(getattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", False))
    cache_ttl_sec = int(getattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 0) or 0)
    cache_max_entries = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 0) or 0)
    cache_version = str(getattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1") or "v1").strip() or "v1"
    if not (cache_enabled and bool(use_parse_cache) and cache_ttl_sec > 0 and cache_max_entries > 0):
        raise HTTPException(status_code=400, detail="parse cache disabled; please upload the file")

    cache_key = (
        f"parse:{str(tenant_id)}:{str(account_id)}:{sha}:{str(file_ext)}:"
        f"{str(parser_backend or '').strip().lower()}:{cache_version}"
    )

    cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
    if cached is None:
        raise HTTPException(status_code=404, detail="Parse cache miss. Upload the file once to warm the cache.")

    parse_cache_hit = True
    parse_cache_age_ms = age_ms
    parsed_docs_payload = list(cached.documents or [])
    resolved_backend = str(cached.resolved_backend or parser_backend)

    dataset_meta: dict = {}
    if dataset_id:
        try:
            ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
            DatasetService.assert_dataset_readable(db, ds, account_id)
            dataset_meta = dict(getattr(ds, "dataset_metadata", None) or {})
        except HTTPException:
            raise
        except Exception:
            dataset_meta = {}

    pipeline_options = _to_pipeline_options(
        pipeline=_parse_pipeline_json(pipeline),
        governance_enabled=governance_enabled,
        governance_remove_toc_lines=governance_remove_toc_lines,
        governance_remove_noise_lines=governance_remove_noise_lines,
        governance_unwrap_lines=governance_unwrap_lines,
        governance_remove_common_lines=governance_remove_common_lines,
        governance_unwrap_max_line_length=governance_unwrap_max_line_length,
        governance_noise_min_chars=governance_noise_min_chars,
        governance_noise_ratio_threshold=governance_noise_ratio_threshold,
        governance_common_lines_min_docs=governance_common_lines_min_docs,
        governance_common_lines_min_ratio=governance_common_lines_min_ratio,
    )
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=dataset_meta,
        document_metadata={},
        request_overrides=pipeline_options,
    )
    pipeline_strategy_params: dict[str, Any] = dict(getattr(pipeline_effective, "chunk_strategy_params", {}) or {})
    if resolved_chunk_strategy == "parent_child":
        merged = dict(pipeline_strategy_params or {})
        if child_ratio is not None:
            merged["child_ratio"] = child_ratio
        if min_child_size is not None:
            merged["min_child_size"] = min_child_size

        if "child_ratio" in merged:
            r = _coerce_float_preview(merged.get("child_ratio"))
            if r is None:
                raise HTTPException(status_code=400, detail="child_ratio must be a float")
            if r < 0.05 or r > 1.0:
                raise HTTPException(status_code=400, detail="child_ratio must be between 0.05 and 1.0")
            chunker_kwargs["child_ratio"] = float(r)

        if "min_child_size" in merged:
            m = _coerce_int_preview(merged.get("min_child_size"))
            if m is None:
                raise HTTPException(status_code=400, detail="min_child_size must be an int")
            if m < 50 or m > 4000:
                raise HTTPException(status_code=400, detail="min_child_size must be between 50 and 4000")
            if m > int(chunk_size or 0):
                warnings_out.append("min_child_size > chunk_size; clamping to chunk_size")
                m = int(chunk_size or 0)
            chunker_kwargs["min_child_size"] = int(m)
    elif resolved_chunk_strategy == "separator":
        merged = dict(pipeline_strategy_params or {})
        if separator_preset is not None:
            merged["separator_preset"] = separator_preset
        if separator is not None:
            merged["separator"] = separator
        if keep_separator is not None:
            merged["keep_separator"] = keep_separator
        if separator_max_chunk_size is not None:
            merged["separator_max_chunk_size"] = separator_max_chunk_size

        preset = str(merged.get("separator_preset") or "").strip() or "paragraph"
        if preset != "custom":
            sep_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
            if sep_value is None:
                raise HTTPException(status_code=400, detail=f"Invalid separator_preset: {preset}")
        else:
            raw = merged.get("separator")
            if raw is None:
                raw = merged.get("separator_custom")
            sep_value = str(raw or "")
            if not sep_value:
                sep_value = "\n\n"
            sep_value = _decode_escaped_input_preview(sep_value)

        keep_sep = merged.get("keep_separator")
        keep_sep_norm = _coerce_bool_preview(keep_sep)
        keep_sep_bool = True if keep_sep_norm is None else bool(keep_sep_norm)

        max_chunk_size = merged.get("separator_max_chunk_size")
        if max_chunk_size is None:
            max_chunk_size = merged.get("max_chunk_size")
        max_chunk_size_int = int(_coerce_int_preview(max_chunk_size) or 0)

        separator_config = {
            "preset": preset,
            "separator": sep_value,
            "keep_separator": keep_sep_bool,
            "separator_max_chunk_size": max_chunk_size_int,
        }
    else:
        chunker_kwargs = _filter_chunker_kwargs_for_strategy(resolved_chunk_strategy, pipeline_strategy_params)
    extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
    combined_rules = build_governance_rules(extra_rules) if extra_rules else None
    governance_kwargs = {
        **({"rules": combined_rules} if combined_rules else {}),
        "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
        "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
        "unwrap_lines": pipeline_effective.governance_unwrap_lines,
        "remove_common_lines": False,
        "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
        "remove_images": pipeline_effective.governance_remove_images,
        "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
        "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
        "detect_language": pipeline_effective.governance_detect_language,
        "language_min_chars": pipeline_effective.governance_language_min_chars,
        "normalize_urls": pipeline_effective.governance_normalize_urls,
        "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
        "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
        "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
        "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
        "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
        "trim_references": pipeline_effective.governance_trim_references,
        "extract_keywords": pipeline_effective.governance_extract_keywords,
        "keywords_provider": pipeline_effective.governance_keywords_provider,
        "keywords_top_k": pipeline_effective.governance_keywords_top_k,
        "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
        "normalize_tables": pipeline_effective.governance_normalize_tables,
        "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
        "pii_anonymize": pipeline_effective.governance_pii_anonymize,
        "pii_mode": pipeline_effective.governance_pii_mode,
        "pii_mask": pipeline_effective.governance_pii_mask,
        "secrets_redact": pipeline_effective.governance_secrets_redact,
        "secrets_mode": pipeline_effective.governance_secrets_mode,
        "secrets_mask": pipeline_effective.governance_secrets_mask,
        "max_blank_lines": pipeline_effective.governance_max_blank_lines,
        "drop_outline_only": pipeline_effective.governance_drop_outline_only,
        "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
        "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
        "drop_low_density": pipeline_effective.governance_drop_low_density,
        "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
        "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
        "noise_min_chars": pipeline_effective.governance_noise_min_chars,
        "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
        "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
        "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
    }

    documents = [
        Document(
            page_content=str(item.get("page_content") or ""),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            id=item.get("id") if isinstance(item.get("id"), str) else None,
        )
        for item in (parsed_docs_payload or [])
        if isinstance(item, dict)
    ]

    if pipeline_effective.governance_enabled:
        _gov_started = time.perf_counter()
        documents, _stats = governance_processor.clean_documents(documents, **governance_kwargs)
        governance_duration_ms += int(max(0.0, (time.perf_counter() - _gov_started) * 1000.0))

    _ensure_preview_page_indices(documents)

    if resolved_chunk_strategy == "separator":
        if separator_config is None:
            raise ValueError("separator chunk strategy requires separator_config")
        preset = str(separator_config.get("preset") or "paragraph")
        sep_value = str(separator_config.get("separator") or "\n\n")
        keep_sep_bool = bool(separator_config.get("keep_separator"))
        max_chunk_size_int = int(separator_config.get("separator_max_chunk_size") or 0)
        chunker = SeparatorChunker(
            chunk_size=chunk_size,
            chunk_overlap=effective_chunk_overlap,
            separator=sep_value,
            keep_separator=keep_sep_bool,
            max_chunk_size=max_chunk_size_int,
        )
        strategy_params_out = {
            "separator_preset": preset,
            "separator": sep_value,
            "keep_separator": keep_sep_bool,
            "separator_max_chunk_size": max_chunk_size_int,
        }
    else:
        chunker = chunker_factory.get_chunker(
            resolved_chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=effective_chunk_overlap,
            **chunker_kwargs,
        )
        strategy_params_out = dict(chunker_kwargs)
        if resolved_chunk_strategy == "parent_child":
            with contextlib.suppress(Exception):
                strategy_params_out = {
                    "child_ratio": float(chunker.child_ratio),
                    "min_child_size": int(chunker.min_child_size),
                    "child_size": int(chunker.child_size),
                    "child_overlap": int(chunker.child_overlap),
                }

    _chunk_started = time.perf_counter()
    chunks = chunker.split_documents(documents)
    chunking_duration_ms = int(max(0.0, (time.perf_counter() - _chunk_started) * 1000.0))

    merge_min = max(0, int(getattr(pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
    if merge_min > 0 and documents and chunks:
        chunks = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=merge_min)

    min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
    if min_chars > 0 and chunks:
        before = len(chunks)
        original_chunks = chunks
        filtered = []
        for c in original_chunks:
            content = (c.page_content or "").strip()
            if len(content) >= min_chars:
                filtered.append(c)
                continue
            meta = c.metadata or {}
            if (
                meta.get("img_id")
                or meta.get("image_id")
                or meta.get("image_url")
                or PREVIEW_IMAGE_REF_RE.search(content)
                or MINIO_IMAGE_REF_RE.search(content)
                or (DATA_IMAGE_PREFIX in content.lower())
            ):
                filtered.append(c)
        if not filtered and original_chunks:
            longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
            filtered = [longest]
        chunks = filtered
        dropped = before - len(chunks)
        if dropped:
            logger.info("Chunk preview(by-sha) dropped %s short chunks (<%s chars)", dropped, min_chars)

    total_chunks_full = len(chunks)
    chunks_truncated = False
    if int(max_chunks or 0) > 0 and len(chunks) > int(max_chunks):
        chunks_truncated = True
        warnings_out.append(f"chunks truncated to max_chunks={int(max_chunks)} (full={total_chunks_full})")
        chunks = chunks[: int(max_chunks)]

    page_texts: list[dict[str, object]] = []
    page_start_map: dict[object, int] = {}
    page_index_start_map: dict[int, int] = {}
    total_characters = 0
    original_text_value: str | None = None

    current_pos = 0
    for doc in documents:
        text = doc.page_content or ""
        meta = doc.metadata or {}
        page_num = meta.get("page") or meta.get("page_number")
        page_index = meta.get("page_index")
        page_texts.append(
            {
                "text": text,
                "page": page_num,
                "page_index": page_index,
                "start": current_pos,
                "end": current_pos + len(text),
            }
        )
        current_pos += len(text) + 1

    total_characters = sum(len(str(p.get("text") or "")) for p in page_texts) + max(0, len(page_texts) - 1)
    page_index_start_map = {
        int(item.get("page_index")): int(item.get("start") or 0)
        for item in page_texts
        if item.get("page_index") is not None
    }
    for item in page_texts:
        p = item.get("page")
        if p is None:
            continue
        if p not in page_start_map:
            page_start_map[p] = int(item.get("start") or 0)
    if include_original and total_characters <= int(original_text_max_chars or 0):
        original_text_value = "\n".join([str(p.get("text") or "") for p in page_texts]) if page_texts else ""

    _stats_started = time.perf_counter()
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    unit: Literal["chars", "tokens"] = "tokens" if resolved_chunk_strategy == "langchain_token" else "chars"
    chunk_items: list[ChunkPreviewItem] = []
    chunk_ranges: list[tuple[int, int]] = []
    length_samples: list[int] = []
    token_lengths: list[int] = []
    total_len = 0
    total_tokens_est = 0
    short_threshold = 40 if unit == "tokens" else 120
    short_count = 0
    seen_hashes: set[str] = set()
    duplicate_count = 0
    auto_counts: Counter[str] = Counter()
    semantic_quality_enabled = bool(include_chunks) or bool(include_review_signals)
    semantic_quality_max_chunks = 512
    prev_token_set: set[str] | None = None
    needs_review_count = 0

    for idx, chunk in enumerate(chunks):
        content = chunk.page_content or ""
        meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        if not isinstance(chunk.metadata, dict):
            chunk.metadata = meta
        page_num = meta.get("page") or meta.get("page_number")
        page_index = meta.get("page_index")
        local_start = meta.get("start_char")
        local_end = meta.get("end_char")

        doc_base: int | None = None
        if page_index is not None:
            try:
                doc_base = page_index_start_map.get(int(page_index))
            except Exception:
                doc_base = None
        if doc_base is None and page_num is not None:
            doc_base = page_start_map.get(page_num)

        if doc_base is None:
            if meta.get("start_char") is not None:
                start_idx = int(meta.get("start_char"))
            else:
                start_idx = 0
        else:
            try:
                local = int(local_start) if local_start is not None else 0
            except Exception:
                local = 0
            start_idx = int(doc_base) + local

        end_idx = start_idx + len(content)
        if local_end is not None:
            try:
                end_local = int(local_end)
            except Exception:
                end_local = None
            if end_local is not None:
                end_idx = end_local if doc_base is None else int(doc_base) + end_local
        if end_idx < start_idx:
            end_idx = start_idx + len(content)
        if end_idx > start_idx:
            chunk_ranges.append((start_idx, end_idx))
        tokens_est = 0
        if content:
            tokens_est = (
                num_tokens_from_string(content)
                if resolved_chunk_strategy == "langchain_token"
                else estimate_tokens(content)
            )

        if semantic_quality_enabled and idx < semantic_quality_max_chunks:
            with contextlib.suppress(Exception):
                scores, cur_token_set = score_chunk_semantic_quality(
                    content,
                    tokens_est=int(tokens_est or 0),
                    prev_token_set=prev_token_set,
                )
                meta["semantic_quality"] = scores
                if bool(scores.get("needs_review")):
                    meta["needs_review"] = True
                    needs_review_count += 1
                prev_token_set = cur_token_set

        total_tokens_est += int(tokens_est or 0)
        if int(tokens_est or 0) > 0:
            token_lengths.append(int(tokens_est or 0))
        unit_len = int(tokens_est or 0) if unit == "tokens" else len(content)
        length_samples.append(unit_len)
        total_len += unit_len
        if unit_len > 0 and unit_len < short_threshold:
            short_count += 1

        stripped = content.strip()
        if stripped:
            digest = hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest()
            if digest in seen_hashes:
                duplicate_count += 1
            else:
                seen_hashes.add(digest)

        if resolved_chunk_strategy == "auto":
            selected = meta.get("chunk_strategy_selected")
            if isinstance(selected, str) and selected.strip():
                auto_counts[selected.strip().lower()] += 1

        if bool(include_chunks) or bool(include_review_signals):
            chunk_items.append(
                ChunkPreviewItem(
                    index=idx,
                    content=content,
                    length=len(content),
                    hierarchy_basis=(
                        str(meta.get("hierarchy_basis")).strip()
                        if meta.get("hierarchy_basis") is not None
                        else None
                    ),
                    tokens_est=tokens_est,
                    start_index=start_idx,
                    end_index=end_idx,
                    page_number=page_num,
                    metadata=chunk.metadata,
                )
            )

    if semantic_quality_enabled and needs_review_count > 0:
        warnings_out.append(f"{int(needs_review_count)} chunks flagged needs_review (semantic heuristics)")

    sorted_lengths = sorted(length_samples)
    token_stats: dict[str, Any] | None = None
    with contextlib.suppress(Exception):
        from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths
        from app.services.dataset_profile_utils import CHUNK_TOKEN_BINS

        token_stats = compute_chunking_stats_from_lengths(
            token_lengths,
            short_threshold=40,
            duplicate_count=int(duplicate_count),
            unit="tokens",
            bins=CHUNK_TOKEN_BINS,
        )
    if sorted_lengths:
        def _pct(p: int) -> int:
            if not sorted_lengths:
                return 0
            pp = max(0, min(100, int(p)))
            pos = int((pp / 100.0) * (len(sorted_lengths) - 1))
            pos = max(0, min(len(sorted_lengths) - 1, pos))
            return int(sorted_lengths[pos] or 0)

        coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
        histogram = _compute_chunk_length_histogram(sorted_lengths, unit=unit, target_bins=8)
        stats = ChunkPreviewStats(
            unit=unit,
            count=len(sorted_lengths),
            total=int(total_len),
            min=int(sorted_lengths[0]),
            max=int(sorted_lengths[-1]),
            avg=int(round(total_len / len(sorted_lengths))) if sorted_lengths else 0,
            median=_pct(50),
            p10=_pct(10),
            p90=_pct(90),
            p95=_pct(95),
            total_tokens_est=int(total_tokens_est),
            short_count=int(short_count),
            duplicate_count=int(duplicate_count),
            histogram=histogram,
            **coverage,
        )
    else:
        coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
        stats = ChunkPreviewStats(unit=unit, **coverage)
    stats_duration_ms = int(max(0.0, (time.perf_counter() - _stats_started) * 1000.0))

    auto_selected_strategy: str | None = None
    if resolved_chunk_strategy == "auto" and auto_counts:
        auto_selected_strategy = auto_counts.most_common(1)[0][0]

    original_text_truncated_val = _is_original_preview_text_truncated(
        include_original=include_original,
        original_text_value=original_text_value,
        total_characters=int(total_characters or 0),
        original_text_max_chars=int(original_text_max_chars or 0),
    )
    original_text_cleaned_value: str | None = None
    if original_text_value is not None and "@@" in original_text_value and "##" in original_text_value:
        if POSITION_TAG_RE.search(original_text_value):
            original_text_cleaned_value = POSITION_TAG_RE.sub("", original_text_value)
    quality_gate, recommendations, recommendation_patches = _compute_chunk_preview_quality(
        stats=stats,
        total_chunks=len(chunks),
        total_characters=int(total_characters or 0),
        chunk_size=int(chunk_size or 0),
        chunk_overlap=int(effective_chunk_overlap or 0),
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated_val,
        original_text_max_chars=int(original_text_max_chars or 0),
    )

    review_signals: ChunkPreviewReviewSignals | None = None
    if bool(include_review_signals):
        signals_strategy = auto_selected_strategy or resolved_chunk_strategy
        with contextlib.suppress(Exception):
            review_signals = _compute_chunk_preview_review_signals(
                chunk_items=chunk_items,
                unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
                strategy=str(signals_strategy or ""),
            )

    preview_duration_ms_val = int(max(0.0, (time.perf_counter() - preview_started) * 1000.0))
    with contextlib.suppress(Exception):
        timing_parts: list[str] = []
        timing_parts.append(f"upload;dur={int(upload_duration_ms)}")
        timing_parts.append(f"parse;dur={int(parse_duration_ms)}")
        timing_parts.append(f"govern;dur={int(governance_duration_ms)}")
        timing_parts.append(f"chunk;dur={int(chunking_duration_ms)}")
        timing_parts.append(f"stats;dur={int(stats_duration_ms)}")
        timing_parts.append(f"total;dur={int(preview_duration_ms_val)}")
        response.headers["Server-Timing"] = ", ".join(timing_parts)

    return ChunkPreviewResponse(
        filename=safe_name,
        file_type=file_ext.lstrip("."),
        file_size=int(file_size or 0),
        file_sha256=sha,
        parse_cache_hit=bool(parse_cache_hit),
        parse_cache_age_ms=parse_cache_age_ms,
        preview_duration_ms=preview_duration_ms_val,
        upload_duration_ms=int(upload_duration_ms),
        parse_duration_ms=int(parse_duration_ms),
        governance_duration_ms=int(governance_duration_ms),
        chunking_duration_ms=int(chunking_duration_ms),
        stats_duration_ms=int(stats_duration_ms),
        total_chunks=len(chunks),
        total_chunks_full=int(total_chunks_full),
        chunks_truncated=bool(chunks_truncated),
        chunks_max_count=int(max_chunks or 0),
        total_characters=total_characters,
        params=ChunkPreviewParams(
            chunk_size=chunk_size,
            chunk_overlap=effective_chunk_overlap,
            unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
            strategy_params=strategy_params_out,
        ),
        chunks=(chunk_items if bool(include_chunks) else []),
        stats=stats,
        chunking_stats_tokens=token_stats,
        auto_selected_strategy=auto_selected_strategy,
        warnings=warnings_out,
        review_signals=review_signals,
        quality_gate=quality_gate,
        recommendations=recommendations,
        recommendation_patches=recommendation_patches,
        original_text=original_text_value,
        original_text_cleaned=original_text_cleaned_value,
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated_val,
        original_text_max_chars=int(original_text_max_chars or 0),
        parser_backend=resolved_backend,
        chunk_strategy=resolved_chunk_strategy,
    )
