import contextlib
import hashlib
import json
import re
import shutil
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, UploadFile
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    ChunkPreviewByShaForm,
    ChunkPreviewFormFields,
    ChunkPreviewItem,
    ChunkPreviewParams,
    ChunkPreviewQuery,
    ChunkPreviewResponse,
    ChunkPreviewReviewSignals,
    ChunkPreviewStats,
    ChunkPreviewUploadForm,
    PipelineOptionOverrides,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES, sanitize_upload_filename, save_upload_file_with_hash
from app.api.utils.document_pipeline_input import (
    CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
    parse_pipeline_json,
    to_pipeline_options,
)
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.env import is_production_env
from app.core.token_utils import estimate_tokens, num_tokens_from_string
from app.parsing.artifact_stats import POSITION_TAG_RE
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.rag.chunking.base import BaseChunker
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.strategies.separator import SeparatorChunker
from app.rag.core.logging import get_logger
from app.rag.preprocessing.cleaning import RegexRule
from app.rag.preprocessing.processor import GovernanceCleanOptions, governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services import dataset_service
from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges
from app.services.document_governance import build_governance_options
from app.services.document_preview_utils import (
    DATA_IMAGE_PREFIX,
    MINIO_IMAGE_REF_RE,
    PREVIEW_IMAGE_REF_RE,
    _compute_chunk_length_histogram,
    _compute_chunk_preview_quality,
    _compute_chunk_preview_review_signals,
    _ensure_preview_page_indices,
    _materialize_extracted_images_for_preview,
    _materialize_local_images_for_preview,
    _merge_small_chunks_preview,
)
from app.services.pipeline_config import resolve_pipeline_effective, validate_pipeline_execution
from app.services.preview_cache import ParseCacheEntry, preview_parse_cache, preview_parse_locks
from app.types.pipeline import PipelineEffective

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger("api.documents")


def _coerce_bool_preview(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _coerce_int_preview(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _coerce_float_preview(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _decode_escaped_input_preview(value: str) -> str:
    """
    Best-effort decode for user input strings like "\\n\\n" / "\\t" / "\\u4e2d".

    Keep aligned with frontend behavior and ingestion SeparatorChunker handling.
    """
    raw = value
    if not raw:
        return raw
    try:
        escaped = raw.replace('"', '\\"')
        return json.loads(f'"{escaped}"')
    except json.JSONDecodeError:
        return raw


def _filter_chunker_kwargs_for_strategy(strategy: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep constructor options only; preview does not enable factory-level metadata enrichment."""
    if not kwargs:
        return {}
    chunker_cls = chunker_factory.SUPPORTED_STRATEGIES.get(strategy)
    if chunker_cls is None:
        return {}

    import inspect

    sig = inspect.signature(chunker_cls.__init__)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return dict(kwargs)
    accepted = {
        p.name
        for p in sig.parameters.values()
        if p.name not in {"self", "chunk_size", "chunk_overlap"}
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in kwargs.items() if k in accepted}


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


class _SeparatorPreviewConfig(TypedDict):
    preset: str
    separator: str
    keep_separator: bool
    separator_max_chunk_size: int


@dataclass
class PreviewPipelineState:
    pipeline_effective: PipelineEffective
    chunker_kwargs: dict[str, Any]
    separator_config: _SeparatorPreviewConfig | None
    strategy_params_out: dict[str, Any]
    governance_options: GovernanceCleanOptions
    governance_rules: list[RegexRule] | None


class _PreviewPageText(TypedDict):
    text: str
    page: Any
    page_index: Any
    start: int


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


@dataclass
class PreviewChunkMetrics:
    chunk_items: list[ChunkPreviewItem]
    chunk_ranges: list[tuple[int, int]]
    length_samples: list[int]
    token_lengths: list[int]
    total_len: int
    total_tokens_est: int
    short_count: int
    duplicate_count: int
    needs_review_count: int
    auto_selected_strategy: str | None


def _build_preview_request_config(query: ChunkPreviewQuery, params: ChunkPreviewFormFields) -> PreviewRequestConfig:
    try:
        resolved_chunk_strategy = chunker_factory.resolve_strategy(params.chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chunk_size = query.chunk_size
    chunk_overlap = query.chunk_overlap
    min_chunk_size = 50 if resolved_chunk_strategy == "langchain_token" else 100
    if chunk_size < min_chunk_size or chunk_size > 4000:
        raise HTTPException(status_code=400, detail=f"chunk_size must be between {min_chunk_size} and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if resolved_chunk_strategy != "separator" and chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL)
    if query.original_text_max_chars < 0 or query.original_text_max_chars > 2_000_000:
        raise HTTPException(status_code=400, detail="original_text_max_chars must be between 0 and 2000000")
    if query.max_chunks < 0 or query.max_chunks > 20000:
        raise HTTPException(status_code=400, detail="max_chunks must be between 0 and 20000")

    effective_chunk_overlap = 0 if resolved_chunk_strategy == "separator" else chunk_overlap
    warnings_out: list[str] = []
    if resolved_chunk_strategy == "separator" and chunk_overlap != effective_chunk_overlap:
        warnings_out.append("separator strategy ignores chunk_overlap; using 0")
    if (
        params.child_ratio is not None or params.min_child_size is not None
    ) and resolved_chunk_strategy != "parent_child":
        warnings_out.append(
            f"strategy params child_ratio/min_child_size ignored for chunk_strategy={resolved_chunk_strategy}"
        )
    return PreviewRequestConfig(
        chunk_size=chunk_size,
        effective_chunk_overlap=effective_chunk_overlap,
        include_original=query.include_original_text and query.original_text_max_chars > 0,
        include_chunks=query.include_chunks,
        include_review_signals=query.include_review_signals,
        original_text_max_chars=query.original_text_max_chars,
        max_chunks=query.max_chunks,
        use_parse_cache=query.use_parse_cache,
        parser_backend=params.parser_backend,
        resolved_chunk_strategy=resolved_chunk_strategy,
        warnings_out=warnings_out,
    )


def _ensure_preview_member(*, tenant_id: UUID, account_id: str) -> None:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)


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
        parsed_id = UUID(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ds = dataset_service.get_dataset(db, tenant_id, parsed_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)
    return dict(ds.dataset_metadata or {})


def _load_preview_dataset_meta(*, tenant_id: UUID, account_id: str, dataset_id: str | None) -> dict[str, Any]:
    with SessionLocal() as db:
        return _resolve_preview_dataset_meta(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)


def _resolve_parent_child_chunker_kwargs(
    *,
    pipeline_strategy_params: dict[str, Any],
    child_ratio: float | None,
    min_child_size: int | None,
    chunk_size: int,
    warnings_out: list[str],
) -> dict[str, Any]:
    merged = dict(pipeline_strategy_params)
    if child_ratio is not None:
        merged["child_ratio"] = child_ratio
    if min_child_size is not None:
        merged["min_child_size"] = min_child_size

    out: dict[str, Any] = {}
    if "child_ratio" in merged:
        ratio = _coerce_float_preview(merged.get("child_ratio"))
        if ratio is None:
            raise HTTPException(status_code=400, detail="child_ratio must be a float")
        if not 0.05 <= ratio <= 1.0:
            raise HTTPException(status_code=400, detail="child_ratio must be between 0.05 and 1.0")
        out["child_ratio"] = ratio
    if "min_child_size" in merged:
        min_size = _coerce_int_preview(merged.get("min_child_size"))
        if min_size is None:
            raise HTTPException(status_code=400, detail="min_child_size must be an int")
        if min_size < 50 or min_size > 4000:
            raise HTTPException(status_code=400, detail="min_child_size must be between 50 and 4000")
        if min_size > chunk_size:
            warnings_out.append("min_child_size > chunk_size; clamping to chunk_size")
            min_size = chunk_size
        out["min_child_size"] = min_size
    return out


def _resolve_separator_chunker_state(
    *,
    pipeline_strategy_params: dict[str, Any],
    separator_preset: str | None,
    separator: str | None,
    keep_separator: bool | None,
    separator_max_chunk_size: int | None,
) -> _SeparatorPreviewConfig:
    merged = dict(pipeline_strategy_params)
    if separator_preset is not None:
        merged["separator_preset"] = separator_preset
    if separator is not None:
        merged["separator"] = separator
    if keep_separator is not None:
        merged["keep_separator"] = keep_separator
    if separator_max_chunk_size is not None:
        merged["separator_max_chunk_size"] = separator_max_chunk_size

    raw_preset = merged.get("separator_preset")
    preset = "paragraph" if raw_preset is None else raw_preset.strip() or "paragraph"
    if preset != "custom":
        separator_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
        if separator_value is None:
            raise HTTPException(status_code=400, detail=f"Invalid separator_preset: {preset}")
    else:
        raw = merged.get("separator")
        if raw is None:
            raw = merged.get("separator_custom")
        separator_value = _decode_escaped_input_preview("\n\n" if raw is None or raw == "" else raw)

    keep_sep_norm = _coerce_bool_preview(merged.get("keep_separator"))
    keep_sep_bool = True if keep_sep_norm is None else keep_sep_norm
    max_chunk_size = merged.get("separator_max_chunk_size")
    if max_chunk_size is None:
        max_chunk_size = merged.get("max_chunk_size")
    max_chunk_size_int = _coerce_int_preview(max_chunk_size) or 0
    return {
        "preset": preset,
        "separator": separator_value,
        "keep_separator": keep_sep_bool,
        "separator_max_chunk_size": max_chunk_size_int,
    }


def _resolve_preview_pipeline_state(
    *,
    config: PreviewRequestConfig,
    dataset_meta: dict[str, Any],
    params: ChunkPreviewFormFields,
) -> PreviewPipelineState:
    try:
        pipeline_options = to_pipeline_options(
            pipeline=parse_pipeline_json(params.pipeline),
            overrides=PipelineOptionOverrides(
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
            ),
        )
        pipeline_effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=pipeline_options,
        )
        validate_pipeline_execution(pipeline_effective)
        pipeline_strategy_params = dict(pipeline_effective.chunk_strategy_params or {})
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
            chunker_kwargs = {}
            separator_config = _resolve_separator_chunker_state(
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
        extra_rules = list(pipeline_effective.governance_regex_rules or [])
        combined_rules = build_governance_rules(extra_rules) if extra_rules else None
        return PreviewPipelineState(
            pipeline_effective=pipeline_effective,
            chunker_kwargs=chunker_kwargs,
            separator_config=separator_config,
            strategy_params_out={},
            governance_options=build_governance_options(pipeline_effective, remove_common_lines=False),
            governance_rules=combined_rules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _materialize_preview_documents(parsed_docs_payload: list[dict[str, Any]] | None) -> list[Document]:
    return [
        Document(
            page_content=item["page_content"],
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            id=item.get("id") if isinstance(item.get("id"), str) else None,
        )
        for item in (parsed_docs_payload if parsed_docs_payload is not None else [])
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
        rules=pipeline_state.governance_rules,
        options=pipeline_state.governance_options,
    )
    duration_ms = int(max(0.0, (time.perf_counter() - started_at) * 1000.0))
    return cleaned_documents, duration_ms


def _create_preview_chunker(
    *,
    config: PreviewRequestConfig,
    pipeline_state: PreviewPipelineState,
) -> tuple[BaseChunker, dict[str, Any]]:
    if config.resolved_chunk_strategy == "separator":
        separator_config = pipeline_state.separator_config
        if separator_config is None:
            raise ValueError("separator chunk strategy requires separator_config")
        strategy_params_out = dict(separator_config)
        chunker = SeparatorChunker(
            chunk_size=config.chunk_size,
            chunk_overlap=config.effective_chunk_overlap,
            separator=separator_config["separator"],
            keep_separator=separator_config["keep_separator"],
            max_chunk_size=separator_config["separator_max_chunk_size"],
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
        strategy_params_out = {
            "child_ratio": chunker.child_ratio,
            "min_child_size": chunker.min_child_size,
            "child_size": chunker.child_size,
            "child_overlap": chunker.child_overlap,
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
    merge_min = max(0, (pipeline_state.pipeline_effective.chunk_merge_small_min_chars or 0))
    if merge_min > 0 and documents and chunks:
        chunks = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=merge_min)

    min_chars = max(0, settings.CHUNK_MIN_CHARS)
    if min_chars > 0 and chunks:
        before = len(chunks)
        original_chunks = chunks
        filtered: list[Document] = []
        for chunk in original_chunks:
            content = (chunk.page_content).strip()
            if len(content) >= min_chars:
                filtered.append(chunk)
                continue
            meta = chunk.metadata
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
            filtered = [max(original_chunks, key=lambda item: len((item.page_content).strip()))]
        chunks = filtered
        dropped = before - len(chunks)
        if dropped:
            label = "Chunk preview(by-sha)" if by_sha else "Chunk preview"
            logger.info("%s dropped %s short chunks (<%s chars)", label, dropped, min_chars)

    total_chunks_full = len(chunks)
    chunks_truncated = False
    if max_chunks > 0 and len(chunks) > max_chunks:
        chunks_truncated = True
        warnings_out.append(f"chunks truncated to max_chunks={max_chunks} (full={total_chunks_full})")
        chunks = chunks[:max_chunks]
    return chunks, total_chunks_full, chunks_truncated


def _build_preview_text_context(
    *,
    documents: list[Document],
    chunks: list[Document],
    include_original: bool,
    original_text_max_chars: int,
) -> tuple[dict[int, int], dict[object, int], dict[int, int], int, str | None]:
    if not documents:
        total_characters = sum(len(chunk.page_content) for chunk in chunks)
        total_characters += 2 * (len(chunks) - 1) if chunks else 0
        original_text_value = None
        if include_original and total_characters <= original_text_max_chars:
            original_text_value = "\n\n".join(chunk.page_content for chunk in chunks)
        integrated_map = {}
        current_pos = 0
        for idx, chunk in enumerate(chunks):
            integrated_map[idx] = current_pos
            current_pos += len(chunk.page_content) + 2
        return integrated_map, {}, {}, total_characters, original_text_value

    page_texts: list[_PreviewPageText] = []
    current_pos = 0
    for doc in documents:
        text = doc.page_content
        meta = doc.metadata
        page_texts.append(
            {
                "text": text,
                "page": meta.get("page") or meta.get("page_number"),
                "page_index": meta.get("page_index"),
                "start": current_pos,
            }
        )
        current_pos += len(text) + 1
    total_characters = sum(len(item["text"]) for item in page_texts) + max(0, len(page_texts) - 1)
    page_index_start_map = {
        int(item["page_index"]): item["start"] for item in page_texts if item["page_index"] is not None
    }
    page_start_map: dict[object, int] = {}
    for item in page_texts:
        page = item["page"]
        if page is not None and page not in page_start_map:
            page_start_map[page] = item["start"]
    original_text_value = None
    if include_original and total_characters <= original_text_max_chars:
        original_text_value = "\n".join(item["text"] for item in page_texts)
    return {}, page_start_map, page_index_start_map, total_characters, original_text_value


def _resolve_preview_chunk_offsets(
    *,
    idx: int,
    chunk: Document,
    integrated_chunk_start_map: dict[int, int],
    page_start_map: dict[object, int],
    page_index_start_map: dict[int, int],
) -> tuple[int, int, object | None]:
    content = chunk.page_content
    meta = chunk.metadata
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
            start_idx = doc_base + local
    end_idx = start_idx + len(content)
    if local_end is not None and idx not in integrated_chunk_start_map:
        with contextlib.suppress(Exception):
            end_local = int(local_end)
            end_idx = end_local if doc_base is None else doc_base + end_local
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
    score_chunk_semantic_quality: Callable[..., tuple[dict[str, Any], set[str]]],
    tokens_est: int,
) -> tuple[int, set[str] | None]:
    if not (config.include_chunks or config.include_review_signals) or idx >= 512:
        return 0, prev_token_set
    try:
        scores, prev_token_set = score_chunk_semantic_quality(
            content,
            tokens_est=tokens_est,
            prev_token_set=prev_token_set,
        )
        meta["semantic_quality"] = scores
        if scores["needs_review"]:
            meta["needs_review"] = True
            return 1, prev_token_set
    except Exception as exc:
        logger.debug("Preview semantic quality unavailable: chunk_index=%s error_type=%s", idx, type(exc).__name__)
    return 0, prev_token_set


def _collect_preview_chunk_metrics(
    *,
    chunks: list[Document],
    config: PreviewRequestConfig,
    integrated_chunk_start_map: dict[int, int],
    page_start_map: dict[object, int],
    page_index_start_map: dict[int, int],
) -> PreviewChunkMetrics:
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
        content = chunk.page_content
        meta = chunk.metadata
        tokens_est = _estimate_preview_tokens(content=content, resolved_chunk_strategy=config.resolved_chunk_strategy)
        needs_review_delta, prev_token_set = _annotate_preview_semantic_quality(
            content=content,
            meta=meta,
            config=config,
            idx=idx,
            prev_token_set=prev_token_set,
            score_chunk_semantic_quality=score_chunk_semantic_quality,
            tokens_est=tokens_est,
        )
        needs_review_count += needs_review_delta
        total_tokens_est += tokens_est
        if tokens_est > 0:
            token_lengths.append(tokens_est)
        unit_len = tokens_est if unit == "tokens" else len(content)
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
                    metadata=meta,
                )
            )
    if config.resolved_chunk_strategy == "auto" and auto_counts:
        auto_selected_strategy = auto_counts.most_common(1)[0][0]
    return PreviewChunkMetrics(
        chunk_items=chunk_items,
        chunk_ranges=chunk_ranges,
        length_samples=length_samples,
        token_lengths=token_lengths,
        total_len=total_len,
        total_tokens_est=total_tokens_est,
        short_count=short_count,
        duplicate_count=duplicate_count,
        needs_review_count=needs_review_count,
        auto_selected_strategy=auto_selected_strategy,
    )


def _build_preview_stats(
    *,
    metrics: PreviewChunkMetrics,
    total_characters: int,
    unit: Literal["chars", "tokens"],
) -> tuple[ChunkPreviewStats, dict[str, Any] | None]:
    coverage = compute_chunk_coverage_metrics_from_ranges(metrics.chunk_ranges, total_characters=total_characters)
    sorted_lengths = sorted(metrics.length_samples)
    token_stats: dict[str, Any] | None = None
    try:
        from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths
        from app.services.dataset_profile_utils import CHUNK_TOKEN_BINS

        token_stats = compute_chunking_stats_from_lengths(
            metrics.token_lengths,
            short_threshold=40,
            duplicate_count=metrics.duplicate_count,
            unit="tokens",
            bins=CHUNK_TOKEN_BINS,
        )
    except Exception as exc:
        logger.debug("Preview token stats unavailable: error_type=%s", type(exc).__name__)
    if not sorted_lengths:
        return ChunkPreviewStats(unit=unit, **coverage), token_stats

    def _pct(percentile: int) -> int:
        pos = int((max(0, min(100, percentile)) / 100.0) * (len(sorted_lengths) - 1))
        pos = max(0, min(len(sorted_lengths) - 1, pos))
        return sorted_lengths[pos]

    histogram = _compute_chunk_length_histogram(sorted_lengths, unit=unit, target_bins=8)
    return (
        ChunkPreviewStats(
            unit=unit,
            count=len(sorted_lengths),
            total=metrics.total_len,
            min=sorted_lengths[0],
            max=sorted_lengths[-1],
            avg=int(round(metrics.total_len / len(sorted_lengths))),
            median=_pct(50),
            p10=_pct(10),
            p90=_pct(90),
            p95=_pct(95),
            total_tokens_est=metrics.total_tokens_est,
            short_count=metrics.short_count,
            duplicate_count=metrics.duplicate_count,
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


def _preview_parse_cache_key(
    *,
    tenant_id: UUID,
    account_id: str,
    file_sha256: str,
    file_ext: str,
    parser_backend: str,
    cache_version: str,
) -> str:
    return f"parse:{tenant_id}:{account_id}:{file_sha256}:{file_ext}:{parser_backend.strip().lower()}:{cache_version}"


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
    total_chars = sum(len(item["page_content"]) for item in parsed_docs_payload)
    if cache_max_doc_chars > 0 and total_chars > cache_max_doc_chars:
        return
    preview_parse_cache.set(
        cache_key,
        ParseCacheEntry(
            created_at_monotonic=time.monotonic(),
            created_at_wall=time.time(),
            file_sha256=file_sha256,
            parser_backend=parser_backend,
            resolved_backend=resolved_backend,
            documents=list(parsed_docs_payload),
            total_chars=total_chars,
        ),
        ttl_sec=cache_ttl_sec,
        max_entries=cache_max_entries,
    )


async def _parse_uncached_preview_documents(
    *,
    temp_path: Path,
    file_ext: str,
    tenant_id: UUID,
    account_id: str,
    request: Request,
    config: PreviewRequestConfig,
) -> tuple[list[dict[str, Any]], str, int]:
    parse_started = time.perf_counter()
    normalized_ext = file_ext.strip().lower()
    if settings.PREVIEW_INLINE_TEXT_PARSE_ENABLED and (
        normalized_ext == ".md" or normalized_ext in parser_factory.PLAIN_TEXT_EXTENSIONS
    ):
        parsed_documents, backend, _provenance = await run_blocking_in_thread(
            parser_factory.parse_with_provenance,
            temp_path,
            parser_backend=config.parser_backend,
            tenant_id=str(tenant_id),
        )
        parsed_documents = await run_blocking_in_thread(
            _materialize_extracted_images_for_preview,
            parsed_documents,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        parsed_documents = await run_blocking_in_thread(
            _materialize_local_images_for_preview,
            parsed_documents,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        duration_ms = int(max(0.0, (time.perf_counter() - parse_started) * 1000.0))
        payload = await run_blocking_in_thread(_serialize_preview_parse_documents, parsed_documents)
        return payload, backend or config.parser_backend, duration_ms

    parsed = await run_subprocess_worker(
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
        timeout_sec=float(settings.TASK_JOB_TIMEOUT_SEC),
    )
    duration_ms = int(max(0.0, (time.perf_counter() - parse_started) * 1000.0))
    return (
        parsed["documents"],
        str(parsed.get("resolved_backend") or config.parser_backend),
        duration_ms,
    )


async def _load_preview_parsed_payload(
    *,
    temp_path: Path,
    file_ext: str,
    tenant_id: UUID,
    account_id: str,
    request: Request,
    config: PreviewRequestConfig,
    file_sha256: str | None,
) -> tuple[list[dict[str, Any]], str, bool, int | None, int]:
    cache_ttl_sec = settings.PREVIEW_PARSE_CACHE_TTL_SEC
    cache_max_entries = settings.PREVIEW_PARSE_CACHE_MAX_ENTRIES
    cache_max_doc_chars = settings.PREVIEW_PARSE_CACHE_MAX_DOC_CHARS
    cache_version = settings.PREVIEW_PARSE_CACHE_VERSION.strip() or "v1"
    cache_key = None
    if (
        settings.PREVIEW_PARSE_CACHE_ENABLED
        and file_sha256
        and config.use_parse_cache
        and cache_ttl_sec > 0
        and cache_max_entries > 0
    ):
        cache_key = _preview_parse_cache_key(
            tenant_id=tenant_id,
            account_id=account_id,
            file_sha256=file_sha256,
            file_ext=file_ext,
            parser_backend=config.parser_backend,
            cache_version=cache_version,
        )
        cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
        if cached is not None:
            return list(cached.documents), cached.resolved_backend or config.parser_backend, True, age_ms, 0

    async with contextlib.AsyncExitStack() as locks:
        if cache_key is not None:
            lock = preview_parse_locks.get(cache_key)
            if lock is not None:
                await locks.enter_async_context(lock)
                cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
                if cached is not None:
                    return list(cached.documents), cached.resolved_backend or config.parser_backend, True, age_ms, 0
        payload, backend, duration_ms = await _parse_uncached_preview_documents(
            temp_path=temp_path,
            file_ext=file_ext,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            config=config,
        )
        _store_preview_parse_cache(
            cache_key=cache_key,
            parsed_docs_payload=payload,
            resolved_backend=backend,
            file_sha256=file_sha256,
            parser_backend=config.parser_backend,
            cache_ttl_sec=cache_ttl_sec,
            cache_max_entries=cache_max_entries,
            cache_max_doc_chars=cache_max_doc_chars,
        )
        return payload, backend, False, None, duration_ms


async def _build_uploaded_preview_execution_state(
    *,
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
        result = await run_subprocess_worker(
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
            timeout_sec=float(settings.TASK_JOB_TIMEOUT_SEC),
        )
        chunks = _materialize_preview_documents(result["documents"])
        chunks, governance_duration_ms = await run_blocking_in_thread(
            _apply_preview_governance, chunks, pipeline_state=pipeline_state
        )
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
        temp_path=temp_path,
        file_ext=file_ext,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        config=config,
        file_sha256=file_sha256,
    )
    documents = _materialize_preview_documents(parsed_docs_payload)
    documents, governance_duration_ms = await run_blocking_in_thread(
        _apply_preview_governance, documents, pipeline_state=pipeline_state
    )
    _ensure_preview_page_indices(documents)
    chunks, chunking_duration_ms, total_chunks_full, chunks_truncated = await run_blocking_in_thread(
        _split_preview_documents,
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
    request: Request,
    response: Response,
    file: UploadFile,
    params: ChunkPreviewFormFields,
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
    dataset_meta = await run_blocking_in_thread(
        _load_preview_dataset_meta,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=params.dataset_id,
    )
    pipeline_state = _resolve_preview_pipeline_state(config=config, dataset_meta=dataset_meta, params=params)
    execution_state = await _build_uploaded_preview_execution_state(
        request=request,
        temp_path=temp_path,
        file_ext=file_ext,
        tenant_id=tenant_id,
        account_id=account_id,
        config=config,
        pipeline_state=pipeline_state,
        file_sha256=file_sha256,
    )
    return await run_blocking_in_thread(
        _build_chunk_preview_response,
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
    msg = (str(exc)).strip()
    if not msg:
        msg = exc.__class__.__name__
    msg = msg[:200]
    return production_message if is_production_env() else f"{production_message}: {msg}"


async def _execute_preview_chunking(
    *,
    request: Request,
    response: Response,
    file: UploadFile,
    params: ChunkPreviewFormFields,
    query: ChunkPreviewQuery,
    tenant_id: UUID,
    account_id: str,
) -> ChunkPreviewResponse:
    await run_blocking_in_thread(
        _ensure_preview_member,
        tenant_id=tenant_id,
        account_id=account_id,
    )
    file.filename = sanitize_upload_filename(file.filename)
    preview_started = time.perf_counter()
    config = _build_preview_request_config(query, params)
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    run_dir = upload_dir / uuid.uuid4().hex
    temp_path = run_dir / f"input{file_ext}"
    try:
        return await _run_uploaded_chunk_preview(
            request=request,
            response=response,
            file=file,
            params=params,
            tenant_id=tenant_id,
            account_id=account_id,
            config=config,
            preview_started=preview_started,
            temp_path=temp_path,
            file_ext=file_ext,
        )
    finally:
        with anyio.fail_after(5.0, shield=True):
            await run_blocking_in_thread(shutil.rmtree, run_dir, ignore_errors=True)


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
    timing_parts: list[str] = []
    if upload_duration_ms is not None:
        timing_parts.append(f"upload;dur={upload_duration_ms}")
    if parse_duration_ms is not None:
        timing_parts.append(f"parse;dur={parse_duration_ms}")
    timing_parts.append(f"govern;dur={governance_duration_ms}")
    timing_parts.append(f"chunk;dur={chunking_duration_ms}")
    timing_parts.append(f"stats;dur={stats_duration_ms}")
    timing_parts.append(f"total;dur={preview_duration_ms}")
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
    metrics = _collect_preview_chunk_metrics(
        chunks=execution_state.chunks,
        config=config,
        integrated_chunk_start_map=integrated_chunk_start_map,
        page_start_map=page_start_map,
        page_index_start_map=page_index_start_map,
    )
    if metrics.needs_review_count > 0:
        config.warnings_out.append(f"{metrics.needs_review_count} chunks flagged needs_review (semantic heuristics)")
    stats, token_stats = _build_preview_stats(
        metrics=metrics,
        total_characters=total_characters,
        unit=unit,
    )
    stats_duration_ms = int(max(0.0, (time.perf_counter() - stats_started) * 1000.0))
    original_text_truncated = (
        config.include_original and original_text_value is None and total_characters > config.original_text_max_chars
    )
    quality_gate, recommendations, recommendation_patches = _compute_chunk_preview_quality(
        stats=stats,
        total_chunks=len(execution_state.chunks),
        total_characters=total_characters,
        chunk_size=config.chunk_size,
        chunk_overlap=config.effective_chunk_overlap,
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated,
        original_text_max_chars=config.original_text_max_chars,
    )
    review_signals: ChunkPreviewReviewSignals | None = None
    if config.include_review_signals:
        signals_strategy = metrics.auto_selected_strategy or config.resolved_chunk_strategy
        try:
            review_signals = _compute_chunk_preview_review_signals(
                chunk_items=metrics.chunk_items,
                unit=unit,
                strategy=signals_strategy,
            )
        except Exception as exc:
            logger.debug("Preview review signals unavailable: error_type=%s", type(exc).__name__)
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
        parse_cache_hit=execution_state.parse_cache_hit,
        parse_cache_age_ms=execution_state.parse_cache_age_ms,
        preview_duration_ms=preview_duration_ms,
        upload_duration_ms=upload_duration_ms,
        parse_duration_ms=execution_state.parse_duration_ms,
        governance_duration_ms=execution_state.governance_duration_ms,
        chunking_duration_ms=execution_state.chunking_duration_ms,
        stats_duration_ms=stats_duration_ms,
        total_chunks=len(execution_state.chunks),
        total_chunks_full=execution_state.total_chunks_full,
        chunks_truncated=execution_state.chunks_truncated,
        chunks_max_count=config.max_chunks,
        total_characters=total_characters,
        params=ChunkPreviewParams(
            chunk_size=config.chunk_size,
            chunk_overlap=config.effective_chunk_overlap,
            unit=unit,
            strategy_params=pipeline_state.strategy_params_out,
        ),
        chunks=metrics.chunk_items if config.include_chunks else [],
        stats=stats,
        chunking_stats_tokens=token_stats,
        auto_selected_strategy=metrics.auto_selected_strategy,
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


def _serialize_preview_parse_documents(documents: list[Document]) -> list[dict[str, Any]]:
    try:
        return [
            {
                "page_content": doc.page_content,
                "metadata": json.loads(json.dumps(doc.metadata, ensure_ascii=False, default=str)),
                "id": doc.id,
            }
            for doc in documents
        ]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Could not serialize preview parse metadata") from exc


@router.post("/chunk-preview", response_model=ChunkPreviewResponse)
async def preview_chunking(
    request: Request,
    response: Response,
    form: Annotated[ChunkPreviewUploadForm, Form(media_type="multipart/form-data")],
    query: Annotated[ChunkPreviewQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ChunkPreviewResponse:
    """
    Chunk preview endpoint.

    Upload a file and preview chunking with the given parameters (no DB writes).
    Returns chunk results with positions for frontend highlighting.
    """
    try:
        return await _execute_preview_chunking(
            request=request,
            response=response,
            file=form.file,
            params=form,
            query=query,
            tenant_id=tenant_id,
            account_id=account_id,
        )

    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = e.details.get("type")
        if err_type in {"ValueError", "RetiredModelProviderError"}:
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.error("Subprocess worker failed during chunk preview: %s", str(e)[:200], exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=_preview_failure_detail(e, production_message="Failed to preview chunking"),
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error during chunk preview: %s", str(e)[:200], exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=_preview_failure_detail(e, production_message="Failed to preview chunking"),
        ) from e


@router.post("/chunk-preview/by-sha", response_model=ChunkPreviewResponse)
def preview_chunking_by_sha(
    response: Response,
    form: Annotated[ChunkPreviewByShaForm, Form()],
    query: Annotated[ChunkPreviewQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ChunkPreviewResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)

    preview_started = time.perf_counter()
    sha = form.file_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(status_code=400, detail="file_sha256 must be a 64-char hex string")

    raw_type = form.file_type
    if raw_type is not None:
        raw_type = raw_type.strip().lower().lstrip(".")
    if not raw_type and form.filename:
        raw_type = Path(form.filename).suffix.lower().lstrip(".")
    if not raw_type:
        raise HTTPException(status_code=400, detail="file_type is required")
    file_ext = f".{raw_type}"
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    safe_name = sanitize_upload_filename(form.filename or f"{sha[:8]}{file_ext}")
    config = _build_preview_request_config(query, form)

    if config.resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail="Integrated pipeline strategies do not support by-sha preview; please upload the file",
        )

    cache_enabled = settings.PREVIEW_PARSE_CACHE_ENABLED
    cache_ttl_sec = settings.PREVIEW_PARSE_CACHE_TTL_SEC
    cache_max_entries = settings.PREVIEW_PARSE_CACHE_MAX_ENTRIES
    cache_version = settings.PREVIEW_PARSE_CACHE_VERSION.strip() or "v1"
    if not (cache_enabled and config.use_parse_cache and cache_ttl_sec > 0 and cache_max_entries > 0):
        raise HTTPException(status_code=400, detail="parse cache disabled; please upload the file")

    cache_key = _preview_parse_cache_key(
        tenant_id=tenant_id,
        account_id=account_id,
        file_sha256=sha,
        file_ext=file_ext,
        parser_backend=config.parser_backend,
        cache_version=cache_version,
    )

    cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
    if cached is None:
        raise HTTPException(status_code=404, detail="Parse cache miss. Upload the file once to warm the cache.")

    dataset_meta = _resolve_preview_dataset_meta(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=form.dataset_id,
    )
    pipeline_state = _resolve_preview_pipeline_state(config=config, dataset_meta=dataset_meta, params=form)
    documents = _materialize_preview_documents(list(cached.documents))
    documents, governance_duration_ms = _apply_preview_governance(documents, pipeline_state=pipeline_state)
    _ensure_preview_page_indices(documents)
    chunks, chunking_duration_ms, total_chunks_full, chunks_truncated = _split_preview_documents(
        documents=documents,
        config=config,
        pipeline_state=pipeline_state,
        by_sha=True,
    )
    execution_state = PreviewExecutionState(
        documents=documents,
        chunks=chunks,
        resolved_backend=cached.resolved_backend or config.parser_backend,
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
        file_size=form.file_size if form.file_size is not None else 0,
        file_sha256=sha,
    )
