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


@dataclass
class PreviewRequestConfig:
    chunk_size: int
    effective_chunk_overlap: int
    include_original: bool
    include_chunks: bool
    include_review_signals: bool
    original_text_max_chars: int
    max_chunks: int
    use_parse_cache: bool
    parser_backend: str
    resolved_chunk_strategy: str
    warnings_out: list[str]


@dataclass
class PreviewPipelineState:
    pipeline_effective: Any
    chunker_kwargs: dict[str, Any]
    separator_config: dict[str, Any] | None
    strategy_params_out: dict[str, Any]
    governance_kwargs: dict[str, Any]


@dataclass
class PreviewExecutionState:
    documents: list[Document]
    chunks: list[Document]
    resolved_backend: str
    parse_cache_hit: bool
    parse_cache_age_ms: int | None
    parse_duration_ms: int | None
    governance_duration_ms: int
    chunking_duration_ms: int
    total_chunks_full: int
    chunks_truncated: bool


def _resolve_preview_chunk_strategy(chunk_strategy: str) -> str:
    try:
        return chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_preview_size_bounds(*, resolved_chunk_strategy: str, chunk_size: int, chunk_overlap: int) -> None:
    min_chunk_size = 50 if resolved_chunk_strategy == "langchain_token" else 100
    if chunk_size < min_chunk_size or chunk_size > 4000:
        raise HTTPException(status_code=400, detail=f"chunk_size must be between {min_chunk_size} and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if resolved_chunk_strategy != "separator" and chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL)


def _build_preview_request_config(
    *,
    chunk_size: int,
    chunk_overlap: int,
    include_original_text: bool,
    include_chunks: bool,
    include_review_signals: bool,
    original_text_max_chars: int,
    max_chunks: int,
    use_parse_cache: bool,
    parser_backend: str,
    chunk_strategy: str,
    child_ratio: float | None,
    min_child_size: int | None,
) -> PreviewRequestConfig:
    resolved_chunk_strategy = _resolve_preview_chunk_strategy(chunk_strategy)
    _validate_preview_size_bounds(
        resolved_chunk_strategy=resolved_chunk_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    if original_text_max_chars < 0 or original_text_max_chars > 2_000_000:
        raise HTTPException(status_code=400, detail="original_text_max_chars must be between 0 and 2000000")
    if max_chunks < 0 or max_chunks > 20000:
        raise HTTPException(status_code=400, detail="max_chunks must be between 0 and 20000")

    effective_chunk_overlap = 0 if resolved_chunk_strategy == "separator" else chunk_overlap
    warnings_out: list[str] = []
    if resolved_chunk_strategy == "separator" and chunk_overlap != effective_chunk_overlap:
        warnings_out.append("separator strategy ignores chunk_overlap; using 0")
    if (child_ratio is not None or min_child_size is not None) and resolved_chunk_strategy != "parent_child":
        warnings_out.append(
            f"strategy params child_ratio/min_child_size ignored for chunk_strategy={resolved_chunk_strategy}"
        )
    include_original = _should_include_original_preview_text(
        include_original_text=bool(include_original_text),
        original_text_max_chars=int(original_text_max_chars or 0),
    )
    return PreviewRequestConfig(
        chunk_size=chunk_size,
        effective_chunk_overlap=effective_chunk_overlap,
        include_original=include_original,
        include_chunks=bool(include_chunks),
        include_review_signals=bool(include_review_signals),
        original_text_max_chars=int(original_text_max_chars or 0),
        max_chunks=int(max_chunks or 0),
        use_parse_cache=bool(use_parse_cache),
        parser_backend=str(parser_backend or ""),
        resolved_chunk_strategy=resolved_chunk_strategy,
        warnings_out=warnings_out,
    )


def _resolve_preview_dataset_meta(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: str | None,
) -> dict[str, Any]:
    if not dataset_id:
        return {}
    try:
        ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
        DatasetService.assert_dataset_readable(db, ds, account_id)
        return dict(getattr(ds, "dataset_metadata", None) or {})
    except HTTPException:
        raise
    except Exception:
        return {}


def _resolve_parent_child_chunker_kwargs(
    *,
    pipeline_strategy_params: dict[str, Any],
    child_ratio: float | None,
    min_child_size: int | None,
    chunk_size: int,
    warnings_out: list[str],
) -> dict[str, Any]:
    merged = dict(pipeline_strategy_params or {})
    if child_ratio is not None:
        merged["child_ratio"] = child_ratio
    if min_child_size is not None:
        merged["min_child_size"] = min_child_size

    out: dict[str, Any] = {}
    if "child_ratio" in merged:
        ratio = _coerce_float_preview(merged.get("child_ratio"))
        if ratio is None:
            raise HTTPException(status_code=400, detail="child_ratio must be a float")
        if ratio < 0.05 or ratio > 1.0:
            raise HTTPException(status_code=400, detail="child_ratio must be between 0.05 and 1.0")
        out["child_ratio"] = float(ratio)
    if "min_child_size" in merged:
        min_size = _coerce_int_preview(merged.get("min_child_size"))
        if min_size is None:
            raise HTTPException(status_code=400, detail="min_child_size must be an int")
        if min_size < 50 or min_size > 4000:
            raise HTTPException(status_code=400, detail="min_child_size must be between 50 and 4000")
        if min_size > int(chunk_size or 0):
            warnings_out.append("min_child_size > chunk_size; clamping to chunk_size")
            min_size = int(chunk_size or 0)
        out["min_child_size"] = int(min_size)
    return out


def _resolve_separator_chunker_state(
    *,
    pipeline_strategy_params: dict[str, Any],
    separator_preset: str | None,
    separator: str | None,
    keep_separator: bool | None,
    separator_max_chunk_size: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        separator_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
        if separator_value is None:
            raise HTTPException(status_code=400, detail=f"Invalid separator_preset: {preset}")
    else:
        raw = merged.get("separator")
        if raw is None:
            raw = merged.get("separator_custom")
        separator_value = _decode_escaped_input_preview(str(raw or "") or "\n\n")

    keep_sep_norm = _coerce_bool_preview(merged.get("keep_separator"))
    keep_sep_bool = True if keep_sep_norm is None else bool(keep_sep_norm)
    max_chunk_size = merged.get("separator_max_chunk_size")
    if max_chunk_size is None:
        max_chunk_size = merged.get("max_chunk_size")
    max_chunk_size_int = int(_coerce_int_preview(max_chunk_size) or 0)
    separator_config = {
        "preset": preset,
        "separator": separator_value,
        "keep_separator": keep_sep_bool,
        "separator_max_chunk_size": max_chunk_size_int,
    }
    return {}, separator_config


def _build_preview_governance_kwargs(pipeline_effective: Any) -> dict[str, Any]:
    extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
    combined_rules = build_governance_rules(extra_rules) if extra_rules else None
    return {
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
        "drop_duplicate_paragraphs_min_occurrences": (
            pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences
        ),
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


def _resolve_preview_pipeline_state(
    *,
    config: PreviewRequestConfig,
    dataset_meta: dict[str, Any],
    params: ChunkPreviewRequestFields,
) -> PreviewPipelineState:
    pipeline_options = _to_pipeline_options(
        pipeline=_parse_pipeline_json(params.pipeline),
        governance_enabled=params.governance_enabled,
        governance_remove_toc_lines=params.governance_remove_toc_lines,
        governance_remove_noise_lines=params.governance_remove_noise_lines,
        governance_unwrap_lines=params.governance_unwrap_lines,
        governance_remove_common_lines=params.governance_remove_common_lines,
        governance_unwrap_max_line_length=params.governance_unwrap_max_line_length,
        governance_noise_min_chars=params.governance_noise_min_chars,
        governance_noise_ratio_threshold=params.governance_noise_ratio_threshold,
        governance_common_lines_min_docs=params.governance_common_lines_min_docs,
        governance_common_lines_min_ratio=params.governance_common_lines_min_ratio,
    )
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=dataset_meta,
        document_metadata={},
        request_overrides=pipeline_options,
    )
    pipeline_strategy_params = dict(getattr(pipeline_effective, "chunk_strategy_params", {}) or {})
    if config.resolved_chunk_strategy == "parent_child":
        chunker_kwargs = _resolve_parent_child_chunker_kwargs(
            pipeline_strategy_params=pipeline_strategy_params,
            child_ratio=params.child_ratio,
            min_child_size=params.min_child_size,
            chunk_size=config.chunk_size,
            warnings_out=config.warnings_out,
        )
        separator_config = None
    elif config.resolved_chunk_strategy == "separator":
        chunker_kwargs, separator_config = _resolve_separator_chunker_state(
            pipeline_strategy_params=pipeline_strategy_params,
            separator_preset=params.separator_preset,
            separator=params.separator,
            keep_separator=params.keep_separator,
            separator_max_chunk_size=params.separator_max_chunk_size,
        )
    else:
        chunker_kwargs = _filter_chunker_kwargs_for_strategy(
            config.resolved_chunk_strategy,
            pipeline_strategy_params,
        )
        separator_config = None
    return PreviewPipelineState(
        pipeline_effective=pipeline_effective,
        chunker_kwargs=chunker_kwargs,
        separator_config=separator_config,
        strategy_params_out={},
        governance_kwargs=_build_preview_governance_kwargs(pipeline_effective),
    )


def _materialize_preview_documents(parsed_docs_payload: list[dict[str, Any]] | None) -> list[Document]:
    return [
        Document(
            page_content=str(item.get("page_content") or ""),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            id=item.get("id") if isinstance(item.get("id"), str) else None,
        )
        for item in (parsed_docs_payload or [])
        if isinstance(item, dict)
    ]


def _apply_preview_governance(
    documents: list[Document],
    *,
    pipeline_state: PreviewPipelineState,
) -> tuple[list[Document], int]:
    if not pipeline_state.pipeline_effective.governance_enabled:
        return documents, 0
    started_at = time.perf_counter()
    cleaned_documents, _stats = governance_processor.clean_documents(
        documents,
        **pipeline_state.governance_kwargs,
    )
    duration_ms = int(max(0.0, (time.perf_counter() - started_at) * 1000.0))
    return cleaned_documents, duration_ms


def _create_preview_chunker(
    *,
    config: PreviewRequestConfig,
    pipeline_state: PreviewPipelineState,
) -> tuple[Any, dict[str, Any]]:
    if config.resolved_chunk_strategy == "separator":
        separator_config = pipeline_state.separator_config
        if separator_config is None:
            raise ValueError("separator chunk strategy requires separator_config")
        strategy_params_out = dict(separator_config)
        chunker = SeparatorChunker(
            chunk_size=config.chunk_size,
            chunk_overlap=config.effective_chunk_overlap,
            separator=str(separator_config.get("separator") or "\n\n"),
            keep_separator=bool(separator_config.get("keep_separator")),
            max_chunk_size=int(separator_config.get("separator_max_chunk_size") or 0),
        )
        return chunker, strategy_params_out

    chunker = chunker_factory.get_chunker(
        config.resolved_chunk_strategy,
        chunk_size=config.chunk_size,
        chunk_overlap=config.effective_chunk_overlap,
        **pipeline_state.chunker_kwargs,
    )
    strategy_params_out = dict(pipeline_state.chunker_kwargs)
    if config.resolved_chunk_strategy == "parent_child":
        with contextlib.suppress(Exception):
            strategy_params_out = {
                "child_ratio": float(chunker.child_ratio),
                "min_child_size": int(chunker.min_child_size),
                "child_size": int(chunker.child_size),
                "child_overlap": int(chunker.child_overlap),
            }
    return chunker, strategy_params_out


def _filter_preview_chunks(
    *,
    documents: list[Document],
    chunks: list[Document],
    pipeline_state: PreviewPipelineState,
    by_sha: bool,
    max_chunks: int,
    warnings_out: list[str],
) -> tuple[list[Document], int, bool]:
    merge_min = max(0, int(getattr(pipeline_state.pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
    if merge_min > 0 and documents and chunks:
        chunks = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=merge_min)

    min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
    if min_chars > 0 and chunks:
        before = len(chunks)
        original_chunks = chunks
        filtered: list[Document] = []
        for chunk in original_chunks:
            content = (chunk.page_content or "").strip()
            if len(content) >= min_chars:
                filtered.append(chunk)
                continue
            meta = chunk.metadata or {}
            if (
                meta.get("img_id")
                or meta.get("image_id")
                or meta.get("image_url")
                or PREVIEW_IMAGE_REF_RE.search(content)
                or MINIO_IMAGE_REF_RE.search(content)
                or (DATA_IMAGE_PREFIX in content.lower())
            ):
                filtered.append(chunk)
        if not filtered and original_chunks:
            filtered = [max(original_chunks, key=lambda item: len((item.page_content or "").strip()))]
        chunks = filtered
        dropped = before - len(chunks)
        if dropped:
            label = "Chunk preview(by-sha)" if by_sha else "Chunk preview"
            logger.info("%s dropped %s short chunks (<%s chars)", label, dropped, min_chars)

    total_chunks_full = len(chunks)
    chunks_truncated = False
    if max_chunks > 0 and len(chunks) > int(max_chunks):
        chunks_truncated = True
        warnings_out.append(f"chunks truncated to max_chunks={int(max_chunks)} (full={total_chunks_full})")
        chunks = chunks[: int(max_chunks)]
    return chunks, total_chunks_full, chunks_truncated


def _build_preview_text_context(
    *,
    documents: list[Document],
    chunks: list[Document],
    include_original: bool,
    original_text_max_chars: int,
) -> tuple[dict[int, int], dict[object, int], dict[int, int], int, str | None]:
    if not documents:
        total_characters = sum(len(chunk.page_content or "") for chunk in chunks)
        total_characters += 2 * (len(chunks) - 1) if chunks else 0
        original_text_value = None
        if include_original and total_characters <= int(original_text_max_chars or 0):
            original_text_value = "\n\n".join(chunk.page_content or "" for chunk in chunks) if chunks else ""
        integrated_map = {}
        current_pos = 0
        for idx, chunk in enumerate(chunks):
            integrated_map[idx] = current_pos
            current_pos += len(chunk.page_content or "") + 2
        return integrated_map, {}, {}, total_characters, original_text_value

    page_texts: list[dict[str, object]] = []
    current_pos = 0
    for doc in documents:
        text = doc.page_content or ""
        meta = doc.metadata or {}
        page_texts.append(
            {
                "text": text,
                "page": meta.get("page") or meta.get("page_number"),
                "page_index": meta.get("page_index"),
                "start": current_pos,
            }
        )
        current_pos += len(text) + 1
    total_characters = sum(len(str(item.get("text") or "")) for item in page_texts) + max(0, len(page_texts) - 1)
    page_index_start_map = {
        int(item.get("page_index")): int(item.get("start") or 0)
        for item in page_texts
        if item.get("page_index") is not None
    }
    page_start_map: dict[object, int] = {}
    for item in page_texts:
        page = item.get("page")
        if page is not None and page not in page_start_map:
            page_start_map[page] = int(item.get("start") or 0)
    original_text_value = None
    if include_original and total_characters <= int(original_text_max_chars or 0):
        original_text_value = "\n".join(str(item.get("text") or "") for item in page_texts) if page_texts else ""
    return {}, page_start_map, page_index_start_map, total_characters, original_text_value


def _resolve_preview_chunk_offsets(
    *,
    idx: int,
    chunk: Document,
    integrated_chunk_start_map: dict[int, int],
    page_start_map: dict[object, int],
    page_index_start_map: dict[int, int],
) -> tuple[int, int, object | None]:
    content = chunk.page_content or ""
    meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
    page_num = meta.get("page") or meta.get("page_number")
    page_index = meta.get("page_index")
    local_start = meta.get("start_char")
    local_end = meta.get("end_char")
    doc_base: int | None = None
    if idx in integrated_chunk_start_map:
        start_idx = integrated_chunk_start_map[idx]
    else:
        if page_index is not None:
            with contextlib.suppress(Exception):
                doc_base = page_index_start_map.get(int(page_index))
        if doc_base is None and page_num is not None:
            doc_base = page_start_map.get(page_num)
        if doc_base is None:
            start_idx = int(meta.get("start_char")) if meta.get("start_char") is not None else 0
        else:
            local = int(local_start) if local_start is not None else 0
            start_idx = int(doc_base) + local
    end_idx = start_idx + len(content)
    if local_end is not None and idx not in integrated_chunk_start_map:
        with contextlib.suppress(Exception):
            end_local = int(local_end)
            end_idx = end_local if doc_base is None else int(doc_base) + end_local
    if end_idx < start_idx:
        end_idx = start_idx + len(content)
    return start_idx, end_idx, page_num


def _estimate_preview_tokens(*, content: str, resolved_chunk_strategy: str) -> int:
    if not content:
        return 0
    if resolved_chunk_strategy == "langchain_token":
        return num_tokens_from_string(content)
    return estimate_tokens(content)


def _annotate_preview_semantic_quality(
    *,
    content: str,
    meta: dict[str, Any],
    config: PreviewRequestConfig,
    idx: int,
    prev_token_set: set[str] | None,
    score_chunk_semantic_quality: Any,
) -> tuple[int, set[str] | None]:
    if not (config.include_chunks or config.include_review_signals) or idx >= 512:
        return 0, prev_token_set
    tokens_est = _estimate_preview_tokens(
        content=content,
        resolved_chunk_strategy=config.resolved_chunk_strategy,
    )
    with contextlib.suppress(Exception):
        scores, prev_token_set = score_chunk_semantic_quality(
            content,
            tokens_est=int(tokens_est or 0),
            prev_token_set=prev_token_set,
        )
        meta["semantic_quality"] = scores
        if bool(scores.get("needs_review")):
            meta["needs_review"] = True
            return 1, prev_token_set
    return 0, prev_token_set


def _collect_preview_chunk_metrics(
    *,
    chunks: list[Document],
    config: PreviewRequestConfig,
    integrated_chunk_start_map: dict[int, int],
    page_start_map: dict[object, int],
    page_index_start_map: dict[int, int],
) -> tuple[list[ChunkPreviewItem], list[tuple[int, int]], list[int], list[int], int, int, int, int, int, str | None]:
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    unit = "tokens" if config.resolved_chunk_strategy == "langchain_token" else "chars"
    chunk_items: list[ChunkPreviewItem] = []
    chunk_ranges: list[tuple[int, int]] = []
    length_samples: list[int] = []
    token_lengths: list[int] = []
    total_len = 0
    total_tokens_est = 0
    short_threshold = 40 if unit == "tokens" else 120
    short_count = 0
    duplicate_count = 0
    seen_hashes: set[str] = set()
    auto_selected_strategy: str | None = None
    auto_counts: Counter[str] = Counter()
    prev_token_set: set[str] | None = None
    needs_review_count = 0

    for idx, chunk in enumerate(chunks):
        start_idx, end_idx, page_num = _resolve_preview_chunk_offsets(
            idx=idx,
            chunk=chunk,
            integrated_chunk_start_map=integrated_chunk_start_map,
            page_start_map=page_start_map,
            page_index_start_map=page_index_start_map,
        )
        if end_idx > start_idx:
            chunk_ranges.append((start_idx, end_idx))
        content = chunk.page_content or ""
        meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        needs_review_delta, prev_token_set = _annotate_preview_semantic_quality(
            content=content,
            meta=meta,
            config=config,
            idx=idx,
            prev_token_set=prev_token_set,
            score_chunk_semantic_quality=score_chunk_semantic_quality,
        )
        needs_review_count += needs_review_delta
        tokens_est = _estimate_preview_tokens(
            content=content,
            resolved_chunk_strategy=config.resolved_chunk_strategy,
        )
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
        selected = meta.get("chunk_strategy_selected")
        if config.resolved_chunk_strategy == "auto" and isinstance(selected, str) and selected.strip():
            auto_counts[selected.strip().lower()] += 1
        if config.include_chunks or config.include_review_signals:
            chunk_items.append(
                ChunkPreviewItem(
                    index=idx,
                    content=content,
                    length=len(content),
                    hierarchy_basis=(
                        str(meta.get("hierarchy_basis")).strip() if meta.get("hierarchy_basis") is not None else None
                    ),
                    tokens_est=tokens_est,
                    start_index=start_idx,
                    end_index=end_idx,
                    page_number=page_num,
                    metadata=chunk.metadata if isinstance(chunk.metadata, dict) else meta,
                )
            )
    if config.resolved_chunk_strategy == "auto" and auto_counts:
        auto_selected_strategy = auto_counts.most_common(1)[0][0]
    return (
        chunk_items,
        chunk_ranges,
        length_samples,
        token_lengths,
        total_len,
        total_tokens_est,
        short_count,
        duplicate_count,
        needs_review_count,
        auto_selected_strategy,
    )


def _build_preview_stats(
    *,
    chunk_ranges: list[tuple[int, int]],
    length_samples: list[int],
    token_lengths: list[int],
    total_len: int,
    total_tokens_est: int,
    short_count: int,
    duplicate_count: int,
    total_characters: int,
    unit: Literal["chars", "tokens"],
) -> tuple[ChunkPreviewStats, dict[str, Any] | None]:
    coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
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
    if not sorted_lengths:
        return ChunkPreviewStats(unit=unit, **coverage), token_stats

    def _pct(percentile: int) -> int:
        pos = int((max(0, min(100, int(percentile))) / 100.0) * (len(sorted_lengths) - 1))
        pos = max(0, min(len(sorted_lengths) - 1, pos))
        return int(sorted_lengths[pos] or 0)

    histogram = _compute_chunk_length_histogram(sorted_lengths, unit=unit, target_bins=8)
    coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
    return (
        ChunkPreviewStats(
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
        ),
        token_stats,
    )


def _split_preview_documents(
    *,
    documents: list[Document],
    config: PreviewRequestConfig,
    pipeline_state: PreviewPipelineState,
    by_sha: bool,
) -> tuple[list[Document], int, int, bool]:
    chunker, strategy_params_out = _create_preview_chunker(config=config, pipeline_state=pipeline_state)
    pipeline_state.strategy_params_out = strategy_params_out
    chunk_started = time.perf_counter()
    chunks = chunker.split_documents(documents)
    chunking_duration_ms = int(max(0.0, (time.perf_counter() - chunk_started) * 1000.0))
    chunks, total_chunks_full, chunks_truncated = _filter_preview_chunks(
        documents=documents,
        chunks=chunks,
        pipeline_state=pipeline_state,
        by_sha=by_sha,
        max_chunks=config.max_chunks,
        warnings_out=config.warnings_out,
    )
    return chunks, chunking_duration_ms, total_chunks_full, chunks_truncated


def _preview_parse_cache_enabled(
    *,
    config: PreviewRequestConfig,
    file_sha256: str | None,
    cache_ttl_sec: int,
    cache_max_entries: int,
) -> bool:
    return bool(file_sha256) and config.use_parse_cache and cache_ttl_sec > 0 and cache_max_entries > 0


def _preview_parse_cache_key(
    *,
    tenant_id: UUID,
    account_id: str,
    file_sha256: str,
    file_ext: str,
    parser_backend: str,
    cache_version: str,
) -> str:
    return (
        f"parse:{str(tenant_id)}:{str(account_id)}:{str(file_sha256)}:{str(file_ext)}:"
        f"{str(parser_backend or '').strip().lower()}:{cache_version}"
    )


def _store_preview_parse_cache(
    *,
    cache_key: str | None,
    parsed_docs_payload: list[dict[str, Any]],
    resolved_backend: str,
    file_sha256: str | None,
    parser_backend: str,
    cache_ttl_sec: int,
    cache_max_entries: int,
    cache_max_doc_chars: int,
) -> None:
    if not cache_key:
        return
    total_chars = sum(len(str(item.get("page_content") or "")) for item in (parsed_docs_payload or []))
    if cache_max_doc_chars > 0 and total_chars > cache_max_doc_chars:
        return
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


async def _parse_uncached_preview_documents(
    *,
    documents_module: Any,
    temp_path: Path,
    file_ext: str,
    tenant_id: UUID,
    account_id: str,
    request: Request,
    config: PreviewRequestConfig,
) -> tuple[list[dict[str, Any]], str, int]:
    parse_started = time.perf_counter()
    if _should_inline_preview_parse(file_ext):
        parsed_documents, backend, _provenance = parser_factory.parse_with_provenance(
            temp_path,
            parser_backend=config.parser_backend,
            tenant_id=str(tenant_id),
        )
        parsed_documents = _materialize_extracted_images_for_preview(
            parsed_documents,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        parsed_documents = _materialize_local_images_for_preview(
            parsed_documents,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        duration_ms = int(max(0.0, (time.perf_counter() - parse_started) * 1000.0))
        return _serialize_preview_parse_documents(parsed_documents), str(backend or config.parser_backend), duration_ms

    parsed = await documents_module.run_subprocess_worker(
        tenant_id=tenant_id,
        payload={
            "action": "parse_documents",
            "tenant_id": str(tenant_id),
            "account_id": str(account_id),
            "file_path": str(temp_path),
            "parser_backend": config.parser_backend,
            "mode": "preview",
        },
        disconnect_check=request.is_disconnected,
        timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
    )
    duration_ms = int(max(0.0, (time.perf_counter() - parse_started) * 1000.0))
    return (
        [item for item in (parsed.get("documents") or []) if isinstance(item, dict)],
        str(parsed.get("resolved_backend") or config.parser_backend),
        duration_ms,
    )


async def _load_preview_parsed_payload(
    *,
    documents_module: Any,
    temp_path: Path,
    file_ext: str,
    tenant_id: UUID,
    account_id: str,
    request: Request,
    config: PreviewRequestConfig,
    file_sha256: str | None,
) -> tuple[list[dict[str, Any]], str, bool, int | None, int]:
    cache_enabled = bool(getattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", False))
    cache_ttl_sec = int(getattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 0) or 0)
    cache_max_entries = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 0) or 0)
    cache_max_doc_chars = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_DOC_CHARS", 0) or 0)
    cache_version = str(getattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1") or "v1").strip() or "v1"
    cache_key: str | None = None
    parsed_docs_payload: list[dict[str, Any]] | None = None
    resolved_backend = str(config.parser_backend)
    parse_cache_hit = False
    parse_cache_age_ms: int | None = None
    parse_duration_ms = 0

    if cache_enabled and _preview_parse_cache_enabled(
        config=config,
        file_sha256=file_sha256,
        cache_ttl_sec=cache_ttl_sec,
        cache_max_entries=cache_max_entries,
    ):
        cache_key = _preview_parse_cache_key(
            tenant_id=tenant_id,
            account_id=account_id,
            file_sha256=str(file_sha256),
            file_ext=file_ext,
            parser_backend=config.parser_backend,
            cache_version=cache_version,
        )
        cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
        if cached is not None:
            parse_cache_hit = True
            parse_cache_age_ms = age_ms
            parsed_docs_payload = list(cached.documents or [])
            resolved_backend = str(cached.resolved_backend or config.parser_backend)

    if parsed_docs_payload is None:
        lock = preview_parse_locks.get(cache_key) if cache_key else None
        if lock is not None:
            async with lock:
                cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
                if cached is not None:
                    return (
                        list(cached.documents or []),
                        str(cached.resolved_backend or config.parser_backend),
                        True,
                        age_ms,
                        0,
                    )
                parsed_docs_payload, resolved_backend, parse_duration_ms = await _parse_uncached_preview_documents(
                    documents_module=documents_module,
                    temp_path=temp_path,
                    file_ext=file_ext,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    request=request,
                    config=config,
                )
                _store_preview_parse_cache(
                    cache_key=cache_key,
                    parsed_docs_payload=parsed_docs_payload,
                    resolved_backend=resolved_backend,
                    file_sha256=file_sha256,
                    parser_backend=config.parser_backend,
                    cache_ttl_sec=cache_ttl_sec,
                    cache_max_entries=cache_max_entries,
                    cache_max_doc_chars=cache_max_doc_chars,
                )
        else:
            parsed_docs_payload, resolved_backend, parse_duration_ms = await _parse_uncached_preview_documents(
                documents_module=documents_module,
                temp_path=temp_path,
                file_ext=file_ext,
                tenant_id=tenant_id,
                account_id=account_id,
                request=request,
                config=config,
            )
            _store_preview_parse_cache(
                cache_key=cache_key,
                parsed_docs_payload=parsed_docs_payload,
                resolved_backend=resolved_backend,
                file_sha256=file_sha256,
                parser_backend=config.parser_backend,
                cache_ttl_sec=cache_ttl_sec,
                cache_max_entries=cache_max_entries,
                cache_max_doc_chars=cache_max_doc_chars,
            )
    return parsed_docs_payload or [], resolved_backend, parse_cache_hit, parse_cache_age_ms, parse_duration_ms


async def _build_uploaded_preview_execution_state(
    *,
    documents_module: Any,
    request: Request,
    temp_path: Path,
    file_ext: str,
    tenant_id: UUID,
    account_id: str,
    config: PreviewRequestConfig,
    pipeline_state: PreviewPipelineState,
    file_sha256: str | None,
) -> PreviewExecutionState:
    if config.resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        integrated_started = time.perf_counter()
        result = await documents_module.run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "integrated_chunk",
                "tenant_id": str(tenant_id),
                "account_id": str(account_id),
                "file_path": str(temp_path),
                "strategy": config.resolved_chunk_strategy,
                "mode": "preview",
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
        chunks = _materialize_preview_documents(result.get("documents") if isinstance(result, dict) else [])
        chunks, governance_duration_ms = _apply_preview_governance(chunks, pipeline_state=pipeline_state)
        return PreviewExecutionState(
            documents=[],
            chunks=chunks,
            resolved_backend="integrated",
            parse_cache_hit=False,
            parse_cache_age_ms=None,
            parse_duration_ms=None,
            governance_duration_ms=governance_duration_ms,
            chunking_duration_ms=int(max(0.0, (time.perf_counter() - integrated_started) * 1000.0)),
            total_chunks_full=len(chunks),
            chunks_truncated=False,
        )

    (
        parsed_docs_payload,
        resolved_backend,
        parse_cache_hit,
        parse_cache_age_ms,
        parse_duration_ms,
    ) = await _load_preview_parsed_payload(
        documents_module=documents_module,
        temp_path=temp_path,
        file_ext=file_ext,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        config=config,
        file_sha256=file_sha256,
    )
    documents = _materialize_preview_documents(parsed_docs_payload)
    documents, governance_duration_ms = _apply_preview_governance(documents, pipeline_state=pipeline_state)
    _ensure_preview_page_indices(documents)
    chunks, chunking_duration_ms, total_chunks_full, chunks_truncated = _split_preview_documents(
        documents=documents,
        config=config,
        pipeline_state=pipeline_state,
        by_sha=False,
    )
    return PreviewExecutionState(
        documents=documents,
        chunks=chunks,
        resolved_backend=resolved_backend,
        parse_cache_hit=parse_cache_hit,
        parse_cache_age_ms=parse_cache_age_ms,
        parse_duration_ms=parse_duration_ms,
        governance_duration_ms=governance_duration_ms,
        chunking_duration_ms=chunking_duration_ms,
        total_chunks_full=total_chunks_full,
        chunks_truncated=chunks_truncated,
    )


def _clean_preview_original_text(original_text_value: str | None) -> str | None:
    if original_text_value is None or "@@" not in original_text_value or "##" not in original_text_value:
        return None
    if not POSITION_TAG_RE.search(original_text_value):
        return None
    return POSITION_TAG_RE.sub("", original_text_value)


async def _run_uploaded_chunk_preview(
    *,
    documents_module: Any,
    request: Request,
    response: Response,
    file: UploadFile,
    params: ChunkPreviewRequestFields,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    config: PreviewRequestConfig,
    preview_started: float,
    temp_path: Path,
    file_ext: str,
) -> ChunkPreviewResponse:
    upload_started = time.perf_counter()
    file_size, file_sha256 = await save_upload_file_with_hash(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)
    upload_duration_ms = int(max(0.0, (time.perf_counter() - upload_started) * 1000.0))
    file_size = int(file_size or 0)
    if file_size <= 0:
        with contextlib.suppress(OSError):
            file_size = int(temp_path.stat().st_size)
    dataset_meta = _resolve_preview_dataset_meta(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=params.dataset_id,
    )
    pipeline_state = _resolve_preview_pipeline_state(config=config, dataset_meta=dataset_meta, params=params)
    execution_state = await _build_uploaded_preview_execution_state(
        documents_module=documents_module,
        request=request,
        temp_path=temp_path,
        file_ext=file_ext,
        tenant_id=tenant_id,
        account_id=account_id,
        config=config,
        pipeline_state=pipeline_state,
        file_sha256=file_sha256,
    )
    return _build_chunk_preview_response(
        response=response,
        config=config,
        pipeline_state=pipeline_state,
        execution_state=execution_state,
        preview_started=preview_started,
        upload_duration_ms=upload_duration_ms,
        filename=file.filename,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_sha256=file_sha256,
    )


def _preview_failure_detail(exc: Exception, *, production_message: str) -> str:
    msg = (str(exc) or "").strip()
    if not msg:
        msg = exc.__class__.__name__
    msg = msg[:200]
    return production_message if is_production_env() else f"{production_message}: {msg}"


async def _execute_preview_chunking(
    *,
    documents_module: Any,
    request: Request,
    response: Response,
    file: UploadFile,
    params: ChunkPreviewRequestFields,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> ChunkPreviewResponse:
    DatasetService.ensure_member(db, tenant_id, account_id)
    file.filename = _sanitize_filename(file.filename)
    preview_started = time.perf_counter()
    config = _build_preview_request_config(
        chunk_size=params.chunk_size,
        chunk_overlap=params.chunk_overlap,
        include_original_text=params.include_original_text,
        include_chunks=params.include_chunks,
        include_review_signals=params.include_review_signals,
        original_text_max_chars=params.original_text_max_chars,
        max_chunks=params.max_chunks,
        use_parse_cache=params.use_parse_cache,
        parser_backend=params.parser_backend,
        chunk_strategy=params.chunk_strategy,
        child_ratio=params.child_ratio,
        min_child_size=params.min_child_size,
    )
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
    try:
        return await _run_uploaded_chunk_preview(
            documents_module=documents_module,
            request=request,
            response=response,
            file=file,
            params=params,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            config=config,
            preview_started=preview_started,
            temp_path=temp_path,
            file_ext=file_ext,
        )
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def _set_preview_server_timing(
    response: Response,
    *,
    upload_duration_ms: int | None,
    parse_duration_ms: int | None,
    governance_duration_ms: int,
    chunking_duration_ms: int,
    stats_duration_ms: int,
    preview_duration_ms: int,
) -> None:
    with contextlib.suppress(Exception):
        timing_parts: list[str] = []
        if upload_duration_ms is not None:
            timing_parts.append(f"upload;dur={int(upload_duration_ms)}")
        if parse_duration_ms is not None:
            timing_parts.append(f"parse;dur={int(parse_duration_ms)}")
        timing_parts.append(f"govern;dur={int(governance_duration_ms)}")
        timing_parts.append(f"chunk;dur={int(chunking_duration_ms)}")
        timing_parts.append(f"stats;dur={int(stats_duration_ms)}")
        timing_parts.append(f"total;dur={int(preview_duration_ms)}")
        if timing_parts:
            response.headers["Server-Timing"] = ", ".join(timing_parts)


def _build_chunk_preview_response(
    *,
    response: Response,
    config: PreviewRequestConfig,
    pipeline_state: PreviewPipelineState,
    execution_state: PreviewExecutionState,
    preview_started: float,
    upload_duration_ms: int | None,
    filename: str,
    file_type: str,
    file_size: int,
    file_sha256: str | None,
) -> ChunkPreviewResponse:
    (
        integrated_chunk_start_map,
        page_start_map,
        page_index_start_map,
        total_characters,
        original_text_value,
    ) = _build_preview_text_context(
        documents=execution_state.documents,
        chunks=execution_state.chunks,
        include_original=config.include_original,
        original_text_max_chars=config.original_text_max_chars,
    )
    stats_started = time.perf_counter()
    unit: Literal["chars", "tokens"] = "tokens" if config.resolved_chunk_strategy == "langchain_token" else "chars"
    (
        chunk_items,
        chunk_ranges,
        length_samples,
        token_lengths,
        total_len,
        total_tokens_est,
        short_count,
        duplicate_count,
        needs_review_count,
        auto_selected_strategy,
    ) = _collect_preview_chunk_metrics(
        chunks=execution_state.chunks,
        config=config,
        integrated_chunk_start_map=integrated_chunk_start_map,
        page_start_map=page_start_map,
        page_index_start_map=page_index_start_map,
    )
    if needs_review_count > 0:
        config.warnings_out.append(f"{int(needs_review_count)} chunks flagged needs_review (semantic heuristics)")
    stats, token_stats = _build_preview_stats(
        chunk_ranges=chunk_ranges,
        length_samples=length_samples,
        token_lengths=token_lengths,
        total_len=total_len,
        total_tokens_est=total_tokens_est,
        short_count=short_count,
        duplicate_count=duplicate_count,
        total_characters=total_characters,
        unit=unit,
    )
    stats_duration_ms = int(max(0.0, (time.perf_counter() - stats_started) * 1000.0))
    original_text_truncated = _is_original_preview_text_truncated(
        include_original=config.include_original,
        original_text_value=original_text_value,
        total_characters=int(total_characters or 0),
        original_text_max_chars=config.original_text_max_chars,
    )
    quality_gate, recommendations, recommendation_patches = _compute_chunk_preview_quality(
        stats=stats,
        total_chunks=len(execution_state.chunks),
        total_characters=int(total_characters or 0),
        chunk_size=config.chunk_size,
        chunk_overlap=config.effective_chunk_overlap,
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated,
        original_text_max_chars=config.original_text_max_chars,
    )
    review_signals: ChunkPreviewReviewSignals | None = None
    if config.include_review_signals:
        signals_strategy = auto_selected_strategy or config.resolved_chunk_strategy
        with contextlib.suppress(Exception):
            review_signals = _compute_chunk_preview_review_signals(
                chunk_items=chunk_items,
                unit=unit,
                strategy=str(signals_strategy or ""),
            )
    preview_duration_ms = int(max(0.0, (time.perf_counter() - preview_started) * 1000.0))
    _set_preview_server_timing(
        response,
        upload_duration_ms=upload_duration_ms,
        parse_duration_ms=execution_state.parse_duration_ms,
        governance_duration_ms=execution_state.governance_duration_ms,
        chunking_duration_ms=execution_state.chunking_duration_ms,
        stats_duration_ms=stats_duration_ms,
        preview_duration_ms=preview_duration_ms,
    )
    return ChunkPreviewResponse(
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        file_sha256=file_sha256,
        parse_cache_hit=bool(execution_state.parse_cache_hit),
        parse_cache_age_ms=execution_state.parse_cache_age_ms,
        preview_duration_ms=preview_duration_ms,
        upload_duration_ms=upload_duration_ms,
        parse_duration_ms=execution_state.parse_duration_ms,
        governance_duration_ms=int(execution_state.governance_duration_ms),
        chunking_duration_ms=int(execution_state.chunking_duration_ms),
        stats_duration_ms=int(stats_duration_ms),
        total_chunks=len(execution_state.chunks),
        total_chunks_full=int(execution_state.total_chunks_full),
        chunks_truncated=bool(execution_state.chunks_truncated),
        chunks_max_count=config.max_chunks,
        total_characters=total_characters,
        params=ChunkPreviewParams(
            chunk_size=config.chunk_size,
            chunk_overlap=config.effective_chunk_overlap,
            unit=unit,
            strategy_params=pipeline_state.strategy_params_out,
        ),
        chunks=(chunk_items if config.include_chunks else []),
        stats=stats,
        chunking_stats_tokens=token_stats,
        auto_selected_strategy=auto_selected_strategy,
        warnings=config.warnings_out,
        review_signals=review_signals,
        quality_gate=quality_gate,
        recommendations=recommendations,
        recommendation_patches=recommendation_patches,
        original_text=original_text_value,
        original_text_cleaned=_clean_preview_original_text(original_text_value),
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated,
        original_text_max_chars=config.original_text_max_chars,
        parser_backend=execution_state.resolved_backend,
        chunk_strategy=config.resolved_chunk_strategy,
    )


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
        include_original and original_text_value is None and total_characters > int(original_text_max_chars or 0)
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

    try:
        return await _execute_preview_chunking(
            documents_module=documents_module,
            request=request,
            response=response,
            file=file,
            params=params,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
        )

    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.error("Subprocess worker failed during chunk preview: %s", str(e)[:200])
        raise HTTPException(
            status_code=500,
            detail=_preview_failure_detail(e, production_message="Failed to preview chunking"),
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error during chunk preview: %s", str(e)[:200])
        raise HTTPException(
            status_code=500,
            detail=_preview_failure_detail(e, production_message="Failed to preview chunking"),
        ) from e


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

    preview_started = time.perf_counter()
    sha = str(file_fields.file_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(status_code=400, detail="file_sha256 must be a 64-char hex string")

    raw_type = str(file_fields.file_type or "").strip().lower().lstrip(".")
    if not raw_type and file_fields.filename:
        raw_type = Path(str(file_fields.filename)).suffix.lower().lstrip(".")
    if not raw_type:
        raise HTTPException(status_code=400, detail="file_type is required")
    file_ext = f".{raw_type}"
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    safe_name = _sanitize_filename(file_fields.filename or f"{sha[:8]}{file_ext}")
    config = _build_preview_request_config(
        chunk_size=params.chunk_size,
        chunk_overlap=params.chunk_overlap,
        include_original_text=params.include_original_text,
        include_chunks=params.include_chunks,
        include_review_signals=params.include_review_signals,
        original_text_max_chars=params.original_text_max_chars,
        max_chunks=params.max_chunks,
        use_parse_cache=params.use_parse_cache,
        parser_backend=params.parser_backend,
        chunk_strategy=params.chunk_strategy,
        child_ratio=params.child_ratio,
        min_child_size=params.min_child_size,
    )

    if config.resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail="Integrated pipeline strategies do not support by-sha preview; please upload the file",
        )

    cache_enabled = bool(getattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", False))
    cache_ttl_sec = int(getattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 0) or 0)
    cache_max_entries = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 0) or 0)
    cache_version = str(getattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1") or "v1").strip() or "v1"
    if not (cache_enabled and config.use_parse_cache and cache_ttl_sec > 0 and cache_max_entries > 0):
        raise HTTPException(status_code=400, detail="parse cache disabled; please upload the file")

    cache_key = (
        f"parse:{str(tenant_id)}:{str(account_id)}:{sha}:{str(file_ext)}:"
        f"{str(config.parser_backend or '').strip().lower()}:{cache_version}"
    )

    cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
    if cached is None:
        raise HTTPException(status_code=404, detail="Parse cache miss. Upload the file once to warm the cache.")

    dataset_meta = _resolve_preview_dataset_meta(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=params.dataset_id,
    )
    pipeline_state = _resolve_preview_pipeline_state(config=config, dataset_meta=dataset_meta, params=params)
    documents = _materialize_preview_documents(list(cached.documents or []))
    documents, governance_duration_ms = _apply_preview_governance(documents, pipeline_state=pipeline_state)
    _ensure_preview_page_indices(documents)
    chunker, strategy_params_out = _create_preview_chunker(config=config, pipeline_state=pipeline_state)
    pipeline_state.strategy_params_out = strategy_params_out
    _chunk_started = time.perf_counter()
    chunks = chunker.split_documents(documents)
    chunking_duration_ms = int(max(0.0, (time.perf_counter() - _chunk_started) * 1000.0))
    chunks, total_chunks_full, chunks_truncated = _filter_preview_chunks(
        documents=documents,
        chunks=chunks,
        pipeline_state=pipeline_state,
        by_sha=True,
        max_chunks=config.max_chunks,
        warnings_out=config.warnings_out,
    )
    execution_state = PreviewExecutionState(
        documents=documents,
        chunks=chunks,
        resolved_backend=str(cached.resolved_backend or config.parser_backend),
        parse_cache_hit=True,
        parse_cache_age_ms=age_ms,
        parse_duration_ms=0,
        governance_duration_ms=governance_duration_ms,
        chunking_duration_ms=chunking_duration_ms,
        total_chunks_full=total_chunks_full,
        chunks_truncated=chunks_truncated,
    )
    return _build_chunk_preview_response(
        response=response,
        config=config,
        pipeline_state=pipeline_state,
        execution_state=execution_state,
        preview_started=preview_started,
        upload_duration_ms=0,
        filename=safe_name,
        file_type=file_ext.lstrip("."),
        file_size=int(file_fields.file_size or 0),
        file_sha256=sha,
    )
