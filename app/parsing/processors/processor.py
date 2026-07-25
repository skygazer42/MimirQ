"""
Document processing service - core processing flow.
"""
import asyncio
import base64
import contextlib
import datetime as dt
import hashlib
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from langchain_core.documents import Document
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
from app.parsing.artifact_stats import POSITION_TAG_RE, compute_parsing_artifact_stats
from app.parsing.enrich.chart_to_data import add_chart_data_blocks
from app.parsing.enrich.formula_ocr import add_formula_latex_blocks
from app.parsing.enrich.image_caption import add_image_captions
from app.parsing.enrich.image_code import add_image_code_blocks
from app.parsing.enrich.vlm_image_caption import add_vlm_image_captions
from app.parsing.errors import ParsingError
from app.parsing.preprocess.file_preprocessor import preprocess_file
from app.parsing.preprocess.image_preprocess import preprocess_image_document
from app.parsing.processors.cross_page_merge import merge_cross_page_documents
from app.parsing.processors.parse_cache import (
    LocalParseCacheStore,
)
from app.parsing.processors.parse_cache import (
    ParseCacheEntry as LocalParseCacheEntry,
)
from app.parsing.processors.parse_cache import (
    build_parse_cache_key as build_local_parse_cache_key,
)
from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata
from app.parsing.processors.vlm_correction import apply_vlm_correction_async, should_apply_vlm_correction
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.reading_order import score_reading_order
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.parsing.routing import route_pdf_backend, should_attempt_pdf_fallback
from app.parsing.subprocess_runner import SubprocessCancelled, run_parser_subprocess
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.roles import classify_chunk_semantic_role, classify_chunk_type
from app.rag.chunking.strategies import SeparatorChunker
from app.rag.chunking.utils.hierarchical import apply_sequence_hierarchy_metadata
from app.rag.core.logging import get_logger
from app.rag.core.metadata import (
    ensure_hierarchy_overlay_metadata,
    infer_chunk_structure,
    normalize_image_metadata,
    normalize_section_metadata,
)
from app.rag.kg.pipeline import extract_events
from app.rag.pipeline_plugins.registry import derive_registered_stage_plugin_ref
from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin, apply_governance_python_plugin
from app.rag.preprocessing.markdown_canonical import canonicalize_markdown
from app.rag.preprocessing.near_dedup import add_simhashes, find_near_duplicate, with_near_dedup_index
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.processor import GovernanceStats, governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.rag.preprocessing.simhash import simhash64, simhash64_hex
from app.services.indexer import Indexer
from app.services.metrics_logger import log_metrics, metrics_span, set_metrics_context
from app.services.parse_cache import (
    ParseCacheEntry as RemoteParseCacheEntry,
)
from app.services.parse_cache import (
    build_parse_cache_key as build_remote_parse_cache_key,
)
from app.services.parse_cache import (
    parse_cache_service,
)
from app.services.pipeline_config import (
    build_indexing_options,
    resolve_pipeline_effective,
)
from app.services.tenant_quota_service import TenantQuotaExceededError
from app.storage.object.minio import minio_service
from app.types.document_analytics import compute_document_analytics
from app.types.indexing import IndexKind, IndexRecord
from app.types.pipeline import PipelineEffective

logger = get_logger("parsing.document_processor")
_PROCESSOR_CLEANUP_LOG_MESSAGE = "Ignoring non-critical processor cleanup failure: %s"


def _log_processor_fallback(context: str, exc: BaseException) -> None:
    logger.debug("processor fallback failed in %s: %s", context, exc, exc_info=True)


MIMIRQ_PARSE_DIRNAME = '.mimirq_parse'
REDACTED_MASK = '[REDACTED]'
# Redaction placeholder, not a credential.
SECRET_MASK = '[SECRET]'  # noqa: S105
LOG_DOC_ID_FMT = '%s document_id=%s'
AUDIT_ACTION_DOCUMENT_QUARANTINE = 'document.quarantine'


def _parsed_checkpoint_is_reusable(metadata: dict[str, Any]) -> bool:
    checkpoint = metadata.get("ingest_checkpoint")
    if not (
        isinstance(checkpoint, dict)
        and str(checkpoint.get("version") or "") == "1"
        and str(checkpoint.get("stage") or "") == "parsed"
    ):
        return False
    persisted = metadata.get("parsed_content_persisted")
    cleaned = persisted.get("cleaned") if isinstance(persisted, dict) else None
    return not (isinstance(cleaned, dict) and bool(cleaned.get("truncated")))


def _build_combined_governance_rules(pipeline_effective: PipelineEffective):
    """
    Build the explicit regex-rule list for GovernanceProcessor when rule packs or custom regex rules are enabled.

    When no extra rules are enabled, return None so GovernanceProcessor can reuse its internal defaults.
    """
    extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
    rule_packs = list(getattr(pipeline_effective, "governance_rule_packs", None) or [])
    return build_governance_rules(extra_rules, rule_packs=rule_packs) if (extra_rules or rule_packs) else None


class DocumentCancelledError(Exception):
    pass


@dataclass(frozen=True)
class ParseResult:
    resolved_backend: str
    resolved_chunk_strategy: str
    documents: list[Document] | None = None
    chunks: list[Document] | None = None


def _logical_source_from_db_document(db_document: Any, *, file_path: Path) -> str:
    meta = getattr(db_document, "doc_metadata", None)
    meta = dict(meta or {}) if isinstance(meta, dict) else {}
    user_meta = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    for value in (
        meta.get("source_path"),
        user_meta.get("source_rel_path") if isinstance(user_meta, dict) else None,
        getattr(db_document, "filename", None),
        file_path.name,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return str(file_path)


def _attach_logical_source_metadata(
    documents: list[Document] | None,
    *,
    db_document: Any,
    file_path: Path,
) -> list[Document]:
    if not documents:
        return []
    source = _logical_source_from_db_document(db_document, file_path=file_path)
    filename = str(getattr(db_document, "filename", None) or file_path.name or "").strip()
    out: list[Document] = []
    for doc in documents:
        meta = dict(doc.metadata or {})
        parser_source = str(meta.get("source") or "").strip()
        if parser_source and parser_source != source:
            meta.setdefault("parser_source", parser_source)
        meta["source"] = source
        meta["source_path"] = source
        if filename:
            meta.setdefault("filename", filename)
            meta.setdefault("file_name", filename)
        out.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))
    return out


def _get_position_tagged_markdown(doc: Document) -> str:
    metadata = getattr(doc, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    tagged = metadata.get("position_tagged_markdown")
    return str(tagged or "").replace("\x00", "").strip() if isinstance(tagged, str) else ""


def _join_document_page_content(documents: list[Document] | None) -> str:
    parts = [POSITION_TAG_RE.sub("", str(d.page_content or "").replace("\x00", "")).strip() for d in (documents or [])]
    return "\n\n".join(parts).strip()


def _join_original_markdown_for_persistence(documents: list[Document] | None) -> str:
    parts: list[str] = []
    for doc in documents or []:
        parts.append(_get_position_tagged_markdown(doc) or str(doc.page_content or "").replace("\x00", ""))
    return "\n\n".join(parts).strip()


@dataclass(frozen=True)
class InlineAssetResult:
    documents: list[Document]
    uploaded_img_ids: list[str]
    next_asset_index: int
    image_codes_added: int = 0
    image_code_audit: dict[str, Any] | None = None
    captions_added: int = 0
    caption_backend: str | None = None
    caption_audit: dict[str, Any] | None = None
    formulas_added: int = 0
    formula_backend: str | None = None
    formula_audit: dict[str, Any] | None = None
    charts_added: int = 0
    chart_backend: str | None = None
    chart_audit: dict[str, Any] | None = None


@dataclass(frozen=True)
class GovernanceResult:
    items: list[Document]
    stats: GovernanceStats | None = None


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[Document]


@dataclass(frozen=True)
class ChunkDedupResult:
    chunks: list[Document]
    duplicates_dropped: int


@dataclass(frozen=True)
class ChunkAssetResult:
    chunks: list[Document]
    img_ids: list[str]


@dataclass(frozen=True)
class ChunkAssetOptions:
    dataset_id: str
    resolved_backend: str
    resolved_chunk_strategy: str
    image_caption_enabled: bool = False
    image_ocr_enabled: bool = False
    image_ocr_max_chars: int = 2000
    image_ocr_max_images: int = 20
    pii_anonymize: bool = False
    pii_mode: str = "mask"
    pii_mask: str = REDACTED_MASK
    secrets_redact: bool = False
    secrets_mode: str = "mask"
    secrets_mask: str = SECRET_MASK


@dataclass(frozen=True)
class ChunkPostprocessStats:
    merge_small_enabled: bool
    merge_small_min_chars: int
    merge_small_before: int
    merge_small_after: int
    merge_small_reduced: int
    dedup_enabled: bool
    dedup_dropped: int
    max_chunks_per_document: int
    max_chunks_strategy: str
    truncated_from: int
    truncated_to: int
    truncated_dropped: int
    truncated_asset_total: int
    truncated_asset_kept: int


@dataclass(frozen=True)
class IndexResult:
    chunk_ids: list[UUID]
    total_characters: int
    db_chunks: list[DocumentChunk]


def _asset_metadata(item: Any) -> dict[str, Any]:
    meta = getattr(item, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _collect_artifact_dir_from_meta(meta: dict[str, Any], artifact_dirs: set[str]) -> None:
    artifact_dir = meta.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir.strip():
        artifact_dirs.add(artifact_dir.strip())


def _collect_image_ids_from_meta(meta: dict[str, Any], document_img_ids: set[str]) -> None:
    images = meta.get("images")
    if not isinstance(images, list):
        return
    for item in images:
        img_id = item.get("img_id") if isinstance(item, dict) else None
        if isinstance(img_id, str) and img_id.strip():
            document_img_ids.add(img_id)


def _collect_item_asset_refs(
    items: list[Any] | None,
    *,
    document_img_ids: set[str],
    artifact_dirs: set[str],
    collect_images: bool,
) -> None:
    for item in items or []:
        meta = _asset_metadata(item)
        _collect_artifact_dir_from_meta(meta, artifact_dirs)
        if collect_images:
            _collect_image_ids_from_meta(meta, document_img_ids)


def _collect_parser_asset_refs(
    parsed: ParseResult,
    *,
    document_img_ids: set[str],
    artifact_dirs: set[str],
) -> None:
    _collect_item_asset_refs(
        parsed.documents,
        document_img_ids=document_img_ids,
        artifact_dirs=artifact_dirs,
        collect_images=True,
    )
    _collect_item_asset_refs(
        parsed.chunks,
        document_img_ids=document_img_ids,
        artifact_dirs=artifact_dirs,
        collect_images=False,
    )


def _inline_asset_audit_needed(inline_result: InlineAssetResult) -> bool:
    return (
        int(getattr(inline_result, "image_codes_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "image_code_audit", None), dict)
        or int(getattr(inline_result, "captions_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "caption_audit", None), dict)
        or int(getattr(inline_result, "formulas_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "formula_audit", None), dict)
        or int(getattr(inline_result, "charts_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "chart_audit", None), dict)
    )


def _apply_inline_asset_audit_patch(
    db: Session,
    db_document: DBDocument,
    inline_result: InlineAssetResult,
) -> None:
    if not _inline_asset_audit_needed(inline_result):
        return

    try:
        meta_patch = dict(db_document.doc_metadata or {})
        field_specs = (
            ("image_codes_added", "image_codes_added", None, None, "image_code_audit", "image_code_audit"),
            ("image_captions_added", "captions_added", "image_caption_backend", "caption_backend", "image_caption_audit", "caption_audit"),
            ("formula_ocr_added", "formulas_added", "formula_ocr_backend", "formula_backend", "formula_ocr_audit", "formula_audit"),
            ("chart_data_added", "charts_added", "chart_data_backend", "chart_backend", "chart_data_audit", "chart_audit"),
        )
        for count_key, count_attr, backend_key, backend_attr, audit_key, audit_attr in field_specs:
            meta_patch[count_key] = int(getattr(inline_result, count_attr, 0) or 0)
            backend_value = getattr(inline_result, backend_attr, None) if backend_attr else None
            if backend_key and backend_value:
                meta_patch[backend_key] = str(backend_value or "")
            audit_value = getattr(inline_result, audit_attr, None)
            if isinstance(audit_value, dict):
                meta_patch[audit_key] = dict(audit_value or {})
        db_document.doc_metadata = meta_patch
        db.commit()
        db.refresh(db_document)
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


def _chunk_has_asset(meta: dict[str, Any]) -> bool:
    doc_type = str(meta.get("doc_type_kwd") or "").lower()
    if doc_type in {"image", "table"}:
        return True
    if meta.get("image") is not None:
        return True
    if isinstance(meta.get("image_path"), str) and meta.get("image_path").strip():
        return True
    return bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url"))


def _serialize_documents_for_parse_cache(items: list[Document] | None) -> list[dict[str, Any]] | None:
    if items is None:
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(
            {
                "page_content": str(item.page_content or ""),
                "metadata": dict(item.metadata or {}),
                "id": getattr(item, "id", None),
            }
        )
    return out


def _deserialize_documents_from_parse_cache(items: list[dict[str, Any]] | None) -> list[Document] | None:
    if items is None:
        return None
    out: list[Document] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                id=item.get("id") if isinstance(item.get("id"), str) else None,
            )
        )
    return out


def _is_table_segment_metadata(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    content_type = str(meta.get("content_type") or "").strip().lower()
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    element_kind = str(meta.get("element_kind") or "").strip().lower()
    return content_type == "table" or doc_type == "table" or element_kind == "table"


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if number != number:
            return None
        return float(number)
    except (TypeError, ValueError, AttributeError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _is_seal_segment_metadata(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    content_type = str(meta.get("content_type") or "").strip().lower()
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    return content_type == "seal" or doc_type == "seal"


def _seal_primary_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    primary = meta.get("seal_primary")
    return primary if isinstance(primary, dict) else {}


def _seal_segment_page(meta: dict[str, Any]) -> int | None:
    page = _coerce_int(meta.get("page"))
    return page if page is not None else _coerce_int(meta.get("page_number"))


def _seal_segment_candidate_count(meta: dict[str, Any]) -> int:
    candidate_count = _coerce_int(meta.get("seal_candidate_count"))
    if candidate_count is not None:
        return int(candidate_count)
    raw_candidates = meta.get("seal_candidates")
    return len(raw_candidates) if isinstance(raw_candidates, list) else 1


def _seal_candidate_from_document(doc: Document) -> dict[str, Any] | None:
    meta = dict(doc.metadata or {})
    if not _is_seal_segment_metadata(meta):
        return None

    primary = _seal_primary_metadata(meta)
    score = _coerce_float(primary.get("score"))
    if score is None:
        score = _coerce_float(meta.get("seal_score"))
    page = _seal_segment_page(meta)
    return {
        "text": str(primary.get("text") or meta.get("seal_text") or doc.page_content or "").strip(),
        "score": float(score) if score is not None else None,
        "kind": str(primary.get("seal_kind") or meta.get("seal_kind") or "unknown").strip() or "unknown",
        "page": int(page) if page is not None else None,
        "candidate_count": _seal_segment_candidate_count(meta),
    }


def _format_seal_summary(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            int(item.get("candidate_count") or 0),
        ),
        reverse=True,
    )
    pages = sorted({int(item["page"]) for item in candidates if item.get("page") is not None})
    primary = candidates[0]
    return {
        "detected": True,
        "count": int(len(candidates)),
        "candidate_count_total": int(sum(int(item.get("candidate_count") or 0) for item in candidates)),
        "primary_text": str(primary.get("text") or ""),
        "primary_score": (float(primary["score"]) if primary.get("score") is not None else None),
        "primary_kind": str(primary.get("kind") or "unknown"),
        "primary_page": primary.get("page"),
        "pages": pages,
    }


def _build_seal_summary(documents: list[Document] | None) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for doc in documents or []:
        candidate = _seal_candidate_from_document(doc)
        if candidate is not None:
            candidates.append(candidate)
    return _format_seal_summary(candidates)


def _seal_summary_to_specialty_signals(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict) or not summary:
        return None
    return {
        "seal_detected": bool(summary.get("detected")),
        "seal_expected": bool(summary.get("detected")),
        "seal_confidence": _coerce_float(summary.get("primary_score")),
        "seal_candidate_count": _coerce_int(summary.get("candidate_count_total")),
    }


def _ocr_confidence_from_metadata(meta: dict[str, Any]) -> float | None:
    confidence_value = meta.get("confidence")
    if confidence_value is None:
        confidence_value = meta.get("element_confidence")
    if confidence_value is None:
        confidence_value = meta.get("ocr_confidence")
    confidence = _coerce_float(confidence_value)
    if confidence is None:
        return None
    return max(0.0, min(1.0, float(confidence)))


def _low_confidence_span(meta: dict[str, Any], *, text: str, confidence: float) -> dict[str, Any]:
    return {
        "element_id": str(meta.get("id") or meta.get("element_id") or meta.get("source_element_id") or ""),
        "text": str(meta.get("text") or text or "")[:160],
        "page": meta.get("page") or meta.get("element_page"),
        "bbox": meta.get("bbox") if isinstance(meta.get("bbox"), dict) else meta.get("element_bbox"),
        "confidence": round(float(confidence), 4),
    }


def _iter_ocr_quality_candidates(documents: list[Document] | None) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[dict[str, Any], str]] = []
    for doc in documents or []:
        meta = dict(getattr(doc, "metadata", None) or {})
        derived = meta.get("derived_elements")
        if isinstance(derived, list):
            for item in derived:
                if isinstance(item, dict):
                    candidates.append((dict(item), str(item.get("text") or "")))
        candidates.append((meta, str(getattr(doc, "page_content", "") or "")))
    return candidates


def _append_ocr_quality_candidate(
    *,
    confidences: list[float],
    low_spans: list[dict[str, Any]],
    meta: dict[str, Any],
    text: str,
    low_confidence_threshold: float,
) -> None:
    confidence = _ocr_confidence_from_metadata(meta)
    if confidence is None:
        return
    confidences.append(confidence)
    if confidence < float(low_confidence_threshold):
        low_spans.append(_low_confidence_span(meta, text=text, confidence=confidence))


def _build_ocr_quality_summary(
    documents: list[Document] | None,
    *,
    low_confidence_threshold: float = 0.7,
) -> dict[str, Any] | None:
    confidences: list[float] = []
    low_spans: list[dict[str, Any]] = []

    for meta, text in _iter_ocr_quality_candidates(documents):
        _append_ocr_quality_candidate(
            confidences=confidences,
            low_spans=low_spans,
            meta=meta,
            text=text,
            low_confidence_threshold=low_confidence_threshold,
        )

    if not confidences:
        return None
    avg = sum(confidences) / max(1, len(confidences))
    return {
        "schema": "mimirq.ocr_quality.v1",
        "confidence_avg": round(float(avg), 4),
        "confidence_min": round(float(min(confidences)), 4),
        "span_count": int(len(confidences)),
        "low_confidence_threshold": float(low_confidence_threshold),
        "low_confidence_count": int(len(low_spans)),
        "low_confidence_spans": low_spans[:20],
    }


def _uniform_sample_indices(indices: list[int], k: int) -> list[int]:
    if k <= 0:
        return []
    if k >= len(indices):
        return list(indices)
    if k == 1:
        return [indices[len(indices) // 2]]

    picked, seen = _initial_uniform_sample(indices, k)
    if len(picked) < k:
        _fill_uniform_sample(indices, picked=picked, seen=seen, k=k)
    return picked[:k]


def _initial_uniform_sample(indices: list[int], k: int) -> tuple[list[int], set[int]]:
    n = len(indices)
    picked: list[int] = []
    seen: set[int] = set()
    for i in range(k):
        pos = round(i * (n - 1) / (k - 1))
        pos = max(0, min(n - 1, int(pos)))
        idx = indices[pos]
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(idx)
    return picked, seen


def _fill_uniform_sample(indices: list[int], *, picked: list[int], seen: set[int], k: int) -> None:
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(idx)
        if len(picked) >= k:
            break


def _chunk_asset_indices(chunks: list[Document]) -> list[int]:
    asset_indices: list[int] = []
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
        if _chunk_has_asset(meta):
            asset_indices.append(idx)
    return asset_indices


def _chunk_has_record_identity(chunk: Document) -> bool:
    return _chunk_record_identity_key(chunk) is not None


def _should_skip_near_dedup_for_chunk(chunk: Document) -> bool:
    meta = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
    return _chunk_has_asset(meta) or _chunk_has_record_identity(chunk)


def _truncate_head_chunks(
    chunks: list[Document],
    *,
    max_chunks: int,
    asset_indices: list[int],
) -> tuple[list[Document], dict[str, Any]]:
    kept_chunks = chunks[:max_chunks]
    asset_kept = sum(
        1
        for c in kept_chunks
        if _chunk_has_asset(c.metadata if isinstance(getattr(c, "metadata", None), dict) else {})
    )
    return kept_chunks, {
        "strategy": "head",
        "asset_total": int(len(asset_indices)),
        "asset_kept": int(asset_kept),
    }


def _truncate_asset_uniform_chunks(
    chunks: list[Document],
    *,
    max_chunks: int,
    asset_indices: list[int],
) -> tuple[list[Document], dict[str, Any]]:
    must_keep = [0]
    for idx in asset_indices:
        if idx not in must_keep:
            must_keep.append(idx)
    if len(must_keep) > max_chunks:
        must_keep = must_keep[:max_chunks]

    keep_set = set(must_keep)
    remaining_slots = max_chunks - len(must_keep)
    if remaining_slots > 0:
        candidate_indices = [i for i in range(len(chunks)) if i not in keep_set]
        keep_set |= set(_uniform_sample_indices(candidate_indices, remaining_slots))

    return [chunks[i] for i in range(len(chunks)) if i in keep_set], {
        "strategy": "asset_uniform",
        "asset_total": int(len(asset_indices)),
        "asset_kept": int(sum(1 for idx in asset_indices if idx in keep_set)),
    }


def _truncate_chunks_for_limit(
    chunks: list[Document],
    *,
    max_chunks: int,
    strategy: str,
) -> tuple[list[Document], dict[str, Any]]:
    if max_chunks <= 0 or not chunks or len(chunks) <= max_chunks:
        return chunks, {"strategy": (strategy or "head").strip().lower() or "head", "asset_total": 0, "asset_kept": 0}
    if any(_chunk_has_record_identity(chunk) for chunk in chunks):
        asset_indices = _chunk_asset_indices(chunks)
        return chunks, {
            "strategy": "record_identity_preserved",
            "asset_total": int(len(asset_indices)),
            "asset_kept": int(len(asset_indices)),
            "truncation_skipped": True,
        }

    strategy_norm = (strategy or "head").strip().lower() or "head"
    asset_indices = _chunk_asset_indices(chunks)
    if strategy_norm not in {"head", "asset_uniform"}:
        strategy_norm = "head"
    if strategy_norm == "head":
        return _truncate_head_chunks(chunks, max_chunks=max_chunks, asset_indices=asset_indices)
    return _truncate_asset_uniform_chunks(chunks, max_chunks=max_chunks, asset_indices=asset_indices)


def _ensure_ingest_page_indices(documents: list[Document]) -> None:
    """
    Ensure each parsed Document has a stable per-document index for offset rebasing.

    Why:
    - Many parsers (e.g. PDF) emit multiple Documents.
    - Most chunkers compute start/end offsets relative to each `doc.page_content`.
    - We persist parsed markdown by joining docs; to highlight chunks reliably,
      we need global offsets (joined-text coordinates).
    """
    for i, doc in enumerate(documents or []):
        meta = dict(getattr(doc, "metadata", None) or {})
        meta.setdefault("page_index", i + 1)  # 1-based (align with chunk-preview)
        doc.metadata = meta


def _joined_text_total_characters(
    documents: list[Document],
    *,
    join_separator: str = "\n\n",
) -> int:
    """Return the joined-text length used for persisted parsed content offsets."""
    if not documents:
        return 0
    sep_len = len(join_separator or "")
    total = 0
    last_index = len(documents) - 1
    for idx, doc in enumerate(documents):
        total += len(doc.page_content or "")
        if idx < last_index:
            total += sep_len
    return int(total)


def _document_page_index(doc: Document, index: int) -> int:
    meta = dict(getattr(doc, "metadata", None) or {})
    try:
        return int(meta.get("page_index") or (index + 1))
    except (TypeError, ValueError, AttributeError):
        return index + 1


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def _chunk_page_index(chunk: Document) -> int | None:
    meta = getattr(chunk, "metadata", None) or {}
    return _optional_int(meta.get("page_index"))


def _build_page_start_offsets(
    documents: list[Document],
    *,
    join_separator: str,
) -> dict[int, int]:
    sep_len = len(join_separator or "")
    page_start: dict[int, int] = {}
    cursor = 0
    last_index = len(documents) - 1
    for index, doc in enumerate(documents):
        page_start[_document_page_index(doc, index)] = cursor
        cursor += len(doc.page_content or "")
        if index < last_index:
            cursor += sep_len
    return page_start


def _rebase_single_chunk_offsets(chunk: Document, *, page_start: dict[int, int]) -> Document:
    meta = dict(getattr(chunk, "metadata", None) or {})
    page_index = _optional_int(meta.get("page_index"))
    base = page_start.get(page_index, 0) if page_index is not None else 0
    start_i = _optional_int(meta.get("start_char"))
    end_i = _optional_int(meta.get("end_char"))

    if start_i is not None:
        meta.setdefault("start_char_local", start_i)
        meta["start_char"] = base + start_i
    if end_i is not None:
        meta.setdefault("end_char_local", end_i)
        meta["end_char"] = base + end_i
    if page_index is not None:
        meta.setdefault("start_char_base", base)

    meta.setdefault("offsets_rebased", True)
    return Document(page_content=chunk.page_content, metadata=meta, id=getattr(chunk, "id", None))


def _rebase_chunk_offsets_by_page_index(
    *,
    documents: list[Document],
    chunks: list[Document],
    join_separator: str = "\n\n",
) -> list[Document]:
    """
    Convert chunk start/end offsets from per-Document coordinates to joined-text coordinates.

    - Assumes chunk metadata contains `page_index` and local `start_char`/`end_char`.
    - Uses the same join separator as persisted parsed content ("\\n\\n").
    """
    if not documents or not chunks:
        return chunks

    page_start = _build_page_start_offsets(documents, join_separator=join_separator)
    return [_rebase_single_chunk_offsets(chunk, page_start=page_start) for chunk in chunks]


def _build_page_text_lookup(
    documents: list[Document],
    *,
    join_separator: str,
) -> tuple[dict[int, str], dict[int, int]]:
    sep_len = len(join_separator or "")
    page_text: dict[int, str] = {}
    page_base: dict[int, int] = {}
    cursor = 0
    last_index = len(documents) - 1
    for index, doc in enumerate(documents):
        page_index = _document_page_index(doc, index)
        page_text[page_index] = doc.page_content or ""
        page_base[page_index] = cursor
        cursor += len(doc.page_content or "")
        if index < last_index:
            cursor += sep_len
    return page_text, page_base


def _chunk_mergeable(chunk: Document) -> bool:
    meta = getattr(chunk, "metadata", None) or {}
    if _chunk_has_asset(meta):
        return False
    return not (meta.get("chunk_role") or meta.get("parent_id"))


def _chunk_record_identity_key(chunk: Document) -> str | None:
    meta = getattr(chunk, "metadata", None) or {}
    record_identity = meta.get("_record_identity") if isinstance(meta, dict) else None
    if not isinstance(record_identity, dict):
        return None
    key = str(record_identity.get("key") or "").strip()
    return key or None


def _chunks_share_record_identity_boundary(first: Document, second: Document) -> bool:
    first_key = _chunk_record_identity_key(first)
    second_key = _chunk_record_identity_key(second)
    if first_key or second_key:
        return bool(first_key and second_key and first_key == second_key)
    return True


def _local_chunk_range(meta: dict[str, Any], *, base: int) -> tuple[int, int] | None:
    # Prefer explicitly stored locals (set by offset rebase stage).
    start_local = meta.get("start_char_local")
    end_local = meta.get("end_char_local")
    start_i = _optional_int(start_local)
    end_i = _optional_int(end_local)

    if start_i is None or end_i is None:
        sg = _optional_int(meta.get("start_char"))
        eg = _optional_int(meta.get("end_char"))
        if sg is None or eg is None:
            return None
        start_i = max(0, sg - base)
        end_i = max(start_i, eg - base)

    if end_i < start_i:
        return None
    return start_i, end_i


_MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS = (
    "content_hash",
    "content_hash_algo",
    "content_len",
    "simhash64",
    "simhash_algo",
    "chunk_quality",
    "chunk_semantic_role",
    "chunk_type",
    "structure",
)


def _retrieval_text_for_merge(chunk: Document, meta: dict[str, Any]) -> str:
    retrieval_text = meta.get("_retrieval_text")
    if isinstance(retrieval_text, str) and retrieval_text.strip():
        return retrieval_text.strip()
    return str(chunk.page_content or "").strip()


def _refresh_merged_chunk_content_metadata(
    meta: dict[str, Any],
    *,
    first: Document,
    second: Document,
    first_meta: dict[str, Any],
    second_meta: dict[str, Any],
    merged_content: str,
) -> None:
    for key in _MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS:
        meta.pop(key, None)

    first_has_retrieval = isinstance(first_meta.get("_retrieval_text"), str) and bool(str(first_meta["_retrieval_text"]).strip())
    second_has_retrieval = isinstance(second_meta.get("_retrieval_text"), str) and bool(str(second_meta["_retrieval_text"]).strip())
    if first_has_retrieval or second_has_retrieval:
        pieces = [
            text
            for text in (
                _retrieval_text_for_merge(first, first_meta),
                _retrieval_text_for_merge(second, second_meta),
            )
            if text
        ]
        meta["_retrieval_text"] = "\n\n".join(pieces)
        meta["_retrieval_display_content"] = str(merged_content or "")
    else:
        meta.pop("_retrieval_text", None)
        meta.pop("_retrieval_display_content", None)


def _merge_two_small_chunks(
    first: Document,
    second: Document,
    *,
    page_index: int,
    page_text: dict[int, str],
    page_base: dict[int, int],
) -> Document | None:
    text = page_text.get(page_index)
    base = int(page_base.get(page_index) or 0)
    if text is None:
        return None
    if not _chunks_share_record_identity_boundary(first, second):
        return None

    first_meta = dict(getattr(first, "metadata", None) or {})
    second_meta = dict(getattr(second, "metadata", None) or {})
    first_range = _local_chunk_range(first_meta, base=base)
    second_range = _local_chunk_range(second_meta, base=base)
    if first_range is None or second_range is None:
        return None

    start_local = max(0, min(min(first_range[0], second_range[0]), len(text)))
    end_local = max(start_local, min(max(first_range[1], second_range[1]), len(text)))
    first_meta["page_index"] = page_index
    first_meta.setdefault("start_char_base", base)
    first_meta["start_char_local"] = start_local
    first_meta["end_char_local"] = end_local
    first_meta["start_char"] = base + start_local
    first_meta["end_char"] = base + end_local
    first_meta["offsets_rebased"] = True
    first_meta["merged_small_chunks"] = int(first_meta.get("merged_small_chunks") or 0) + 1
    merged_content = text[start_local:end_local]
    _refresh_merged_chunk_content_metadata(
        first_meta,
        first=first,
        second=second,
        first_meta=first_meta,
        second_meta=second_meta,
        merged_content=merged_content,
    )

    return Document(page_content=merged_content, metadata=first_meta, id=getattr(first, "id", None))


def _merge_with_pending_small_chunk(
    *,
    out: list[Document],
    pending: Document,
    current: Document,
    page_index: int,
    page_text: dict[int, str],
    page_base: dict[int, int],
) -> None:
    merged = _merge_two_small_chunks(
        pending,
        current,
        page_index=page_index,
        page_text=page_text,
        page_base=page_base,
    )
    if merged is not None:
        out.append(merged)
        return
    out.append(pending)
    out.append(current)


def _flush_pending_on_page_change(
    *,
    out: list[Document],
    pending: Document | None,
    pending_page: int | None,
    page_index: int | None,
) -> tuple[Document | None, int | None]:
    if pending is not None and page_index != pending_page:
        out.append(pending)
        return None, None
    return pending, pending_page


def _append_unmergeable_chunk(
    *,
    out: list[Document],
    chunk: Document,
    pending: Document | None,
) -> tuple[Document | None, int | None]:
    if pending is not None:
        out.append(pending)
    out.append(chunk)
    return None, None


def _try_merge_with_previous_chunk(
    *,
    out: list[Document],
    chunk: Document,
    page_index: int,
    page_text: dict[int, str],
    page_base: dict[int, int],
) -> bool:
    if not out:
        return False
    prev = out[-1]
    if _chunk_page_index(prev) != page_index or not _chunk_mergeable(prev):
        return False
    merged = _merge_two_small_chunks(
        prev,
        chunk,
        page_index=page_index,
        page_text=page_text,
        page_base=page_base,
    )
    if merged is None:
        return False
    out[-1] = merged
    return True


def _merge_small_chunks_by_min_chars(
    *,
    documents: list[Document],
    chunks: list[Document],
    min_chars: int,
    join_separator: str = "\n\n",
) -> list[Document]:
    """
    Merge very short text chunks with neighbors to reduce over-fragmentation.

    Design goals:
    - Keep merge bounded within the same `page_index` (stable highlighting).
    - Preserve assets (image/table) and parent/child semantics by skipping those chunks.
    - Use original per-page text slice when offsets are available (so content matches offsets).
    """
    min_chars = max(0, int(min_chars or 0))
    if min_chars <= 0 or not documents or not chunks:
        return chunks

    page_text, page_base = _build_page_text_lookup(documents, join_separator=join_separator)

    out: list[Document] = []
    pending: Document | None = None
    pending_page: int | None = None

    for c in chunks:
        page_index = _chunk_page_index(c)
        pending, pending_page = _flush_pending_on_page_change(
            out=out,
            pending=pending,
            pending_page=pending_page,
            page_index=page_index,
        )

        mergeable = page_index is not None and page_index in page_text and _chunk_mergeable(c)
        content_len = len((c.page_content or "").strip())

        if not mergeable:
            pending, pending_page = _append_unmergeable_chunk(out=out, chunk=c, pending=pending)
            continue

        if pending is not None:
            _merge_with_pending_small_chunk(
                out=out,
                pending=pending,
                current=c,
                page_index=page_index,
                page_text=page_text,
                page_base=page_base,
            )
            pending = None
            pending_page = None
            continue

        if content_len >= min_chars:
            out.append(c)
            continue

        # Small chunk: merge into previous if possible, otherwise buffer and merge into next.
        if _try_merge_with_previous_chunk(
            out=out,
            chunk=c,
            page_index=page_index,
            page_text=page_text,
            page_base=page_base,
        ):
            continue

        pending = c
        pending_page = page_index

    if pending is not None:
        out.append(pending)

    return out


def _governance_reduction_pct(*, original_chars: int, cleaned_chars: int) -> int:
    if original_chars <= 0 or cleaned_chars < 0:
        return 0
    try:
        ratio = float((original_chars - cleaned_chars) / float(original_chars))
    except (TypeError, ValueError, AttributeError):
        ratio = 0.0
    return int(round(max(0.0, min(1.0, ratio)) * 100.0))


def _safe_governance_int(raw: object) -> int:
    try:
        if raw is None or isinstance(raw, bool):
            return 0
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, AttributeError):
        return 0


def _governance_quality_from_metadata(meta: dict[str, Any]) -> tuple[int, int, int, int, int] | None:
    quality = meta.get("governance_quality")
    if not isinstance(quality, dict):
        return None
    return (
        _safe_governance_int(quality.get("chars_non_space")),
        _safe_governance_int(quality.get("chars_alnum_cjk")),
        _safe_governance_int(quality.get("lines_total")),
        _safe_governance_int(quality.get("lines_outline")),
        _safe_governance_int(quality.get("content_chars")),
    )


def _compute_governance_quality_metrics(text: str) -> tuple[int, int, int, int, int]:
    from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only

    try:
        density_metrics = drop_if_low_density(text, threshold=-1.0).metrics or {}
    except Exception as exc:
        _log_processor_fallback('_build_governance_audit_metadata_patch', exc)
        density_metrics = {}
    try:
        outline_metrics = drop_if_outline_only(text, min_content_chars=0, max_heading_ratio=2.0).metrics or {}
    except Exception as exc:
        _log_processor_fallback('_build_governance_audit_metadata_patch', exc)
        outline_metrics = {}

    return (
        _safe_governance_int(density_metrics.get("chars_non_space")),
        _safe_governance_int(density_metrics.get("chars_alnum_cjk")),
        _safe_governance_int(outline_metrics.get("lines_total")),
        _safe_governance_int(outline_metrics.get("lines_outline")),
        _safe_governance_int(outline_metrics.get("content_chars")),
    )


def _aggregate_governance_quality(source_items: list[Document]) -> dict[str, Any]:
    chars_non_space = 0
    chars_alnum_cjk = 0
    lines_total = 0
    lines_outline = 0
    content_chars = 0

    for doc in source_items:
        meta = doc.metadata if isinstance(getattr(doc, "metadata", None), dict) else {}
        metrics = _governance_quality_from_metadata(meta)
        if metrics is None:
            metrics = _compute_governance_quality_metrics(doc.page_content or "")
        chars_non_space += metrics[0]
        chars_alnum_cjk += metrics[1]
        lines_total += metrics[2]
        lines_outline += metrics[3]
        content_chars += metrics[4]

    density = float(chars_alnum_cjk / max(1, chars_non_space)) if chars_non_space > 0 else 0.0
    heading_ratio = float(lines_outline / max(1, lines_total)) if lines_total > 0 else 0.0
    return {
        "density": round(float(max(0.0, min(1.0, density))), 6),
        "chars_non_space": int(max(0, chars_non_space)),
        "chars_alnum_cjk": int(max(0, chars_alnum_cjk)),
        "heading_ratio": round(float(max(0.0, min(1.0, heading_ratio))), 6),
        "lines_total": int(max(0, lines_total)),
        "lines_outline": int(max(0, lines_outline)),
        "content_chars": int(max(0, content_chars)),
    }


def _positive_governance_counts(stats: GovernanceStats) -> dict[str, int]:
    effects_map = {
        "governance_frontmatter_docs": getattr(stats, "frontmatter_docs", 0),
        "governance_frontmatter_stripped_docs": getattr(stats, "frontmatter_stripped_docs", 0),
        "governance_paragraphs_dropped": getattr(stats, "paragraphs_dropped", 0),
        "governance_references_removed_lines": getattr(stats, "references_removed_lines", 0),
        "governance_urls_changed": getattr(stats, "urls_changed", 0),
        "governance_boilerplate_removed_sections": getattr(stats, "boilerplate_removed_sections", 0),
        "governance_boilerplate_removed_lines": getattr(stats, "boilerplate_removed_lines", 0),
        "governance_images_removed": getattr(stats, "images_removed", 0),
        "governance_tables_normalized": getattr(stats, "tables_normalized", 0),
        "governance_table_rows_changed": getattr(stats, "table_rows_changed", 0),
        "governance_code_blocks_changed": getattr(stats, "code_blocks_changed", 0),
        "governance_code_lines_stripped": getattr(stats, "code_lines_stripped", 0),
        "governance_keywords_docs": getattr(stats, "keywords_docs", 0),
        "governance_keywords_total": getattr(stats, "keywords_total", 0),
        "governance_titles_docs": getattr(stats, "titles_docs", 0),
        "governance_tags_docs": getattr(stats, "tags_docs", 0),
    }
    return {key: value for key, raw in effects_map.items() if (value := _safe_governance_int(raw)) > 0}


def _positive_string_count_map(raw_counts: Any) -> dict[str, int] | None:
    if not isinstance(raw_counts, dict) or not raw_counts:
        return None
    out: dict[str, int] = {}
    for raw_key, raw_value in raw_counts.items():
        if raw_key is None:
            continue
        key = str(raw_key).strip()
        value = _safe_governance_int(raw_value)
        if key and value > 0:
            out[key] = value
    return out or None


def _string_count_map(raw_counts: Any) -> dict[str, int] | None:
    if not isinstance(raw_counts, dict) or not raw_counts:
        return None
    return {str(key): int(value) for key, value in raw_counts.items()}


def _clean_governance_rule_packs(rule_packs: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in rule_packs or []:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(key[:64])
        if len(cleaned) >= 20:
            break
    return cleaned


class ParsingStage:
    def __init__(self, service: "DocumentProcessorService"):
        self._svc = service

    async def run(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        dataset_id: str,
        parser_backend: str | None,
        chunk_strategy: str | None,
        html_xpath: str | None = None,
    ) -> ParseResult:
        # IMPORTANT: resolve strategy first so defaults (e.g. DEFAULT_CHUNK_STRATEGY)
        # are honored consistently (including integrated_* strategies).
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
        if resolved_chunk_strategy in self._svc.INTEGRATED_PIPELINE_STRATEGIES:
            resolved_backend = "integrated"
            self._svc._record_processing_metadata(
                db,
                tenant_id,
                document_id,
                parser_backend=resolved_backend,
                chunk_strategy=resolved_chunk_strategy,
            )
            artifact_root = (
                Path(settings.UPLOAD_DIR)
                / str(tenant_id)
                / MIMIRQ_PARSE_DIRNAME
                / f"{str(document_id)}-integrated-{uuid.uuid4().hex}"
            )
            cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

            async def cancel_check_worker() -> bool:
                return await cancel_check()

            try:
                result = await run_parser_subprocess(
                    tenant_id=tenant_id,
                    payload={
                        "action": "integrated_chunk",
                        "tenant_id": str(tenant_id),
                        "file_path": str(file_path),
                        "strategy": resolved_chunk_strategy,
                        "mode": "ingest",
                        "artifact_root": str(artifact_root),
                    },
                    cancel_check=cancel_check_worker,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
            except SubprocessCancelled as exc:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise DocumentCancelledError(str(exc)) from exc
            except asyncio.CancelledError:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise
            except ParsingError as exc:
                raise RuntimeError(f"Integrated pipeline parsing failed: {str(exc)[:200]}") from exc

            chunks = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (result.get("documents") or [])
                if isinstance(item, dict)
            ]
            return ParseResult(
                resolved_backend=resolved_backend,
                resolved_chunk_strategy=resolved_chunk_strategy,
                chunks=_attach_logical_source_metadata(chunks, db_document=db_document, file_path=file_path),
            )

        logger.info("Parsing document: %s", file_path)
        effective_parser_backend = parser_backend
        file_ext = file_path.suffix.lower()
        pdf_quality = None
        parse_cache_key: str | None = None
        parse_cache_hit = False
        parse_cache_age_ms: int | None = None
        if file_ext == ".pdf":
            requested = (parser_backend or "").strip().lower()
            if not requested or requested == "auto":
                cached_quality = None
                try:
                    m0 = db_document.doc_metadata or {}
                    q0 = m0.get("pdf_quality") if isinstance(m0, dict) else None
                    if isinstance(q0, dict) and q0.get("score") is not None:
                        cached_quality = dict(q0)
                except (TypeError, ValueError, AttributeError):
                    cached_quality = None
                effective_parser_backend, pdf_quality = route_pdf_backend(
                    file_path,
                    parser_backend,
                    quality=cached_quality,
                    sample_pages=3,
                    use_ocr_validation=settings.RAPIDOCR_ENABLED,
                )
                if isinstance(pdf_quality, dict):
                    metadata = dict(db_document.doc_metadata or {})
                    metadata["pdf_quality"] = pdf_quality
                    db_document.doc_metadata = metadata
                    db.commit()
                    db.refresh(db_document)

        parsed: dict[str, Any] | None = None
        documents: list[Document] = []

        # Optional: parse cache (MinIO). Best-effort and never blocks ingestion.
        try:
            if bool(getattr(settings, "PARSE_CACHE_ENABLED", False)) and bool(getattr(settings, "MINIO_ENABLED", False)):
                meta0 = dict(db_document.doc_metadata or {})
                file_sha = str(meta0.get("file_sha256") or "").strip().lower()
                pipeline_hash = str(meta0.get("pipeline_hash") or meta0.get("active_pipeline_hash") or "").strip()
                config_hash = pipeline_hash or "unknown"
                backend_key = str(effective_parser_backend or "").strip().lower()
                if file_sha and backend_key:
                    parse_cache_key = build_remote_parse_cache_key(
                        file_sha256=file_sha,
                        resolved_backend=backend_key,
                        config_hash=config_hash,
                        version=str(getattr(settings, "PARSE_CACHE_VERSION", "v1") or "v1"),
                    )
                    cached, age_ms = parse_cache_service.get(
                        tenant_id=str(tenant_id),
                        dataset_id=str(dataset_id),
                        cache_key=parse_cache_key,
                        ttl_sec=int(getattr(settings, "PARSE_CACHE_TTL_SEC", 0) or 0),
                        max_bytes=int(getattr(settings, "PARSE_CACHE_MAX_BYTES", 0) or 0),
                    )
                    if cached is not None and list(getattr(cached, "documents", None) or []):
                        parse_cache_hit = True
                        parse_cache_age_ms = age_ms
                        documents = [
                            Document(
                                page_content=str(item.get("page_content") or ""),
                                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                                id=item.get("id") if isinstance(item.get("id"), str) else None,
                            )
                            for item in (cached.documents or [])
                            if isinstance(item, dict)
                        ]
                        # Record cache hit for observability (best-effort).
                        try:
                            meta_patch = dict(db_document.doc_metadata or {})
                            meta_patch["parse_cache"] = {
                                "schema": "mimirq.parse_cache_hit.v1",
                                "hit": True,
                                "age_ms": int(parse_cache_age_ms or 0),
                                "backend": backend_key,
                            }
                            db_document.doc_metadata = meta_patch
                            db.commit()
                            db.refresh(db_document)
                        except Exception as exc:
                            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        except Exception as exc:
            _log_processor_fallback('run', exc)
            parse_cache_hit = False

        if not parse_cache_hit:
            artifact_root = (
                Path(settings.UPLOAD_DIR)
                / str(tenant_id)
                / MIMIRQ_PARSE_DIRNAME
                / f"{str(document_id)}-parse-{uuid.uuid4().hex}"
            )
            cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

            async def cancel_check_worker() -> bool:
                return await cancel_check()

            try:
                payload = {
                    "action": "parse_documents",
                    "tenant_id": str(tenant_id),
                    "file_path": str(file_path),
                    "parser_backend": effective_parser_backend,
                    "mode": "ingest",
                    "dataset_id": dataset_id,
                    "document_id": str(document_id),
                    "pdf_quality": pdf_quality,
                    "artifact_root": str(artifact_root),
                }
                if isinstance(html_xpath, str) and html_xpath.strip():
                    payload["html_xpath"] = html_xpath.strip()
                parsed = await run_parser_subprocess(
                    tenant_id=tenant_id,
                    payload=payload,
                    cancel_check=cancel_check_worker,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
            except SubprocessCancelled as exc:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise DocumentCancelledError(str(exc)) from exc
            except asyncio.CancelledError:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise
            except ParsingError as exc:
                raise RuntimeError(f"Parsing failed: {str(exc)[:200]}") from exc

            documents = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (parsed.get("documents") or [])
                if isinstance(item, dict)
            ]

        documents = _attach_logical_source_metadata(documents, db_document=db_document, file_path=file_path)

        # Persist parse provenance for audit/debug (best-effort).
        try:
            prov = parsed.get("provenance") if isinstance(parsed, dict) else None
            if isinstance(prov, dict) and prov:
                meta = dict(db_document.doc_metadata or {})
                meta["parse_provenance"] = prov
                db_document.doc_metadata = meta
                db.commit()
                db.refresh(db_document)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

        # Attach lightweight parsed-text quality metrics for observability/tuning.
        try:
            joined = _join_document_page_content(documents)
            quality = score_parsed_text_quality(joined).to_dict()
            seal_summary = _build_seal_summary(documents)
            specialty_signals = _seal_summary_to_specialty_signals(seal_summary)
            ocr_summary = _build_ocr_quality_summary(
                documents,
                low_confidence_threshold=float(settings.PARSE_QUALITY_OCR_LOW_CONFIDENCE_THRESHOLD),
            )
            meta = dict(db_document.doc_metadata or {})
            meta["parsed_text_quality"] = quality
            meta["parse_quality"] = score_document_parse_quality(
                pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                parsed_text_quality=quality,
                specialty_signals=specialty_signals,
            )
            if seal_summary is not None:
                meta["seal_summary"] = seal_summary
            if ocr_summary is not None:
                meta["ocr"] = ocr_summary
            artifact_stats = compute_parsing_artifact_stats(
                documents=documents,
                original_markdown=_join_original_markdown_for_persistence(documents),
                markdown=joined,
                pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
            )
            meta.update(artifact_stats)
            # Lightweight "document portrait" for UI (best-effort, safe to ignore).
            try:
                meta["document_analytics_raw"] = compute_document_analytics(
                    markdown=joined,
                    documents=documents,
                    pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                    detect_language=bool(getattr(settings, "GOVERNANCE_DETECT_LANGUAGE", False)),
                    language_min_chars=int(getattr(settings, "GOVERNANCE_LANGUAGE_MIN_CHARS", 40) or 40),
                ).to_dict()
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            meta = apply_parse_quality_gate_metadata(meta)
            db_document.doc_metadata = meta
            db.commit()
            db.refresh(db_document)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

        # Parse cache write-through (best-effort, only when miss).
        if (not parse_cache_hit) and parse_cache_key and documents:
            try:
                meta0 = dict(db_document.doc_metadata or {})
                file_sha = str(meta0.get("file_sha256") or "").strip().lower()
                pipeline_hash = str(meta0.get("pipeline_hash") or meta0.get("active_pipeline_hash") or "").strip()
                config_hash = pipeline_hash or "unknown"
                backend_key = str(effective_parser_backend or "").strip().lower()
                entry = RemoteParseCacheEntry(
                    created_at=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
                    file_sha256=file_sha,
                    resolved_backend=backend_key,
                    config_hash=config_hash,
                    documents=[
                        {
                            "page_content": str(d.page_content or ""),
                            "metadata": dict(d.metadata or {}),
                            "id": str(d.id) if isinstance(getattr(d, "id", None), str) else None,
                        }
                        for d in (documents or [])
                    ],
                )
                parse_cache_service.set(
                    tenant_id=str(tenant_id),
                    dataset_id=str(dataset_id),
                    cache_key=parse_cache_key,
                    entry=entry,
                    max_bytes=int(getattr(settings, "PARSE_CACHE_MAX_BYTES", 0) or 0),
                )
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

        parsed_backend = parsed.get("resolved_backend") if isinstance(parsed, dict) else None
        resolved_backend = str(parsed_backend or effective_parser_backend or parser_backend or "auto")
        self._svc._record_processing_metadata(
            db,
            tenant_id,
            document_id,
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy,
        )
        return ParseResult(
            resolved_backend=resolved_backend,
            resolved_chunk_strategy=resolved_chunk_strategy,
            documents=documents,
        )


class InlineAssetStage:
    def __init__(self, service: "DocumentProcessorService"):
        self._svc = service

    def run(
        self,
        *,
        documents: list[Document],
        tenant_id: UUID,
        dataset_id: str,
        document_id: UUID,
        origin_path: Path,
        start_index: int = 0,
        image_caption_enabled: bool = False,
    ) -> InlineAssetResult:
        upload_enabled = bool(getattr(settings, "MINIO_ENABLED", False))
        caption_enabled = bool(image_caption_enabled)
        formula_url = str(getattr(settings, "FORMULA_OCR_API_URL", "") or "").strip()
        formula_enabled = bool(getattr(settings, "FORMULA_OCR_ENABLED", False)) and bool(formula_url)
        chart_enabled = bool(getattr(settings, "CHART_TO_DATA_ENABLED", False)) and bool(
            str(getattr(settings, "CHART_TO_DATA_API_URL", "") or "").strip()
        )
        image_code_enabled = True
        if not upload_enabled and not caption_enabled and not formula_enabled and not chart_enabled and not image_code_enabled:
            return InlineAssetResult(documents=documents, uploaded_img_ids=[], next_asset_index=int(start_index or 0))

        inline_cache: dict[str, str] = {}
        asset_idx = int(start_index or 0)
        uploaded: list[str] = []
        processed_docs: list[Document] = []
        image_codes_added_total = 0
        image_code_audit: dict[str, Any] | None = None
        captions_added_total = 0
        caption_backend: str | None = None
        caption_audit: dict[str, Any] | None = None
        formulas_added_total = 0
        formula_backend: str | None = None
        formula_audit: dict[str, Any] | None = None
        charts_added_total = 0
        chart_backend: str | None = None
        chart_audit: dict[str, Any] | None = None

        for doc in documents:
            content = doc.page_content or ""
            original_meta = dict(doc.metadata or {})
            origin_for_doc = origin_path
            base_dir = original_meta.get("asset_base_dir")
            if isinstance(base_dir, str) and base_dir.strip():
                origin_for_doc = Path(base_dir.strip())

            next_content = content
            next_meta = dict(original_meta)
            if next_content:
                try:
                    next_content, added, audit = add_image_code_blocks(
                        next_content,
                        origin_path=origin_for_doc,
                    )
                    image_codes_added_total += int(added or 0)
                    image_code_audit = audit.to_dict()
                    raw_code_elements = getattr(audit, "code_elements", None)
                    if isinstance(raw_code_elements, list) and raw_code_elements:
                        derived = [item for item in (next_meta.get("derived_elements") or []) if isinstance(item, dict)]
                        page_hint = next_meta.get("element_page") or next_meta.get("page")
                        for raw_element in raw_code_elements:
                            if not isinstance(raw_element, dict):
                                continue
                            item = dict(raw_element)
                            if item.get("page") is None and page_hint is not None:
                                item["page"] = page_hint
                            if not str(item.get("id") or "").strip():
                                page_part = item.get("page") if item.get("page") is not None else "na"
                                item["id"] = f"image_code:{page_part}:{len(derived)}"
                            derived.append(item)
                        if derived:
                            next_meta["derived_elements"] = derived
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            # Opt3: Formula OCR / LaTeX conversion (best-effort) before asset rewriting
            # so we can still read local image files.
            if formula_enabled and next_content:
                try:
                    next_content, added, audit = add_formula_latex_blocks(
                        next_content,
                        origin_path=origin_for_doc,
                        api_url=formula_url,
                        timeout_sec=float(getattr(settings, "FORMULA_OCR_TIMEOUT_SEC", 60) or 60),
                        max_images=int(getattr(settings, "FORMULA_OCR_MAX_IMAGES", 12) or 12),
                        max_image_bytes=int(getattr(settings, "FORMULA_OCR_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                        max_latex_chars=int(getattr(settings, "FORMULA_OCR_MAX_LATEX_CHARS", 2000) or 2000),
                    )
                    formulas_added_total += int(added or 0)
                    formula_backend = "formula_http"
                    formula_audit = audit.to_dict()
                    raw_formula_elements = getattr(audit, "formula_elements", None)
                    if isinstance(raw_formula_elements, list) and raw_formula_elements:
                        derived = [item for item in (next_meta.get("derived_elements") or []) if isinstance(item, dict)]
                        page_hint = next_meta.get("element_page") or next_meta.get("page")
                        for raw_element in raw_formula_elements:
                            if not isinstance(raw_element, dict):
                                continue
                            item = dict(raw_element)
                            if item.get("page") is None and page_hint is not None:
                                item["page"] = page_hint
                            if not str(item.get("id") or "").strip():
                                page_part = item.get("page") if item.get("page") is not None else "na"
                                item["id"] = f"formula_ocr:{page_part}:{len(derived)}"
                            derived.append(item)
                        if derived:
                            next_meta["derived_elements"] = derived
                except Exception as exc:
                    _log_processor_fallback('run', exc)
                    # Never fail ingest due to optional enrichment.

            # Best-effort chart -> structured data extraction.
            if chart_enabled and next_content:
                try:
                    next_content, added, audit = add_chart_data_blocks(
                        next_content,
                        origin_path=origin_for_doc,
                        max_images=int(getattr(settings, "CHART_TO_DATA_MAX_IMAGES", 8) or 8),
                        max_image_bytes=int(getattr(settings, "CHART_TO_DATA_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                        timeout_sec=float(getattr(settings, "CHART_TO_DATA_TIMEOUT_SEC", 20) or 20),
                    )
                    charts_added_total += int(added or 0)
                    chart_backend = "chart_http"
                    chart_audit = audit.to_dict()
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

            # Opt5: image captions (best-effort) before asset rewriting so we can still
            # read local image files when using an external VLM backend.
            if caption_enabled:
                try:
                    if bool(getattr(settings, "IMAGE_CAPTION_VLM_ENABLED", False)) and str(
                        getattr(settings, "IMAGE_CAPTION_VLM_API_URL", "") or ""
                    ).strip():
                        next_content, added, audit = add_vlm_image_captions(
                            next_content,
                            origin_path=origin_for_doc,
                            api_url=str(getattr(settings, "IMAGE_CAPTION_VLM_API_URL", "") or ""),
                            timeout_sec=float(getattr(settings, "IMAGE_CAPTION_VLM_TIMEOUT_SEC", 60) or 60),
                            max_images=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_IMAGES", 20) or 20),
                            max_image_bytes=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                            max_caption_chars=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_CAPTION_CHARS", 200) or 200),
                        )
                        captions_added_total += int(added or 0)
                        caption_backend = "vlm_http"
                        # Keep last audit (best-effort); do not grow unbounded.
                        caption_audit = audit.to_dict()
                    else:
                        next_content, added = add_image_captions(next_content)
                        captions_added_total += int(added or 0)
                        caption_backend = "heuristic"
                except Exception as exc:
                    _log_processor_fallback('run', exc)
                    # Never fail ingest due to optional captioning.

            if upload_enabled:
                new_content, new_img_ids, asset_idx = self._svc._upload_inline_images_to_minio(
                    markdown_text=next_content,
                    tenant_id=str(tenant_id),
                    dataset_id=dataset_id,
                    document_id=str(document_id),
                    cache=inline_cache,
                    start_index=asset_idx,
                    origin_path=origin_for_doc,
                )
                uploaded.extend(list(new_img_ids or []))
            else:
                new_content = next_content
                new_img_ids = []

            if new_content != content:
                processed_docs.append(
                    Document(
                        page_content=new_content,
                        metadata=next_meta,
                        id=doc.id,
                    )
                )
            elif next_meta != original_meta:
                processed_docs.append(
                    Document(
                        page_content=content,
                        metadata=next_meta,
                        id=doc.id,
                    )
                )
            else:
                processed_docs.append(doc)

        return InlineAssetResult(
            documents=processed_docs,
            uploaded_img_ids=uploaded,
            next_asset_index=asset_idx,
            image_codes_added=int(image_codes_added_total),
            image_code_audit=(dict(image_code_audit) if isinstance(image_code_audit, dict) else None),
            captions_added=int(captions_added_total),
            caption_backend=caption_backend,
            caption_audit=(dict(caption_audit) if isinstance(caption_audit, dict) else None),
            formulas_added=int(formulas_added_total),
            formula_backend=formula_backend,
            formula_audit=(dict(formula_audit) if isinstance(formula_audit, dict) else None),
            charts_added=int(charts_added_total),
            chart_backend=chart_backend,
            chart_audit=(dict(chart_audit) if isinstance(chart_audit, dict) else None),
        )


class GovernanceStage:
    def run(
        self,
        *,
        items: list[Document],
        enabled: bool,
        kwargs: dict[str, Any],
    ) -> GovernanceResult:
        if not enabled:
            return GovernanceResult(items=items, stats=None)
        cleaned, stats = governance_processor.clean_documents(items, **kwargs)
        return GovernanceResult(items=cleaned, stats=stats)


class NormalizeStage:
    """
    Apply conservative normalization before governance/chunking.

    Unlike governance cleaning, this stage is always safe to run:
    - Normalizes line endings and Unicode whitespace artifacts
    - Removes zero-width/control characters and soft hyphens
    - Repairs common PDF ligatures
    """

    def run(self, *, items: list[Document]) -> list[Document]:
        if not items:
            return items
        out: list[Document] = []
        for doc in items:
            raw = doc.page_content or ""
            normalized = normalize_text(raw, normalize_line_endings=True, remove_control_chars=True)
            canon = canonicalize_markdown(normalized)
            meta = dict(doc.metadata or {})
            meta["text_normalized"] = True
            meta["text_normalized_changed"] = bool(normalized != raw)
            meta["markdown_canonicalized"] = True
            meta["markdown_canonical_changed"] = bool(canon.changed)
            meta["markdown_canonical_stats"] = {
                "headings_changed": int(canon.headings_changed),
                "list_markers_changed": int(canon.list_markers_changed),
                "ordered_list_markers_changed": int(canon.ordered_list_markers_changed),
                "code_fences_changed": int(canon.code_fences_changed),
                "tables": int(canon.tables),
                "table_rows_changed": int(canon.table_rows_changed),
            }
            out.append(Document(page_content=canon.text, metadata=meta, id=getattr(doc, "id", None)))
        return out


class ChunkingStage:
    def run(
        self,
        *,
        documents: list[Document],
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        chunk_strategy_params: dict[str, Any] | None = None,
        chunk_python_plugin: str = "",
        chunk_python_params: dict[str, Any] | None = None,
    ) -> ChunkingResult:
        logger.info("Chunking document into smaller pieces...")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        params = dict(chunk_strategy_params or {})
        plugin_ref = str(chunk_python_plugin or "").strip()
        if plugin_ref:
            plugin_params = {**params, **dict(chunk_python_params or {})}
            chunks = apply_chunk_python_plugin(
                documents,
                plugin_ref=plugin_ref,
                params=plugin_params,
                context={
                    "chunk_strategy": chunk_strategy,
                    "chunk_size": int(chunk_size),
                    "chunk_overlap": int(chunk_overlap),
                },
            )
            return ChunkingResult(chunks=chunks)

        def _to_bool(v: object) -> bool | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                s = v.strip().lower()
                if s in {"1", "true", "yes", "y", "on"}:
                    return True
                if s in {"0", "false", "no", "n", "off"}:
                    return False
            return None

        def _to_int(v: object) -> int | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, (int, float)):
                try:
                    return int(v)
                except (TypeError, ValueError, AttributeError):
                    return None
            if isinstance(v, str):
                try:
                    return int(float(v.strip()))
                except (TypeError, ValueError, AttributeError):
                    return None
            return None

        def _to_float(v: object) -> float | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return float(v)
            if isinstance(v, (int, float)):
                try:
                    return float(v)
                except (TypeError, ValueError, AttributeError):
                    return None
            if isinstance(v, str):
                try:
                    return float(v.strip())
                except (TypeError, ValueError, AttributeError):
                    return None
            return None

        # Separator chunking needs preset/custom mapping (preview supports this too).
        if (chunk_strategy or "").strip().lower() == "separator":
            preset = str(params.get("separator_preset") or "").strip() or "paragraph"
            if preset != "custom":
                sep_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
                if sep_value is None:
                    raise ValueError(f"Invalid separator_preset: {preset}")
            else:
                raw = params.get("separator")
                if raw is None:
                    raw = params.get("separator_custom")
                sep_value = str(raw or "")
                if not sep_value:
                    sep_value = "\n\n"
                # Support common escaped inputs like "\\n\\n" (match frontend behavior).
                try:
                    import json as _json  # local import to keep module deps minimal

                    escaped = sep_value.replace("\"", "\\\"")
                    sep_value = _json.loads(f"\"{escaped}\"")
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

            keep_sep = params.get("keep_separator")
            keep_sep_norm = _to_bool(keep_sep)
            if keep_sep_norm is None:
                keep_sep = True
            else:
                keep_sep = keep_sep_norm

            max_chunk_size = _to_int(params.get("separator_max_chunk_size"))
            if max_chunk_size is None:
                max_chunk_size = _to_int(params.get("max_chunk_size"))
            max_chunk_size = int(max_chunk_size or 0)

            chunker = SeparatorChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=sep_value,
                keep_separator=bool(keep_sep),
                max_chunk_size=max_chunk_size,
            )
        else:
            # Common numeric coercions for strategy kwargs (avoid accidental string types from patches).
            if "child_ratio" in params:
                r = _to_float(params.get("child_ratio"))
                if r is not None:
                    params["child_ratio"] = r
            if "min_child_size" in params:
                n = _to_int(params.get("min_child_size"))
                if n is not None:
                    params["min_child_size"] = n

            chunker = chunker_factory.get_chunker(
                chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                **params,
            )
        return ChunkingResult(chunks=chunker.split_documents(documents))


class ChunkDedupStage:
    @staticmethod
    def _chunk_digest_metadata(chunk: Document) -> tuple[str, dict[str, Any]]:
        raw = chunk.page_content or ""
        normalized = normalize_text(raw, normalize_line_endings=True, remove_control_chars=True)
        digest = hashlib.sha256(normalized.strip().encode("utf-8", "ignore")).hexdigest()

        meta = dict(chunk.metadata or {})
        meta.setdefault("content_hash", digest)
        meta.setdefault("content_hash_algo", "sha256")
        meta.setdefault("content_len", len(normalized.strip()))
        return digest, meta

    @staticmethod
    def _chunk_has_asset(meta: dict[str, Any]) -> bool:
        doc_type = str(meta.get("doc_type_kwd") or "").lower()
        return (
            doc_type in {"image", "table"}
            or meta.get("image") is not None
            or bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url"))
        )

    @staticmethod
    def _record_identity_key(meta: dict[str, Any]) -> str | None:
        record_identity = meta.get("_record_identity")
        if not isinstance(record_identity, dict):
            return None
        key = str(record_identity.get("key") or "").strip()
        return key or None

    @classmethod
    def _duplicate_text_chunk(
        cls,
        *,
        digest: str,
        meta: dict[str, Any],
        seen: set[tuple[str, str | None]],
    ) -> bool:
        if cls._chunk_has_asset(meta):
            return False
        dedup_key = (digest, cls._record_identity_key(meta))
        if dedup_key in seen:
            return True
        seen.add(dedup_key)
        return False

    def run(self, *, chunks: list[Document], enabled: bool) -> ChunkDedupResult:
        """
        Drop exact-duplicate *text* chunks within a single document.

        Notes:
        - Keeps image/table-related chunks even if their text matches (assets matter).
        - Uses a normalized content hash for comparison (line endings/control chars).
        """
        if not enabled or not chunks:
            return ChunkDedupResult(chunks=chunks, duplicates_dropped=0)

        seen: set[tuple[str, str | None]] = set()
        out: list[Document] = []
        dropped = 0

        for c in chunks:
            digest, meta = self._chunk_digest_metadata(c)
            if self._duplicate_text_chunk(digest=digest, meta=meta, seen=seen):
                dropped += 1
                continue

            out.append(Document(page_content=c.page_content, metadata=meta, id=getattr(c, "id", None)))

        return ChunkDedupResult(chunks=out, duplicates_dropped=dropped)


class ChunkAssetStage:
    def __init__(self, service: "DocumentProcessorService"):
        self._svc = service

    def run(
        self,
        *,
        chunks: list[Document],
        tenant_id: UUID,
        document_id: UUID,
        options: ChunkAssetOptions,
    ) -> ChunkAssetResult:
        from app.parsing.enrich.image_understanding import (
            append_image_understanding_text,
            decode_image_codes,
            derive_image_caption,
            infer_visual_kind_from_pixels,
            load_image_for_ocr,
            ocr_image,
        )
        from app.parsing.enrich.ocr_redaction import redact_ocr_text
        from app.services.chunk_quality_scoring import score_chunk_quality

        dataset_id = options.dataset_id
        resolved_backend = options.resolved_backend
        resolved_chunk_strategy = options.resolved_chunk_strategy
        image_caption_enabled = options.image_caption_enabled
        image_ocr_enabled = options.image_ocr_enabled
        image_ocr_max_chars = options.image_ocr_max_chars
        pii_anonymize = options.pii_anonymize
        pii_mode = options.pii_mode
        pii_mask = options.pii_mask
        secrets_redact = options.secrets_redact
        secrets_mode = options.secrets_mode
        secrets_mask = options.secrets_mask

        max_images = max(0, int(options.image_ocr_max_images or 0))
        ocr_remaining: int | None = (max_images if max_images > 0 else None)

        img_ids: list[str] = []
        out_chunks: list[Document] = []
        out_idx = 0
        seen_ocr_hashes: set[str] = set()

        for chunk in chunks:
            # Assign chunk_index in output order (may differ from input order when we emit OCR chunks).
            idx = int(out_idx)
            meta = dict(chunk.metadata or {})
            meta.setdefault("dataset_id", str(dataset_id))
            meta["document_id"] = str(document_id)
            meta["chunk_index"] = idx
            meta["parser_backend"] = resolved_backend
            meta.setdefault("chunk_strategy", resolved_chunk_strategy)
            meta["resolved_chunk_strategy"] = resolved_chunk_strategy
            meta.setdefault("chunk_key", f"{str(document_id)}:{idx}")
            normalize_section_metadata(meta)
            ensure_hierarchy_overlay_metadata(
                meta,
                document_id=str(document_id),
                chunk_index=idx,
            )

            # Image understanding (best-effort): keep it off by default; never fail ingest.
            caption = ""
            ocr_text = ""
            image_code_text = ""
            doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
            if doc_type == "image":
                # Structural chunk roles: keep this lightweight and deterministic so downstream
                # can filter/rerank image vs OCR chunks explicitly.
                meta.setdefault("chunk_role", "image")
                if bool(image_caption_enabled):
                    try:
                        caption = derive_image_caption(chunk.page_content or "", meta)
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        caption = ""
                need_image_inspection = (
                    not str(meta.get("visual_kind") or "").strip()
                    or not str(meta.get("image_code_text") or "").strip()
                    or (bool(image_ocr_enabled) and (ocr_remaining is None or ocr_remaining > 0))
                )
                if need_image_inspection:
                    img, should_close = load_image_for_ocr(meta, _tenant_id=str(tenant_id))
                    try:
                        if img is not None:
                            try:
                                code_info = decode_image_codes(img)
                            except Exception as exc:
                                _log_processor_fallback('run', exc)
                                code_info = {}
                            if isinstance(code_info, dict):
                                image_code_text = str(code_info.get("text") or "").strip()
                                if image_code_text:
                                    meta["image_code_text"] = image_code_text
                                    raw_values = code_info.get("values")
                                    if isinstance(raw_values, list):
                                        meta["image_code_values"] = [str(item).strip() for item in raw_values if str(item).strip()]
                                visual_kind = str(code_info.get("visual_kind") or "").strip().lower()
                                if visual_kind:
                                    meta["visual_kind"] = visual_kind
                            if not str(meta.get("visual_kind") or "").strip():
                                try:
                                    visual_kind = str(infer_visual_kind_from_pixels(img) or "").strip().lower()
                                except Exception as exc:
                                    _log_processor_fallback('run', exc)
                                    visual_kind = ""
                                if visual_kind:
                                    meta["visual_kind"] = visual_kind
                            if bool(image_ocr_enabled) and (ocr_remaining is None or ocr_remaining > 0):
                                ocr_text = ocr_image(img, _max_chars=int(image_ocr_max_chars))
                                if ocr_remaining is not None:
                                    ocr_remaining -= 1
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        ocr_text = ""
                    finally:
                        if should_close and img is not None:
                            try:
                                img.close()
                            except Exception as exc:
                                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

                # Policy-driven safety: OCR/caption text is appended after governance cleaning, so apply
                # PII/secret redactions here (best-effort).
                if caption:
                    try:
                        caption, _pii_hits, _sec_hits = redact_ocr_text(
                            caption,
                            pii_anonymize=bool(pii_anonymize),
                            pii_mode=str(pii_mode or "mask"),
                            pii_mask=str(pii_mask or REDACTED_MASK),
                            secrets_redact=bool(secrets_redact),
                            secrets_mode=str(secrets_mode or "mask"),
                            secrets_mask=str(secrets_mask or SECRET_MASK),
                        )
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        # Fail-closed when redaction is enabled: do not emit raw caption.
                        if bool(pii_anonymize) or bool(secrets_redact):
                            caption = str(pii_mask or REDACTED_MASK) if bool(pii_anonymize) else str(secrets_mask or SECRET_MASK)
                if caption:
                    meta["image_caption"] = caption

                if ocr_text:
                    try:
                        ocr_text, pii_hits, sec_hits = redact_ocr_text(
                            ocr_text,
                            pii_anonymize=bool(pii_anonymize),
                            pii_mode=str(pii_mode or "mask"),
                            pii_mask=str(pii_mask or REDACTED_MASK),
                            secrets_redact=bool(secrets_redact),
                            secrets_mode=str(secrets_mode or "mask"),
                            secrets_mask=str(secrets_mask or SECRET_MASK),
                        )
                        if pii_hits:
                            meta["image_ocr_pii_hits"] = {str(k): int(v) for k, v in pii_hits.items() if int(v or 0) > 0}
                        if sec_hits:
                            meta["image_ocr_secrets_hits"] = {str(k): int(v) for k, v in sec_hits.items() if int(v or 0) > 0}
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        # Fail-closed when redaction is enabled: do not emit raw OCR.
                        if bool(pii_anonymize) or bool(secrets_redact):
                            ocr_text = str(pii_mask or REDACTED_MASK) if bool(pii_anonymize) else str(secrets_mask or SECRET_MASK)
                        else:
                            ocr_text = ""
                    if ocr_text:
                        meta["image_ocr_text"] = ocr_text
                        meta["image_ocr_chars"] = len(ocr_text)

                # Keep OCR in the image chunk content for backwards compatibility (retrieval expects it),
                # but also emit an OCR-only chunk (role="ocr") to enable dedup and explicit filtering.
                if caption or ocr_text or image_code_text:
                    chunk.page_content = append_image_understanding_text(
                        chunk.page_content or "",
                        caption=caption,
                        ocr_text=ocr_text,
                        code_text=image_code_text,
                    )

            content_norm = normalize_text(chunk.page_content or "", normalize_line_endings=True, remove_control_chars=True)
            meta.setdefault("content_len", len(content_norm.strip()))
            infer_chunk_structure(meta, content_norm)
            # Per-chunk quality scoring (noise/boilerplate) for debug + downstream filtering.
            try:
                meta.setdefault("chunk_quality", score_chunk_quality(content_norm, meta=meta))
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            # Lightweight semantic role labels (deterministic): helps filtering/reranking.
            # Keep separate from existing `chunk_role` (parent/child/qa/etc).
            try:
                meta.setdefault(
                    "chunk_semantic_role",
                    classify_chunk_semantic_role(content=content_norm, meta=meta),
                )
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            try:
                meta.setdefault(
                    "chunk_type",
                    classify_chunk_type(content=content_norm, meta=meta),
                )
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            if not isinstance(meta.get("content_hash"), str) or not str(meta.get("content_hash") or "").strip():
                meta["content_hash"] = hashlib.sha256(content_norm.strip().encode("utf-8", "ignore")).hexdigest()
                meta.setdefault("content_hash_algo", "sha256")
            if not isinstance(meta.get("simhash64"), str) or not str(meta.get("simhash64") or "").strip():
                try:
                    meta["simhash64"] = simhash64_hex(simhash64(content_norm))
                    meta.setdefault("simhash_algo", "simhash64_sha1")
                except Exception as exc:
                    _log_processor_fallback('run', exc)
                    # Best-effort only.
            chunk.metadata = meta

            img_id = self._svc._extract_and_upload_image_to_minio(
                meta,
                tenant_id=str(tenant_id),
                dataset_id=dataset_id,
                document_id=str(document_id),
                chunk_index=idx,
            )
            if not img_id:
                img_id = self._svc._extract_img_id_from_content(chunk.page_content)
            if img_id:
                meta["img_id"] = img_id
                normalize_image_metadata(meta)
                chunk.metadata = meta
                img_ids.append(img_id)

            # Emit the (possibly enriched) base chunk.
            out_chunks.append(Document(page_content=chunk.page_content or "", metadata=meta, id=getattr(chunk, "id", None)))
            out_idx += 1

            # Optional: OCR child chunk (dedup by OCR text hash).
            if doc_type == "image" and ocr_text:
                ocr_norm = normalize_text(ocr_text, normalize_line_endings=True, remove_control_chars=True).strip()
                ocr_hash = hashlib.sha256(ocr_norm.encode("utf-8", "ignore")).hexdigest() if ocr_norm else ""
                if ocr_hash and ocr_hash not in seen_ocr_hashes:
                    seen_ocr_hashes.add(ocr_hash)
                    ocr_meta = dict(meta)
                    ocr_meta["chunk_index"] = int(out_idx)
                    ocr_meta["chunk_key"] = f"{str(document_id)}:{int(out_idx)}"
                    ocr_meta["doc_type_kwd"] = "ocr"
                    ocr_meta["content_type"] = "ocr"
                    ocr_meta["chunk_role"] = "ocr"
                    ocr_meta["image_parent_chunk_index"] = int(idx)
                    ensure_hierarchy_overlay_metadata(
                        ocr_meta,
                        document_id=str(document_id),
                        chunk_index=int(out_idx),
                    )
                    # Recompute content-derived fields for OCR chunk.
                    for k in ("content_hash", "content_hash_algo", "content_len", "simhash64", "simhash_algo", "structure", "chunk_semantic_role", "chunk_type"):
                        ocr_meta.pop(k, None)
                    ocr_meta["ocr_text_hash"] = str(ocr_hash)
                    ocr_meta.setdefault("ocr_text_hash_algo", "sha256")

                    ocr_content_norm = normalize_text(ocr_text, normalize_line_endings=True, remove_control_chars=True)
                    ocr_meta.setdefault("content_len", len(ocr_content_norm.strip()))
                    infer_chunk_structure(ocr_meta, ocr_content_norm)
                    try:
                        ocr_meta.setdefault("chunk_quality", score_chunk_quality(ocr_content_norm, meta=ocr_meta))
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    try:
                        ocr_meta.setdefault(
                            "chunk_semantic_role",
                            classify_chunk_semantic_role(content=ocr_content_norm, meta=ocr_meta),
                        )
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    try:
                        ocr_meta.setdefault(
                            "chunk_type",
                            classify_chunk_type(content=ocr_content_norm, meta=ocr_meta),
                        )
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    ocr_meta["content_hash"] = hashlib.sha256(ocr_content_norm.strip().encode("utf-8", "ignore")).hexdigest()
                    ocr_meta.setdefault("content_hash_algo", "sha256")
                    try:
                        ocr_meta["simhash64"] = simhash64_hex(simhash64(ocr_content_norm))
                        ocr_meta.setdefault("simhash_algo", "simhash64_sha1")
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

                    out_chunks.append(Document(page_content=ocr_text, metadata=ocr_meta))
                    out_idx += 1

        # Adjacency graph (prev/next) for stitching + UI diagnostics:
        # - Stored in chunk metadata so it survives persistence/indexing.
        # - Computed on the final emitted chunk order (including OCR-only chunks).
        total_out = len(out_chunks)
        for i, doc in enumerate(out_chunks):
            meta = dict(getattr(doc, "metadata", None) or {})
            prev_idx = (i - 1) if i > 0 else None
            next_idx = (i + 1) if i < (total_out - 1) else None
            meta["prev_chunk_index"] = prev_idx
            meta["next_chunk_index"] = next_idx
            doc_id = str(meta.get("document_id") or document_id)
            meta["prev_chunk_key"] = f"{doc_id}:{prev_idx}" if prev_idx is not None else None
            meta["next_chunk_key"] = f"{doc_id}:{next_idx}" if next_idx is not None else None
            ensure_hierarchy_overlay_metadata(
                meta,
                document_id=doc_id,
                chunk_index=i,
                total_chunks=total_out,
            )
            doc.metadata = meta
        apply_sequence_hierarchy_metadata(
            [doc.metadata for doc in out_chunks if isinstance(getattr(doc, "metadata", None), dict)],
            document_id=str(document_id),
            basis="chunk_sequence",
            level="chunk",
        )

        return ChunkAssetResult(chunks=out_chunks, img_ids=img_ids)


class IndexStage:
    def run(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        file_path: Path,
        default_source: str,
        chunks: list[Document],
        options,
    ) -> IndexResult:
        logger.info("Persisting chunks and indexes...")
        records: list[IndexRecord] = []
        for chunk in chunks:
            meta = dict(chunk.metadata or {})
            content = normalize_text(chunk.page_content or "", normalize_line_endings=True, remove_control_chars=True)
            records.append(
                IndexRecord(
                    kind=IndexKind.CHUNK,
                    content=content,
                    metadata=meta,
                    document_id=document_id,
                    page_number=meta.get("page") or meta.get("page_number"),
                    start_char=meta.get("start_char"),
                    end_char=meta.get("end_char"),
                )
            )

        persist_result = Indexer(db).upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=str(default_source or "").strip() or str(file_path.name),
            commit=False,
            options=options,
        ).chunk_result
        if persist_result is None:
            raise RuntimeError("Chunk indexing returned no result")
        return IndexResult(
            chunk_ids=persist_result.chunk_ids,
            total_characters=persist_result.total_characters,
            db_chunks=persist_result.db_chunks,
        )


class DocumentProcessorService:
    """Document processing service."""

    def __init__(self):
        pass

    # Preset strategies (parse + chunk directly).
    INTEGRATED_PIPELINE_STRATEGIES = {"integrated_naive", "integrated_book", "integrated_laws", "integrated_email"}

    def _build_cancel_check(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        poll_interval_sec: float = 1.0,
    ):
        """
        Build a cached cancel-check closure.

        This is shared by:
        - ingest pipeline (DocumentProcessorService)
        - parsing subprocess runner (ParsingStage)
        """
        last_check = 0.0
        cached_cancel = False

        async def cancel_check(*, force: bool = False) -> bool:
            nonlocal last_check, cached_cancel
            await asyncio.sleep(0)
            now = time.monotonic()
            if not force and (now - last_check) < float(poll_interval_sec):
                return cached_cancel
            last_check = now
            db_doc = (
                db.query(DBDocument)
                .populate_existing()
                .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                .first()
            )
            if not db_doc:
                cached_cancel = True
                return True
            status = str(db_doc.status or "").lower()
            if status == "cancelled":
                cached_cancel = True
                return True
            meta = db_doc.doc_metadata or {}
            if isinstance(meta, dict) and bool(meta.get("cancel_requested")):
                cached_cancel = True
                return True
            cached_cancel = False
            return False

        return cancel_check

    def _rollback_and_cleanup_indexes(
        self,
        db: Session,
        *,
        db_document: DBDocument,
        tenant_id: UUID,
        document_id: UUID,
    ) -> None:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

        try:
            meta = dict(getattr(db_document, "doc_metadata", None) or {})
            active_hash = str(meta.get("active_pipeline_hash") or "").strip()
            cur_hash = str(meta.get("pipeline_hash") or "").strip()
            active_ready = bool(meta.get("active_pipeline_ready"))
            if active_ready and active_hash and cur_hash and cur_hash != active_hash:
                Indexer(db).delete_chunk_indexes_for_doc_pipeline_key(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    doc_pipeline_key=f"{document_id}:{cur_hash}",
                )
            else:
                Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    def _apply_pending_retry_cleanup(
        self,
        db: Session,
        *,
        db_document: DBDocument,
        tenant_id: UUID,
        document_id: UUID,
    ) -> bool:
        meta = dict(getattr(db_document, "doc_metadata", None) or {})
        request = meta.get("retry_cleanup")
        if request is None:
            return True
        if not isinstance(request, dict) or str(request.get("version") or "") != "1":
            logger.error("Refusing unknown retry cleanup intent for document %s", document_id)
            return False

        pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
        scope = str(request.get("scope") or "").strip()
        target_key = str(request.get("doc_pipeline_key") or "").strip()
        if str(request.get("pipeline_hash") or "").strip() != pipeline_hash or scope not in {"document", "pipeline"}:
            logger.error("Refusing stale retry cleanup intent for document %s", document_id)
            return False
        if scope == "pipeline" and target_key != f"{document_id}:{pipeline_hash}":
            logger.error("Refusing invalid scoped retry cleanup intent for document %s", document_id)
            return False

        preserve_existing = scope == "pipeline"
        indexer = Indexer(db)
        cleanup_chunk_ids: list[UUID] = []

        if bool(request.get("force")):
            meta.pop("ingest_checkpoint", None)
            meta.pop("parsed_content_persisted", None)
            db.query(DocumentParsedContent).filter(
                DocumentParsedContent.document_id == document_id,
                DocumentParsedContent.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

        if preserve_existing:
            cleanup_chunk_ids = [
                chunk_id
                for (chunk_id,) in (
                    db.query(DocumentChunk.id)
                    .filter(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.tenant_id == tenant_id,
                        DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
                    )
                    .all()
                )
                if isinstance(chunk_id, UUID)
            ]
            indexer.delete_chunk_indexes_for_doc_pipeline_key(
                tenant_id=tenant_id,
                document_id=document_id,
                doc_pipeline_key=target_key,
            )
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
        else:
            indexer.delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
            ).delete(synchronize_session=False)
            meta.pop("img_ids", None)
            db_document.chunk_count = 0
            db_document.total_characters = 0

        db_document.doc_metadata = meta
        db.commit()

        try:
            from app.rag.kg.models import KgRelation

            relation_query = db.query(KgRelation).filter(KgRelation.tenant_id == tenant_id)
            if preserve_existing:
                if cleanup_chunk_ids:
                    relation_query.filter(KgRelation.chunk_id.in_(cleanup_chunk_ids)).delete(synchronize_session=False)
                    indexer.delete_event_indexes_for_chunks(
                        tenant_id=tenant_id,
                        chunk_ids=cleanup_chunk_ids,
                        commit=False,
                        prune_orphan_entities=True,
                    )
            else:
                relation_query.filter(KgRelation.document_id == document_id).delete(synchronize_session=False)
                indexer.delete_event_indexes(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    commit=False,
                    prune_orphan_entities=True,
                )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Failed to clean retry KG indexes for document %s: %s", document_id, str(exc)[:200])

        meta = dict(getattr(db_document, "doc_metadata", None) or {})
        meta.pop("retry_cleanup", None)
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
        return True

    async def process_document(
        self,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        parser_backend: str | None = None,
        chunk_strategy: str | None = None,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """
        Full document processing flow.

        Steps:
        1. Parse document
        2. Split text
        3. Generate embeddings
        4. Persist to vector store
        5. Persist to database

        Args:
            file_path: Path to the file
            document_id: Document ID
            db: Database session

        Returns:
            Processing result
        """
        owns_db = False
        if db is None:
            db = SessionLocal()
            owns_db = True

        preprocessed_temp_path: Path | None = None
        try:
            cancel_check = self._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

            stage_durations_ms: dict[str, int] = {}

            def _add_stage_duration(stage: str, elapsed_ms: float) -> None:
                try:
                    key = str(stage or "").strip()
                    if not key:
                        return
                    ms = int(round(float(elapsed_ms)))
                except (TypeError, ValueError, AttributeError):
                    return
                if ms < 0:
                    ms = 0
                stage_durations_ms[key] = int(stage_durations_ms.get(key, 0) or 0) + ms

            def _with_stage_durations(meta: dict[str, Any] | None) -> dict[str, Any]:
                out = dict(meta or {})
                if stage_durations_ms:
                    out["ingest_stage_durations_ms"] = dict(stage_durations_ms)
                return out

            async def raise_if_cancelled(*, force: bool = False) -> None:
                if await cancel_check(force=force):
                    raise DocumentCancelledError("cancel_requested")

            db_document = (
                db.query(DBDocument)
                .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                .first()
            )
            if db_document is None:
                logger.warning("Document not found for processing: tenant=%s document=%s", tenant_id, document_id)
                return {"status": "skipped", "reason": "document_not_found"}

            # If user already cancelled before the worker started, stop immediately.
            await raise_if_cancelled(force=True)

            if not self._apply_pending_retry_cleanup(
                db,
                db_document=db_document,
                tenant_id=tenant_id,
                document_id=document_id,
            ):
                await self._update_status(
                    db,
                    tenant_id,
                    document_id,
                    "failed",
                    0,
                    "failed",
                    error_message="invalid_retry_cleanup_intent",
                )
                return {"status": "failed", "reason": "invalid_retry_cleanup_intent"}

            # Step 1: update status to processing.
            await self._update_status(
                db, tenant_id, document_id, "processing", 0, "parsing"
            )

            # Resolve dataset_id early (MinerU ZIP / MinIO paths depend on it).
            dataset_id = str(db_document.dataset_id) if db_document.dataset_id else str(tenant_id)

            # Bind metrics context for this coroutine/task (best-effort; used only when ENABLE_METRICS_LOG=true).
            set_metrics_context(tenant_id=tenant_id, document_id=document_id, dataset_id=dataset_id)

            # Track all img_id values linked to this document (used for cleanup).
            document_img_ids: set[str] = set()
            artifact_dirs: set[str] = set()

            dataset_meta: dict[str, Any] = {}
            if db_document.dataset_id:
                ds = (
                    db.query(Dataset)
                    .filter(Dataset.id == db_document.dataset_id, Dataset.tenant_id == tenant_id)
                    .first()
                )
                if ds is not None and isinstance(getattr(ds, "dataset_metadata", None), dict):
                    dataset_meta = dict(ds.dataset_metadata or {})

            pipeline_effective = resolve_pipeline_effective(
                dataset_metadata=dataset_meta,
                document_metadata=(db_document.doc_metadata or {}),
                request_overrides=None,
            )
            index_options = build_indexing_options(pipeline_effective)
            self._record_pipeline_effective(db, tenant_id, document_id, pipeline_effective)
            table_sidecar_tables_imported = 0
            table_sidecar_routing_audit: dict[str, Any] | None = None

            if bool(getattr(pipeline_effective, "ingest_pre_poc_scanner_enabled", False)):
                try:
                    from app.services.ingest_pre_poc_quality_gate import evaluate_ingest_pre_poc_quality_gate

                    t0 = time.perf_counter()
                    with metrics_span("ingest.pre_poc_quality_gate", file_ext=file_path.suffix.lower()):
                        pre_poc_gate = evaluate_ingest_pre_poc_quality_gate(
                            file_path,
                            enabled=True,
                            mode=str(getattr(pipeline_effective, "ingest_pre_poc_quality_gate_mode", "warn") or "warn"),
                        )
                    _add_stage_duration("pre_poc_quality_gate", (time.perf_counter() - t0) * 1000)
                    next_meta = dict(db_document.doc_metadata or {})
                    next_meta["pre_poc_quality_gate"] = pre_poc_gate
                    next_meta = apply_parse_quality_gate_metadata(next_meta)
                    db_document.doc_metadata = next_meta
                    db.commit()
                    db.refresh(db_document)
                    if bool(pre_poc_gate.get("blocked")):
                        msg = "Document blocked by Pre-POC quality gate"
                        await self._update_status(
                            db,
                            tenant_id,
                            document_id,
                            "failed",
                            0,
                            "failed",
                            chunk_count=0,
                            total_characters=0,
                            error_message=msg,
                            doc_metadata=_with_stage_durations(next_meta),
                        )
                        return {
                            "status": "failed",
                            "reason": "pre_poc_quality_gate_blocked",
                            "chunk_count": 0,
                            "total_characters": 0,
                            "parser_backend": parser_backend or "auto",
                            "chunk_strategy": chunk_strategy or "auto",
                        }
                except Exception as exc:  # noqa: BLE001
                    _log_processor_fallback('process_document', exc)
                    if str(getattr(pipeline_effective, "ingest_pre_poc_quality_gate_mode", "warn") or "warn").lower() == "strict":
                        raise RuntimeError(f"pre_poc_quality_gate_failed: {str(exc)[:200]}") from exc

            # Optional: file-level preprocessing before parsing (configured via ingestion policy).
            try:
                meta = db_document.doc_metadata or {}
                ingestion = meta.get("ingestion") if isinstance(meta, dict) else None
                preprocess_cfg = ingestion.get("preprocess") if isinstance(ingestion, dict) else None
                steps = preprocess_cfg.get("steps") if isinstance(preprocess_cfg, dict) else None
                if isinstance(steps, list) and steps:
                    t0 = time.perf_counter()
                    with metrics_span("ingest.preprocess", file_ext=file_path.suffix.lower()):
                        result = preprocess_file(input_path=file_path, steps=steps)
                    _add_stage_duration("preprocess", (time.perf_counter() - t0) * 1000)
                    # Persist a lightweight audit record for debugging/tuning (best-effort).
                    try:
                        next_meta = dict(db_document.doc_metadata or {})
                        next_meta["preprocess"] = result.to_dict()
                        db_document.doc_metadata = next_meta
                        db.commit()
                        db.refresh(db_document)
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    if bool(getattr(result, "changed", False)):
                        out_path = Path(str(getattr(result, "output_path", "") or "")).resolve(strict=False)
                        preprocessed_temp_path = out_path
                        file_path = out_path
            except Exception as exc:  # noqa: BLE001
                _log_processor_fallback('process_document', exc)
                # Fail closed: when preprocessing is enabled, it is part of ingestion correctness.
                raise RuntimeError(f"preprocess_failed: {str(exc)[:200]}") from exc

            # Optional: image-level preprocessing before parsing (deskew/orientation/watermark).
            # This is disabled by default to keep baseline ingest behavior unchanged.
            try:
                if bool(getattr(settings, "IMAGE_PREPROCESS_ENABLED", False)):
                    ext = file_path.suffix.lower()
                    if ext == ".pdf" or ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                        t0 = time.perf_counter()
                        with metrics_span("ingest.image_preprocess", file_ext=ext):
                            pdf_quality = None
                            if ext == ".pdf":
                                try:
                                    from app.parsing.quality.scorer import score_pdf_quality

                                    pdf_quality = score_pdf_quality(
                                        file_path,
                                        sample_pages=int(getattr(settings, "PREPROCESS_SAMPLE_PAGES", 3) or 3),
                                        use_ocr_validation=False,
                                    )
                                    # Persist early so downstream routing can reuse it (best-effort).
                                    try:
                                        if isinstance(pdf_quality, dict) and pdf_quality.get("score") is not None:
                                            next_meta = dict(db_document.doc_metadata or {})
                                            next_meta["pdf_quality"] = pdf_quality
                                            db_document.doc_metadata = next_meta
                                            db.commit()
                                            db.refresh(db_document)
                                    except Exception as exc:
                                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                                except Exception as exc:
                                    _log_processor_fallback('process_document', exc)
                                    pdf_quality = None
                            result = preprocess_image_document(
                                input_path=file_path,
                                document_id=str(document_id) if document_id else None,
                                pdf_quality=pdf_quality,
                            )
                        _add_stage_duration("image_preprocess", (time.perf_counter() - t0) * 1000)
                        # Persist a lightweight audit record for debugging/tuning (best-effort).
                        try:
                            next_meta = dict(db_document.doc_metadata or {})
                            next_meta["image_preprocess"] = result.to_dict()
                            db_document.doc_metadata = next_meta
                            db.commit()
                            db.refresh(db_document)
                        except Exception as exc:
                            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                        if bool(getattr(result, "changed", False)):
                            out_path = Path(str(getattr(result, "output_path", "") or "")).resolve(strict=False)
                            preprocessed_temp_path = out_path
                            file_path = out_path
            except Exception as exc:  # noqa: BLE001
                _log_processor_fallback('process_document', exc)
                raise RuntimeError(f"image_preprocess_failed: {str(exc)[:200]}") from exc

            # Structured Table Store (TAG): optionally import table-like documents and skip chunk/vector ingestion.
            #
            # Default behavior (table_store_auto_route=false):
            # - table_store_enabled=true  => always import table docs into SQLite (TAG) and short-circuit RAG indexing
            #
            # Auto routing (table_store_auto_route=true):
            # - small tables => fall back to normal parsing+chunking+indexing (RAG)
            # - large/complex tables => import into SQLite store (TAG)
            if (
                bool(getattr(pipeline_effective, "table_store_enabled", False))
                and db_document.dataset_id is not None
                and file_path.suffix.lower() in {".csv", ".xls", ".xlsx"}
            ):
                # Decide whether this file should go to TAG or remain in the RAG pipeline.
                table_decision = None
                try:
                    from app.services.table_routing import decide_table_route

                    table_decision = decide_table_route(
                        file_path=file_path,
                        auto_route=bool(getattr(pipeline_effective, "table_store_auto_route", False)),
                        file_bytes_threshold=int(getattr(pipeline_effective, "table_store_auto_file_bytes_threshold", 0) or 0),
                        row_threshold=int(getattr(pipeline_effective, "table_store_auto_row_threshold", 0) or 0),
                        col_threshold=int(getattr(pipeline_effective, "table_store_auto_col_threshold", 0) or 0),
                        sheet_threshold=int(getattr(pipeline_effective, "table_store_auto_sheet_threshold", 0) or 0),
                    )
                except Exception as exc:
                    _log_processor_fallback('process_document', exc)
                    table_decision = None

                # Persist routing decision for audit/debug (best-effort; never fail ingestion).
                if table_decision is not None:
                    try:
                        next_meta = dict(db_document.doc_metadata or {})
                        next_meta["table_routing"] = {
                            "version": "1",
                            "route": getattr(table_decision, "route", None),
                            "reason": getattr(table_decision, "reason", None),
                            "stats": dict(getattr(table_decision, "stats", None) or {}),
                        }
                        db_document.doc_metadata = next_meta
                        db.commit()
                        db.refresh(db_document)
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

                # When auto-route says "rag", continue the normal parsing+indexing pipeline.
                should_tag = True
                if table_decision is not None and str(getattr(table_decision, "route", "") or "").lower() == "rag":
                    should_tag = False

                if should_tag:
                    await raise_if_cancelled(force=True)
                    await self._update_status(db, tenant_id, document_id, "processing", 15, "table_import")
                    try:
                        from app.services.table_store_service import import_table_document

                        t0 = time.perf_counter()
                        assets = import_table_document(
                            tenant_id=tenant_id,
                            dataset_id=db_document.dataset_id,
                            document_id=document_id,
                            file_path=file_path,
                            max_rows=int(getattr(pipeline_effective, "table_store_max_rows", 0) or 0),
                            max_cols=int(getattr(pipeline_effective, "table_store_max_cols", 0) or 0),
                            sample_rows=int(getattr(pipeline_effective, "table_store_sample_rows", 0) or 0),
                        )
                        _add_stage_duration("table_import", (time.perf_counter() - t0) * 1000)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"table_import_failed: {(str(exc) or exc.__class__.__name__)[:200]}"
                        logger.warning("Table import failed: %s document_id=%s", msg, document_id)
                        meta_patch = _with_stage_durations(dict(db_document.doc_metadata or {}))
                        await self._update_status(
                            db,
                            tenant_id,
                            document_id,
                            "failed",
                            0,
                            "failed",
                            chunk_count=0,
                            total_characters=0,
                            error_message=msg,
                            doc_metadata=meta_patch,
                        )
                        return {
                            "status": "failed",
                            "reason": "table_import_failed",
                            "chunk_count": 0,
                            "total_characters": 0,
                            "parser_backend": "table_store",
                            "chunk_strategy": "none",
                        }

                    await raise_if_cancelled(force=True)

                    # Persist structured table metadata for listing/preview endpoints.
                    try:
                        now_iso = dt.datetime.now(dt.UTC).isoformat()
                        tables_payload: list[dict[str, Any]] = []
                        for a in assets or []:
                            tables_payload.append(
                                {
                                    "table_id": str(getattr(a, "table_id", "")),
                                    "sheet_index": int(getattr(a, "sheet_index", 0) or 0),
                                    "sheet_name": getattr(a, "sheet_name", None),
                                    "row_count": int(getattr(a, "row_count", 0) or 0),
                                    "col_count": int(getattr(a, "col_count", 0) or 0),
                                    "truncated": bool(getattr(a, "truncated", False)),
                                    "columns": list(getattr(a, "columns", None) or []),
                                    "sample_rows": list(getattr(a, "sample_rows", None) or []),
                                }
                            )

                        next_meta = dict(db_document.doc_metadata or {})
                        next_meta["table_store"] = {
                            "version": "1",
                            "source_ext": file_path.suffix.lower(),
                            "imported_at": now_iso,
                            "tables": tables_payload,
                        }
                        next_meta = apply_parse_quality_gate_metadata(next_meta)
                        db_document.doc_metadata = next_meta
                        db.commit()
                        db.refresh(db_document)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to persist table_store metadata (ignored): %s", str(exc)[:200])

                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        "completed",
                        100,
                        "completed",
                        chunk_count=0,
                        total_characters=0,
                        error_message=None,
                        doc_metadata=_with_stage_durations(dict(db_document.doc_metadata or {})),
                    )
                    return {
                        "status": "completed",
                        "reason": "table_store",
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": "table_store",
                        "chunk_strategy": "none",
                    }

            # Structured Table Store (TAG) sidecar for DOCX: import tables into SQLite, but keep
            # the normal parsing+chunking pipeline intact.
            #
            # Motivation:
            # - DOCX often mixes narrative text + tables; short-circuiting would hurt RAG.
            # - Still, having structured tables available improves TAG answers and UI previews.
            if (
                bool(getattr(pipeline_effective, "table_store_enabled", False))
                and db_document.dataset_id is not None
                and file_path.suffix.lower() == ".docx"
            ):
                await raise_if_cancelled(force=True)
                try:
                    from app.services.table_store_service import import_docx_tables

                    assets = import_docx_tables(
                        tenant_id=tenant_id,
                        dataset_id=db_document.dataset_id,
                        document_id=document_id,
                        file_path=file_path,
                        max_rows=int(getattr(pipeline_effective, "table_store_max_rows", 0) or 0),
                        max_cols=int(getattr(pipeline_effective, "table_store_max_cols", 0) or 0),
                        sample_rows=int(getattr(pipeline_effective, "table_store_sample_rows", 0) or 0),
                    )
                    await raise_if_cancelled(force=True)

                    # Persist structured table metadata for listing/preview endpoints.
                    #
                    # If no tables were found, remove stale table_store metadata from previous ingests.
                    try:
                        next_meta = dict(db_document.doc_metadata or {})
                        if assets:
                            now_iso = dt.datetime.now(dt.UTC).isoformat()
                            tables_payload: list[dict[str, Any]] = []
                            for a in assets or []:
                                tables_payload.append(
                                    {
                                        "table_id": str(getattr(a, "table_id", "")),
                                        "sheet_index": int(getattr(a, "sheet_index", 0) or 0),
                                        "sheet_name": getattr(a, "sheet_name", None),
                                        "row_count": int(getattr(a, "row_count", 0) or 0),
                                        "col_count": int(getattr(a, "col_count", 0) or 0),
                                        "truncated": bool(getattr(a, "truncated", False)),
                                        "columns": list(getattr(a, "columns", None) or []),
                                        "sample_rows": list(getattr(a, "sample_rows", None) or []),
                                    }
                                )

                            next_meta["table_store"] = {
                                "version": "1",
                                "source_ext": file_path.suffix.lower(),
                                "imported_at": now_iso,
                                "tables": tables_payload,
                            }
                        else:
                            next_meta.pop("table_store", None)
                        next_meta = apply_parse_quality_gate_metadata(next_meta)

                        if next_meta != (db_document.doc_metadata or {}):
                            db_document.doc_metadata = next_meta
                            db.commit()
                            db.refresh(db_document)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to persist DOCX table_store metadata (ignored): %s", str(exc)[:200])
                except Exception as exc:  # noqa: BLE001
                    # Best-effort only: never fail ingestion for sidecar TAG import.
                    logger.info("DOCX table import failed (ignored): %s document_id=%s", str(exc)[:200], document_id)

            combined_rules = _build_combined_governance_rules(pipeline_effective)
            governance_kwargs = {
                **({"rules": combined_rules} if combined_rules else {}),
                "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
                "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
                "unwrap_lines": pipeline_effective.governance_unwrap_lines,
                "remove_common_lines": pipeline_effective.governance_remove_common_lines,
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
                "pii_max_hits": pipeline_effective.governance_pii_max_hits,
                "secrets_redact": pipeline_effective.governance_secrets_redact,
                "secrets_mode": pipeline_effective.governance_secrets_mode,
                "secrets_mask": pipeline_effective.governance_secrets_mask,
                "secrets_max_hits": pipeline_effective.governance_secrets_max_hits,
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

            parsing_stage = ParsingStage(self)
            inline_asset_stage = InlineAssetStage(self)
            normalize_stage = NormalizeStage()
            governance_stage = GovernanceStage()
            chunking_stage = ChunkingStage()
            chunk_dedup_stage = ChunkDedupStage()
            chunk_asset_stage = ChunkAssetStage(self)
            index_stage = IndexStage()

            parsed_documents_before_governance: list[Document] | None = None
            parsed_documents: list[Document] | None = None
            governance_stats: GovernanceStats | None = None
            governance_audit_patch: dict[str, Any] | None = None
            resumed_from_checkpoint = False
            resumed_from_parse_cache = False
            parsed: ParseResult | None = None
            parse_cache_store: LocalParseCacheStore | None = None
            parse_cache_key: str | None = None

            # Optional checkpoint/resume: if we previously persisted parsed markdown content
            # for this same (file_sha256 + pipeline_hash), skip parsing and resume from it.
            #
            # This reduces wasted work on retries after downstream failures (embedding/vector writes).
            try:
                meta0 = dict(db_document.doc_metadata or {})
                ck = meta0.get("ingest_checkpoint") if isinstance(meta0, dict) else None
                ck_ok = _parsed_checkpoint_is_reusable(meta0)
                if ck_ok:
                    pipeline_hash0 = str(meta0.get("pipeline_hash") or "").strip()
                    file_sha0 = str(meta0.get("file_sha256") or "").strip().lower()
                    ck_pipeline = str(ck.get("pipeline_hash") or "").strip()
                    ck_sha = str(ck.get("file_sha256") or "").strip().lower()

                    if (not pipeline_hash0 or ck_pipeline == pipeline_hash0) and (not file_sha0 or not ck_sha or ck_sha == file_sha0):
                        rec = (
                            db.query(DocumentParsedContent)
                            .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
                            .first()
                        )
                        cleaned_md = str(getattr(rec, "markdown_content", "") or "").strip() if rec is not None else ""
                        original_md = str(getattr(rec, "original_markdown_content", "") or "").strip() if rec is not None else ""
                        if cleaned_md:
                            logger.info(
                                "Resuming ingest from parsed checkpoint: tenant=%s document=%s pipeline_hash=%s",
                                tenant_id,
                                document_id,
                                pipeline_hash0[:16] if pipeline_hash0 else "",
                            )
                            resolved_backend0 = (
                                str(
                                    meta0.get("parser_backend")
                                    or meta0.get("parser_backend_requested")
                                    or parser_backend
                                    or "auto"
                                ).strip()
                                or "auto"
                            )
                            resolved_chunk_strategy0 = chunker_factory.resolve_strategy(chunk_strategy)
                            resume_md = cleaned_md.strip()
                            resume_meta: dict[str, Any] = {"page": 1}
                            if original_md and original_md != resume_md:
                                resume_meta["position_tagged_markdown"] = original_md
                            parsed = ParseResult(
                                resolved_backend=resolved_backend0,
                                resolved_chunk_strategy=resolved_chunk_strategy0,
                                documents=[Document(page_content=resume_md, metadata=resume_meta)],
                            )
                            resumed_from_checkpoint = True
            except Exception as exc:
                _log_processor_fallback('process_document', exc)
                resumed_from_checkpoint = False

            if not resumed_from_checkpoint:
                try:
                    meta0 = dict(db_document.doc_metadata or {})
                    file_sha0 = str(meta0.get("file_sha256") or "").strip().lower()
                    pipeline_hash0 = str(meta0.get("pipeline_hash") or "").strip()
                    parser_backend_key = str(parser_backend or "").strip().lower() or "auto"
                    if (
                        bool(getattr(pipeline_effective, "parse_cache_enabled", False))
                        and file_sha0
                        and pipeline_hash0
                    ):
                        parse_cache_store = LocalParseCacheStore(
                            root=Path(settings.UPLOAD_DIR) / str(tenant_id) / ".mimirq_parse_cache"
                        )
                        parse_cache_key = build_local_parse_cache_key(
                            file_sha256=file_sha0,
                            parser_backend=parser_backend_key,
                            config_hash=pipeline_hash0,
                        )
                        cached_entry, cached_age_ms = parse_cache_store.get(
                            parse_cache_key,
                            ttl_sec=int(getattr(pipeline_effective, "parse_cache_ttl_sec", 0) or 0),
                        )
                        if cached_entry is not None and (cached_entry.documents is not None or cached_entry.chunks is not None):
                            parsed = ParseResult(
                                resolved_backend=str(cached_entry.resolved_backend or parser_backend_key),
                                resolved_chunk_strategy=str(cached_entry.resolved_chunk_strategy or chunker_factory.resolve_strategy(chunk_strategy)),
                                documents=_deserialize_documents_from_parse_cache(cached_entry.documents),
                                chunks=_deserialize_documents_from_parse_cache(cached_entry.chunks),
                            )
                            resumed_from_parse_cache = True
                            meta_hit = dict(db_document.doc_metadata or {})
                            meta_hit["parse_cache"] = {
                                "enabled": True,
                                "hit": True,
                                "age_ms": int(cached_age_ms or 0),
                                "ttl_sec": int(getattr(pipeline_effective, "parse_cache_ttl_sec", 0) or 0),
                            }
                            db_document.doc_metadata = meta_hit
                            db.commit()
                            db.refresh(db_document)
                except Exception as exc:
                    _log_processor_fallback('process_document', exc)
                    resumed_from_parse_cache = False

            if not resumed_from_checkpoint and not resumed_from_parse_cache:
                with metrics_span(
                    "ingest.parse",
                    parser_backend_requested=parser_backend,
                    chunk_strategy_requested=chunk_strategy,
                ):
                    t_parse0 = time.perf_counter()
                    parsed = await parsing_stage.run(
                        db=db,
                        db_document=db_document,
                        file_path=file_path,
                        document_id=document_id,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        parser_backend=parser_backend,
                        chunk_strategy=chunk_strategy,
                        html_xpath=(
                            pipeline_effective.governance_html_xpath
                            if file_path.suffix.lower() in {".html", ".htm"}
                            else None
                        ),
                    )

                await raise_if_cancelled(force=True)

            # Optional: retry parsing with an alternative backend when output quality is obviously low.
            if (
                bool(getattr(pipeline_effective, "parse_fallback_enabled", False))
                and file_path.suffix.lower() == ".pdf"
                and (str(parser_backend or "").strip().lower() in {"", "auto"})
                and (not resumed_from_checkpoint)
                and (not resumed_from_parse_cache)
                and parsed.documents is not None
            ):
                try:
                    min_chars = max(0, int(getattr(pipeline_effective, "parse_fallback_min_content_chars", 0) or 0))
                    min_parse_score = max(
                        0.0,
                        float(getattr(pipeline_effective, "parse_fallback_min_parse_score", 0.0) or 0.0),
                    )
                    max_retries = max(0, int(getattr(pipeline_effective, "parse_fallback_max_retries", 0) or 0))
                    if (min_chars > 0 or min_parse_score > 0.0) and max_retries > 0:
                        joined = "\n\n".join([(d.page_content or "") for d in (parsed.documents or [])])
                        q0 = score_parsed_text_quality(joined)
                        q0_quality = score_document_parse_quality(
                            pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                            parsed_text_quality=q0.to_dict(),
                        )
                        q0_score = float(q0_quality.get("score") or 0.0)
                        q0_chars = int(getattr(q0, "content_chars", 0) or 0)
                        if should_attempt_pdf_fallback(
                            grade="fail" if q0_chars <= 0 else "warn",
                            parse_score=q0_score,
                            content_chars=q0_chars,
                            min_content_chars=min_chars,
                            min_parse_score=min_parse_score,
                        ):
                            from app.parsing.parsers.magic_pdf_parser import (
                                magicpdf_service_configured,
                                resolve_magicpdf_models_dir,
                            )
                            from app.parsing.utils.cli import resolve_cli_command

                            def _magicpdf_available() -> bool:
                                if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
                                    return False
                                if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
                                    return True
                                cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
                                return bool(
                                    resolve_cli_command(cli)
                                    and resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
                                )

                            candidates: list[str] = []
                            current = str(parsed.resolved_backend or "").strip().lower()

                            if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
                                candidates.append("mineru")
                            if bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(
                                (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
                            ):
                                candidates.append("deepseek_ocr")
                            if bool(getattr(settings, "QIANFAN_OCR_ENABLED", False)) and bool(
                                (getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()
                            ):
                                candidates.append("qianfan_ocr")
                            if bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
                                (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
                            ):
                                candidates.append("etl4llm")
                            if settings.DEEPDOC_ENABLED:
                                candidates.append("deepdoc")
                            if getattr(settings, "DOCLING_ENABLED", False):
                                candidates.append("docling")
                            if _magicpdf_available():
                                candidates.append("magicpdf")
                            if settings.MARKITDOWN_ENABLED:
                                candidates.append("markitdown")
                            candidates.append("basic")

                            # Remove current backend and keep order.
                            filtered: list[str] = []
                            for c in candidates:
                                c_norm = (c or "").strip().lower()
                                if not c_norm or c_norm == current:
                                    continue
                                if c_norm not in filtered:
                                    filtered.append(c_norm)

                            attempts: list[dict[str, object]] = []
                            retries_left = max_retries
                            for candidate in filtered:
                                if retries_left <= 0:
                                    break
                                retries_left -= 1
                                try:
                                    with metrics_span("ingest.parse_fallback", backend=candidate):
                                        alt = await parsing_stage.run(
                                            db=db,
                                            db_document=db_document,
                                            file_path=file_path,
                                            document_id=document_id,
                                            tenant_id=tenant_id,
                                            dataset_id=dataset_id,
                                            parser_backend=candidate,
                                            chunk_strategy=chunk_strategy,
                                            html_xpath=None,
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    _log_processor_fallback('process_document', exc)
                                    attempts.append(
                                        {
                                            "from": current,
                                            "to": candidate,
                                            "quality_before": q0.to_dict(),
                                            "error": str(exc)[:200],
                                            "accepted": False,
                                        }
                                    )
                                    continue
                                if alt.documents is None:
                                    continue
                                joined_alt = "\n\n".join([(d.page_content or "") for d in (alt.documents or [])])
                                q1 = score_parsed_text_quality(joined_alt)
                                q1_quality = score_document_parse_quality(
                                    pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                                    parsed_text_quality=q1.to_dict(),
                                )
                                q1_score = float(q1_quality.get("score") or 0.0)
                                q1_chars = int(getattr(q1, "content_chars", 0) or 0)
                                accepted = not should_attempt_pdf_fallback(
                                    grade="warn",
                                    parse_score=q1_score,
                                    content_chars=q1_chars,
                                    min_content_chars=min_chars,
                                    min_parse_score=min_parse_score,
                                )
                                attempts.append(
                                    {
                                        "from": current,
                                        "to": candidate,
                                        "quality_before": q0.to_dict(),
                                        "quality_after": q1.to_dict(),
                                        "accepted": bool(accepted),
                                    }
                                )
                                if accepted:
                                    parsed = alt
                                    break

                            if attempts:
                                meta = dict(db_document.doc_metadata or {})
                                meta["parse_fallback"] = {
                                    "enabled": True,
                                    "attempts": attempts,
                                    "min_content_chars": int(min_chars),
                                    "max_retries": int(max_retries),
                                }
                                db_document.doc_metadata = meta
                                db.commit()
                                db.refresh(db_document)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Parse fallback failed (ignored): %s", str(exc)[:200])

            if resumed_from_checkpoint:
                meta0 = dict(db_document.doc_metadata or {})
                resolved_backend = str(meta0.get("parser_backend") or meta0.get("parser_backend_requested") or parser_backend or "auto").strip() or "auto"
                resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
            else:
                if not resumed_from_parse_cache:
                    _add_stage_duration("parse", (time.perf_counter() - t_parse0) * 1000)

                resolved_backend = parsed.resolved_backend
                resolved_chunk_strategy = parsed.resolved_chunk_strategy

            if parsed is not None:
                parsed = ParseResult(
                    resolved_backend=parsed.resolved_backend,
                    resolved_chunk_strategy=parsed.resolved_chunk_strategy,
                    documents=_attach_logical_source_metadata(
                        parsed.documents,
                        db_document=db_document,
                        file_path=file_path,
                    )
                    if parsed.documents is not None
                    else None,
                    chunks=_attach_logical_source_metadata(
                        parsed.chunks,
                        db_document=db_document,
                        file_path=file_path,
                    )
                    if parsed.chunks is not None
                    else None,
                )

            if (
                not resumed_from_checkpoint
                and not resumed_from_parse_cache
                and parse_cache_store is not None
                and parse_cache_key
                and parsed is not None
            ):
                try:
                    parse_cache_store.set(
                        parse_cache_key,
                        LocalParseCacheEntry(
                            created_at_epoch=time.time(),
                            file_sha256=str((db_document.doc_metadata or {}).get("file_sha256") or "").strip().lower(),
                            parser_backend=str(parser_backend or "").strip().lower() or "auto",
                            resolved_backend=str(parsed.resolved_backend or resolved_backend),
                            resolved_chunk_strategy=str(parsed.resolved_chunk_strategy or resolved_chunk_strategy),
                            documents=_serialize_documents_for_parse_cache(parsed.documents),
                            chunks=_serialize_documents_for_parse_cache(parsed.chunks),
                        ),
                    )
                    meta_cached = dict(db_document.doc_metadata or {})
                    meta_cached["parse_cache"] = {
                        "enabled": True,
                        "hit": False,
                        "ttl_sec": int(getattr(pipeline_effective, "parse_cache_ttl_sec", 0) or 0),
                    }
                    db_document.doc_metadata = meta_cached
                    db.commit()
                    db.refresh(db_document)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Persisted parse cache write failed (ignored): %s", str(exc)[:200])

            # Parse quality gate: if fallback is enabled but we still don't have enough signal,
            # route to failed/quarantined instead of indexing garbage.
            #
            # This is intentionally conservative and currently scoped to PDF+auto, matching the
            # parse_fallback behavior/knobs.
            if (
                bool(getattr(pipeline_effective, "parse_fallback_enabled", False))
                and file_path.suffix.lower() == ".pdf"
                and (str(parser_backend or "").strip().lower() in {"", "auto"})
                and (not resumed_from_checkpoint)
                and (not resumed_from_parse_cache)
                and parsed.documents is not None
            ):
                try:
                    min_chars = max(0, int(getattr(pipeline_effective, "parse_fallback_min_content_chars", 0) or 0))
                    min_parse_score = max(
                        0.0,
                        float(getattr(pipeline_effective, "parse_fallback_min_parse_score", 0.0) or 0.0),
                    )
                    if min_chars > 0 or min_parse_score > 0.0:
                        joined_final = "\n\n".join([(d.page_content or "") for d in (parsed.documents or [])])
                        q_final = score_parsed_text_quality(joined_final)
                        final_chars = int(getattr(q_final, "content_chars", 0) or 0)

                        # If parse_fallback attempted other backends, ensure the stored quality reflects
                        # the final selected parse result (not a rejected candidate attempt).
                        meta = dict(db_document.doc_metadata or {})
                        attempted = bool(meta.get("parse_fallback"))
                        if attempted or final_chars < min_chars:
                            meta["parsed_text_quality"] = q_final.to_dict()
                            specialty_signals = _seal_summary_to_specialty_signals(
                                meta.get("seal_summary") if isinstance(meta.get("seal_summary"), dict) else None
                            )
                            with contextlib.suppress(Exception):
                                meta["parse_quality"] = score_document_parse_quality(
                                    pdf_quality=(meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None),
                                    parsed_text_quality=(meta.get("parsed_text_quality") if isinstance(meta.get("parsed_text_quality"), dict) else None),
                                    specialty_signals=specialty_signals,
                                )
                            meta = apply_parse_quality_gate_metadata(meta)
                            db_document.doc_metadata = meta
                            db.commit()
                            db.refresh(db_document)

                        final_quality = score_document_parse_quality(
                            pdf_quality=(meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None),
                            parsed_text_quality=q_final.to_dict(),
                            specialty_signals=specialty_signals,
                        )
                        final_score = float(final_quality.get("score") or 0.0)
                        if should_attempt_pdf_fallback(
                            grade="warn",
                            parse_score=final_score,
                            content_chars=final_chars,
                            min_content_chars=min_chars,
                            min_parse_score=min_parse_score,
                        ):
                            quarantined = bool(getattr(pipeline_effective, "governance_quarantine_on_drop", False))
                            status = "quarantined" if quarantined else "failed"
                            reason = "quarantined_by_parse_quality" if quarantined else "dropped_by_parse_quality"
                            msg = (
                                f"Document {'quarantined' if quarantined else 'failed'} by parse quality gate "
                                f"(content_chars={final_chars}, parse_score={round(final_score, 3)}). "
                                "Consider enabling OCR/backends or lowering parse fallback thresholds."
                            )
                            logger.warning(LOG_DOC_ID_FMT, msg, document_id)
                            meta_patch = _with_stage_durations(dict(db_document.doc_metadata or {}))

                            from app.core.pipeline_versions import should_preserve_existing_versions

                            update_kwargs: dict[str, Any] = {
                                "error_message": msg,
                                "doc_metadata": meta_patch,
                            }
                            if not should_preserve_existing_versions(meta_patch):
                                update_kwargs["chunk_count"] = 0
                                update_kwargs["total_characters"] = 0

                            await self._update_status(
                                db,
                                tenant_id,
                                document_id,
                                status,
                                0,
                                status,
                                **update_kwargs,
                            )
                            with contextlib.suppress(Exception):
                                from app.services.audit_log_service import audit_log_event

                                audit_log_event(
                                    db,
                                    tenant_id=tenant_id,
                                    actor_id=(getattr(db_document, "owner_id", None) or None),
                                    action=(AUDIT_ACTION_DOCUMENT_QUARANTINE if quarantined else "document.parse_drop"),
                                    resource_type="document",
                                    resource_id=str(document_id),
                                    details={
                                        "reason": reason,
                                        "parse_fallback_min_content_chars": int(min_chars),
                                        "parsed_content_chars": int(final_chars),
                                        "parser_backend": str(resolved_backend or ""),
                                    },
                                )
                                db.commit()

                            return {
                                "status": status,
                                "reason": reason,
                                "chunk_count": 0,
                                "total_characters": 0,
                                "parser_backend": resolved_backend,
                                "chunk_strategy": resolved_chunk_strategy,
                            }
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Parse quality gate failed (ignored): %s", str(exc)[:200])

            # Governance: normalize/clean documents or integrated chunks.
            merge_small_min_chars = 0
            merge_small_before = 0
            merge_small_after = 0
            merge_small_reduced = 0

            _collect_parser_asset_refs(parsed, document_img_ids=document_img_ids, artifact_dirs=artifact_dirs)

            if parsed.documents:
                t0 = time.perf_counter()
                with metrics_span("ingest.inline_assets"):
                    inline_result = inline_asset_stage.run(
                        documents=parsed.documents,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        document_id=document_id,
                        origin_path=file_path,
                        start_index=0,
                        image_caption_enabled=bool(getattr(pipeline_effective, "image_caption_enabled", False)),
                    )
                _add_stage_duration("inline_assets", (time.perf_counter() - t0) * 1000)
                parsed_documents = inline_result.documents
                for iid in inline_result.uploaded_img_ids:
                    if isinstance(iid, str) and iid.strip():
                        document_img_ids.add(iid)
                _apply_inline_asset_audit_patch(db, db_document, inline_result)
            else:
                parsed_documents = None

            if parsed_documents and bool(getattr(pipeline_effective, "cross_page_merge_enabled", False)):
                t0 = time.perf_counter()
                with metrics_span("ingest.cross_page_merge"):
                    parsed_documents = merge_cross_page_documents(
                        parsed_documents,
                        max_page_gap=int(getattr(pipeline_effective, "cross_page_merge_max_page_gap", 1) or 1),
                    )
                _add_stage_duration("cross_page_merge", (time.perf_counter() - t0) * 1000)

            if parsed.chunks is not None and parsed_documents and file_path.suffix.lower() == ".pdf":
                try:
                    joined_for_ro = "\n\n".join([(d.page_content or "") for d in parsed_documents])
                    ro = score_reading_order(joined_for_ro)
                    meta_patch = dict(db_document.doc_metadata or {})
                    meta_patch["reading_order"] = ro
                    db_document.doc_metadata = meta_patch
                    db.commit()
                    db.refresh(db_document)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

            pdf_quality = (db_document.doc_metadata or {}).get("pdf_quality") if isinstance((db_document.doc_metadata or {}).get("pdf_quality"), dict) else None
            if (
                parsed_documents
                and file_path.suffix.lower() == ".pdf"
                and should_apply_vlm_correction(
                    enabled=bool(getattr(pipeline_effective, "vlm_correction_enabled", False)),
                    pdf_quality=pdf_quality,
                    min_table_score=float(getattr(pipeline_effective, "vlm_correction_min_table_score", 0.6) or 0.6),
                )
            ):
                t0 = time.perf_counter()
                with metrics_span("ingest.vlm_correction"):
                    corrected_docs, correction_meta = await apply_vlm_correction_async(
                        documents=parsed_documents,
                        file_path=file_path,
                        max_pages=int(getattr(pipeline_effective, "vlm_correction_max_pages", 2) or 2),
                    )
                _add_stage_duration("vlm_correction", (time.perf_counter() - t0) * 1000)
                parsed_documents = corrected_docs
                if bool(correction_meta.get("applied")):
                    meta_vlm = dict(db_document.doc_metadata or {})
                    meta_vlm["vlm_correction"] = correction_meta
                    db_document.doc_metadata = meta_vlm
                    db.commit()
                    db.refresh(db_document)

            # Parsed table segments (e.g. PDF parsers) -> Table Store sidecar (TAG).
            if parsed_documents and file_path.suffix.lower() == ".pdf":
                table_sidecar_tables_imported = self._import_parsed_markdown_tables_to_store(
                    db,
                    db_document=db_document,
                    tenant_id=tenant_id,
                    documents=parsed_documents,
                    pipeline_effective=pipeline_effective,
                )

            # Best-effort cleanup for parser artifact directories (e.g., MagicPDF output).
            self._cleanup_parser_artifacts(artifact_dirs, tenant_id=tenant_id)

            await raise_if_cancelled()

            if parsed.chunks is not None:
                t0 = time.perf_counter()
                with metrics_span("ingest.normalize"):
                    parsed_chunks = normalize_stage.run(items=parsed.chunks)
                _add_stage_duration("normalize", (time.perf_counter() - t0) * 1000)

                t0 = time.perf_counter()
                with metrics_span("ingest.governance", enabled=bool(pipeline_effective.governance_enabled)):
                    gov = governance_stage.run(
                        items=parsed_chunks,
                        enabled=bool(pipeline_effective.governance_enabled),
                        kwargs=governance_kwargs,
                )
                _add_stage_duration("governance", (time.perf_counter() - t0) * 1000)
                chunks = gov.items
                governance_stats = gov.stats

                governance_plugin_ref = str(getattr(pipeline_effective, "governance_python_plugin", "") or "").strip()
                if governance_plugin_ref:
                    t0 = time.perf_counter()
                    with metrics_span("ingest.governance_python_plugin", enabled=True):
                        chunks = apply_governance_python_plugin(
                            chunks,
                            plugin_ref=governance_plugin_ref,
                            params=dict(getattr(pipeline_effective, "governance_python_params", {}) or {}),
                            context={
                                "document_id": str(document_id),
                                "tenant_id": str(tenant_id),
                                "stage": "post_governance_chunks",
                            },
                        )
                    _add_stage_duration("governance_python_plugin", (time.perf_counter() - t0) * 1000)

                if bool(pipeline_effective.governance_enabled) or governance_plugin_ref:
                    try:
                        governance_audit_patch = self._build_governance_audit_metadata_patch(
                            before_items=parsed_chunks,
                            after_items=chunks,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to record governance audit metadata: %s", str(exc)[:200])
                        governance_audit_patch = None

                if chunks:
                    llm_tagging_meta = await self._apply_llm_auto_tagging(
                        chunks,
                        pipeline_effective=pipeline_effective,
                    )
                    if llm_tagging_meta:
                        audit_patch = dict(governance_audit_patch or {})
                        audit_patch["governance_llm_auto_tagging"] = llm_tagging_meta
                        governance_audit_patch = audit_patch

                if (
                    bool(pipeline_effective.governance_enabled)
                    and governance_stats is not None
                    and not chunks
                    and int(getattr(governance_stats, "dropped", 0) or 0) > 0
                ):
                    self._record_governance_metadata(
                        db,
                        tenant_id,
                        document_id,
                        governance_stats,
                        rule_packs=list(getattr(pipeline_effective, "governance_rule_packs", None) or []),
                        audit_patch=governance_audit_patch,
                    )
                    quarantined = bool(getattr(pipeline_effective, "governance_quarantine_on_drop", False))
                    reasons = getattr(governance_stats, "drop_reasons", {}) or {}
                    reason_str = ", ".join([f"{k}:{v}" for k, v in sorted(reasons.items())]) if isinstance(reasons, dict) else ""
                    hint = "You can disable outline/low-density filters or relax thresholds."
                    if isinstance(reasons, dict) and any(k in reasons for k in ("pii_exceeded", "secrets_exceeded")):
                        hint = "You can adjust PII/Secrets gates (pii_max_hits/secrets_max_hits) or disable them."
                    msg = (
                        ("Document quarantined by governance rules" if quarantined else "Document filtered by governance rules")
                        + (f" ({reason_str})" if reason_str else "")
                        + f". {hint}"
                    )
                    logger.warning(LOG_DOC_ID_FMT, msg, document_id)
                    status = "quarantined" if quarantined else "failed"
                    reason = "quarantined_by_governance" if quarantined else "filtered_by_governance"
                    meta_patch = _with_stage_durations(dict(db_document.doc_metadata or {}))
                    from app.core.pipeline_versions import should_preserve_existing_versions

                    update_kwargs: dict[str, Any] = {
                        "error_message": msg,
                        "doc_metadata": meta_patch,
                    }
                    # When reprocessing a document, keep the currently-active version's stats visible.
                    if not should_preserve_existing_versions(meta_patch):
                        update_kwargs["chunk_count"] = 0
                        update_kwargs["total_characters"] = 0
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        status,
                        0,
                        status,
                        **update_kwargs,
                    )
                    with contextlib.suppress(Exception):
                        from app.services.audit_log_service import audit_log_event

                        pii_hits = getattr(governance_stats, "pii_hits", None) or {}
                        secrets_hits = getattr(governance_stats, "secrets_hits", None) or {}
                        audit_log_event(
                            db,
                            tenant_id=tenant_id,
                            actor_id=(getattr(db_document, "owner_id", None) or None),
                            action=(AUDIT_ACTION_DOCUMENT_QUARANTINE if quarantined else "document.governance_drop"),
                            resource_type="document",
                            resource_id=str(document_id),
                            details={
                                "reason": reason,
                                "drop_reasons": reasons,
                                "pii_hits_total": pii_hits,
                                "secrets_hits_total": secrets_hits,
                                "quarantine_on_drop": quarantined,
                            },
                        )
                        db.commit()
                    return {
                        "status": status,
                        "reason": reason,
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }

                if (
                    bool(pipeline_effective.governance_enabled)
                    or governance_plugin_ref
                    or bool(getattr(pipeline_effective, "governance_llm_auto_tagging_enabled", False))
                ) and chunks:
                    try:
                        self._record_governance_enrichment_metadata(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            items=chunks,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to record governance enrichment: %s", str(exc)[:200])
                    self._strip_doc_enrichment_fields(chunks)
            else:
                t0 = time.perf_counter()
                with metrics_span("ingest.normalize"):
                    parsed_documents = normalize_stage.run(items=parsed_documents or [])
                _add_stage_duration("normalize", (time.perf_counter() - t0) * 1000)
                parsed_documents_before_governance = parsed_documents
                governance_plugin_ref = str(getattr(pipeline_effective, "governance_python_plugin", "") or "").strip()
                if governance_plugin_ref:
                    t0 = time.perf_counter()
                    with metrics_span("ingest.governance_python_plugin", enabled=True):
                        parsed_documents = apply_governance_python_plugin(
                            parsed_documents,
                            plugin_ref=governance_plugin_ref,
                            params=dict(getattr(pipeline_effective, "governance_python_params", {}) or {}),
                            context={
                                "document_id": str(document_id),
                                "tenant_id": str(tenant_id),
                                "stage": "pre_builtin_governance_documents",
                            },
                        )
                    _add_stage_duration("governance_python_plugin", (time.perf_counter() - t0) * 1000)

                t0 = time.perf_counter()
                with metrics_span("ingest.governance", enabled=bool(pipeline_effective.governance_enabled)):
                    gov = governance_stage.run(
                        items=parsed_documents,
                        enabled=bool(pipeline_effective.governance_enabled),
                        kwargs=governance_kwargs,
                    )
                _add_stage_duration("governance", (time.perf_counter() - t0) * 1000)
                parsed_documents = gov.items
                governance_stats = gov.stats

                if bool(pipeline_effective.governance_enabled) or governance_plugin_ref:
                    try:
                        governance_audit_patch = self._build_governance_audit_metadata_patch(
                            before_items=parsed_documents_before_governance,
                            after_items=parsed_documents,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to record governance audit metadata: %s", str(exc)[:200])
                        governance_audit_patch = None

                if parsed_documents:
                    llm_tagging_meta = await self._apply_llm_auto_tagging(
                        parsed_documents,
                        pipeline_effective=pipeline_effective,
                    )
                    if llm_tagging_meta:
                        audit_patch = dict(governance_audit_patch or {})
                        audit_patch["governance_llm_auto_tagging"] = llm_tagging_meta
                        governance_audit_patch = audit_patch

                # Ensure stable per-doc indices so we can rebase chunk offsets into joined-text coordinates.
                _ensure_ingest_page_indices(parsed_documents)

                # Optional: persist parsed markdown (raw+clean) for audit/debug.
                if bool(getattr(pipeline_effective, "persist_parsed_content", False)):
                    try:
                        original_md = _join_original_markdown_for_persistence(parsed_documents_before_governance)
                        cleaned_md = _join_document_page_content(parsed_documents)
                        persist_meta = self._persist_parsed_content(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            original_markdown=original_md,
                            cleaned_markdown=cleaned_md,
                            max_chars=int(getattr(pipeline_effective, "persist_parsed_content_max_chars", 0) or 0),
                        )
                        meta = dict(db_document.doc_metadata or {})
                        meta["parsed_content_persisted"] = persist_meta
                        # Truncated audit content is not a valid restart checkpoint.
                        if bool((persist_meta.get("cleaned") or {}).get("truncated")):
                            meta.pop("ingest_checkpoint", None)
                        else:
                            meta["ingest_checkpoint"] = {
                                "version": "1",
                                "stage": "parsed",
                                "source": "document_parsed_contents",
                                "file_sha256": str(meta.get("file_sha256") or "").strip().lower(),
                                "pipeline_hash": str(meta.get("pipeline_hash") or "").strip(),
                            }
                        db_document.doc_metadata = meta
                        db.commit()
                        db.refresh(db_document)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to persist parsed content: %s", str(exc)[:200])

                if (
                    bool(pipeline_effective.governance_enabled)
                    and governance_stats is not None
                    and not parsed_documents
                    and int(getattr(governance_stats, "dropped", 0) or 0) > 0
                ):
                    self._record_governance_metadata(
                        db,
                        tenant_id,
                        document_id,
                        governance_stats,
                        rule_packs=list(getattr(pipeline_effective, "governance_rule_packs", None) or []),
                        audit_patch=governance_audit_patch,
                    )
                    quarantined = bool(getattr(pipeline_effective, "governance_quarantine_on_drop", False))
                    reasons = getattr(governance_stats, "drop_reasons", {}) or {}
                    reason_str = ", ".join([f"{k}:{v}" for k, v in sorted(reasons.items())]) if isinstance(reasons, dict) else ""
                    hint = "You can disable outline/low-density filters or relax thresholds."
                    if isinstance(reasons, dict) and any(k in reasons for k in ("pii_exceeded", "secrets_exceeded")):
                        hint = "You can adjust PII/Secrets gates (pii_max_hits/secrets_max_hits) or disable them."
                    msg = (
                        ("Document quarantined by governance rules" if quarantined else "Document filtered by governance rules")
                        + (f" ({reason_str})" if reason_str else "")
                        + f". {hint}"
                    )
                    logger.warning(LOG_DOC_ID_FMT, msg, document_id)
                    status = "quarantined" if quarantined else "failed"
                    reason = "quarantined_by_governance" if quarantined else "filtered_by_governance"
                    meta_patch = _with_stage_durations(dict(db_document.doc_metadata or {}))
                    from app.core.pipeline_versions import should_preserve_existing_versions

                    update_kwargs: dict[str, Any] = {
                        "error_message": msg,
                        "doc_metadata": meta_patch,
                    }
                    # When reprocessing a document, keep the currently-active version's stats visible.
                    if not should_preserve_existing_versions(meta_patch):
                        update_kwargs["chunk_count"] = 0
                        update_kwargs["total_characters"] = 0
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        status,
                        0,
                        status,
                        **update_kwargs,
                    )
                    with contextlib.suppress(Exception):
                        from app.services.audit_log_service import audit_log_event

                        pii_hits = getattr(governance_stats, "pii_hits", None) or {}
                        secrets_hits = getattr(governance_stats, "secrets_hits", None) or {}
                        audit_log_event(
                            db,
                            tenant_id=tenant_id,
                            actor_id=(getattr(db_document, "owner_id", None) or None),
                            action=(AUDIT_ACTION_DOCUMENT_QUARANTINE if quarantined else "document.governance_drop"),
                            resource_type="document",
                            resource_id=str(document_id),
                            details={
                                "reason": reason,
                                "drop_reasons": reasons,
                                "pii_hits_total": pii_hits,
                                "secrets_hits_total": secrets_hits,
                                "quarantine_on_drop": quarantined,
                            },
                        )
                        db.commit()
                    return {
                        "status": status,
                        "reason": reason,
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }

                if (
                    bool(pipeline_effective.governance_enabled)
                    or governance_plugin_ref
                    or bool(getattr(pipeline_effective, "governance_llm_auto_tagging_enabled", False))
                ) and parsed_documents:
                    try:
                        self._record_governance_enrichment_metadata(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            items=parsed_documents,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to record governance enrichment: %s", str(exc)[:200])
                    # Avoid propagating large per-doc fields to all chunks.
                    self._strip_doc_enrichment_fields(parsed_documents)

                await raise_if_cancelled()

                await self._update_status(db, tenant_id, document_id, "processing", 33, "chunking")
                t0 = time.perf_counter()
                with metrics_span(
                    "ingest.chunking",
                    chunk_strategy=resolved_chunk_strategy,
                    chunk_size=int(pipeline_effective.chunk_size),
                    chunk_overlap=int(pipeline_effective.chunk_overlap),
                ):
                    chunked = chunking_stage.run(
                        documents=parsed_documents,
                        chunk_strategy=resolved_chunk_strategy,
                        chunk_size=int(pipeline_effective.chunk_size),
                        chunk_overlap=int(pipeline_effective.chunk_overlap),
                        chunk_strategy_params=dict(getattr(pipeline_effective, "chunk_strategy_params", {}) or {}),
                        chunk_python_plugin=str(getattr(pipeline_effective, "chunk_python_plugin", "") or ""),
                        chunk_python_params=dict(getattr(pipeline_effective, "chunk_python_params", {}) or {}),
                    )
                chunks = _rebase_chunk_offsets_by_page_index(
                    documents=parsed_documents,
                    chunks=chunked.chunks,
                    join_separator="\n\n",
                )
                _add_stage_duration("chunking", (time.perf_counter() - t0) * 1000)
                merge_min = max(0, int(getattr(pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
                merge_small_min_chars = int(merge_min)
                merge_small_before = len(chunks)
                merge_small_after = merge_small_before
                merge_small_reduced = 0
                if merge_min > 0 and chunks:
                    t0 = time.perf_counter()
                    with metrics_span("ingest.chunk_merge_small", min_chars=merge_min):
                        merged = _merge_small_chunks_by_min_chars(
                            documents=parsed_documents,
                            chunks=chunks,
                            min_chars=merge_min,
                            join_separator="\n\n",
                        )
                    _add_stage_duration("chunk_merge_small", (time.perf_counter() - t0) * 1000)
                    merge_small_after = len(merged)
                    merge_small_reduced = max(0, merge_small_before - merge_small_after)
                    chunks = merged

            await raise_if_cancelled()

            # Drop extremely short chunks to reduce retrieval noise (keep image-bearing chunks).
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
                    doc_type = str(meta.get("doc_type_kwd") or "").lower()
                    # Keep image/table chunks even if caption is short: they carry important assets.
                    if (
                        doc_type in {"image", "table"}
                        or meta.get("image") is not None
                        or meta.get("img_id")
                        or meta.get("image_id")
                        or meta.get("image_url")
                    ):
                        filtered.append(c)
                kept_short_fallback = False
                if not filtered and original_chunks:
                    # Avoid indexing an empty document: keep the longest chunk even if it's short.
                    longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
                    filtered = [longest]
                    kept_short_fallback = True
                chunks = filtered
                dropped = before - len(chunks)
                if kept_short_fallback:
                    kept_len = len((chunks[0].page_content or "").strip()) if chunks else 0
                    logger.info(
                        "All chunks shorter than %s chars; kept 1 (%s chars) and dropped %s for document %s",
                        min_chars,
                        kept_len,
                        dropped,
                        document_id,
                    )
                elif dropped:
                    logger.info("Dropped %s short chunks (<%s chars) for document %s", dropped, min_chars, document_id)

            # Optional exact-duplicate text chunk drop (within document).
            dedup_enabled = bool(getattr(settings, "CHUNK_DEDUP_ENABLED", False))
            dedup_dropped = 0
            if dedup_enabled and chunks:
                t0 = time.perf_counter()
                with metrics_span("ingest.chunk_dedup", enabled=True):
                    deduped = chunk_dedup_stage.run(chunks=chunks, enabled=True)
                _add_stage_duration("chunk_dedup", (time.perf_counter() - t0) * 1000)
                chunks = deduped.chunks
                dedup_dropped = int(deduped.duplicates_dropped)
                if int(deduped.duplicates_dropped) > 0:
                    logger.info(
                        "Dropped %s duplicate chunks for document %s",
                        int(deduped.duplicates_dropped),
                        document_id,
                    )
                    log_metrics(
                        {
                            "event": "ingest.chunk_dedup",
                            "duplicates_dropped": int(deduped.duplicates_dropped),
                        }
                    )

            # Optional cross-document near-duplicate drop (SimHash bucket index; best-effort).
            near_dedup_dropped = 0
            if bool(getattr(pipeline_effective, "near_dedup_enabled", False)) and chunks:
                t0 = time.perf_counter()
                try:
                    threshold = max(0, int(getattr(pipeline_effective, "near_dedup_hamming_threshold", 0) or 0))
                    max_bucket_size = max(0, int(getattr(pipeline_effective, "near_dedup_max_bucket_size", 0) or 0))
                    # Safety: keep the index per-tenant per-dataset to avoid unintended cross-pollution.
                    safe_dataset = re.sub(r"[^A-Za-z0-9._-]+", "_", str(dataset_id or tenant_id))
                    index_path = Path(settings.UPLOAD_DIR) / str(tenant_id) / ".mimirq_dedup" / f"{safe_dataset}.json"

                    kept_chunks: list[Document] = []
                    kept_hashes: list[str] = []
                    sample_match: dict[str, Any] | None = None

                    def update_fn(buckets: dict[str, list[str]]):
                        nonlocal near_dedup_dropped, sample_match
                        for c in chunks:
                            meta = c.metadata if isinstance(getattr(c, "metadata", None), dict) else {}
                            if _should_skip_near_dedup_for_chunk(c):
                                kept_chunks.append(c)
                                continue

                            content_norm = normalize_text(c.page_content or "", normalize_line_endings=True, remove_control_chars=True)
                            sh_hex = str(meta.get("simhash64") or "").strip().lower()
                            if not sh_hex:
                                sh_hex = simhash64_hex(simhash64(content_norm))
                                meta = dict(meta)
                                meta["simhash64"] = sh_hex
                                meta.setdefault("simhash_algo", "simhash64_sha1")
                                c.metadata = meta

                            match = find_near_duplicate(
                                buckets=buckets,
                                simhash64_hex=sh_hex,
                                hamming_threshold=threshold,
                                max_bucket_size=max_bucket_size,
                            )
                            if match is not None:
                                near_dedup_dropped += 1
                                if sample_match is None:
                                    sample_match = {
                                        "simhash64": sh_hex,
                                        "matched_simhash64": match.simhash64,
                                        "distance": int(match.distance),
                                    }
                                continue

                            kept_chunks.append(c)
                            kept_hashes.append(sh_hex)

                        if kept_hashes:
                            add_simhashes(buckets=buckets, simhashes=kept_hashes, max_bucket_size=max_bucket_size)
                        return buckets

                    with metrics_span("ingest.near_dedup", enabled=True, threshold=threshold):
                        with_near_dedup_index(path=index_path, fn=update_fn)

                    if near_dedup_dropped > 0:
                        original_chunks_for_fallback = list(chunks)
                        chunks = kept_chunks
                        if not chunks:
                            # Avoid indexing an empty document: keep the longest chunk.
                            longest = max(
                                original_chunks_for_fallback,
                                key=lambda d: len((d.page_content or "").strip()),
                                default=None,
                            )
                            if longest is not None:
                                chunks = [longest]
                        logger.info(
                            "Dropped %s near-duplicate chunks for document %s (threshold=%s)",
                            int(near_dedup_dropped),
                            document_id,
                            int(threshold),
                        )
                        log_metrics(
                            {
                                "event": "ingest.near_dedup",
                                "dropped": int(near_dedup_dropped),
                                "threshold": int(threshold),
                            }
                        )
                        meta = dict(db_document.doc_metadata or {})
                        meta["near_dedup"] = {
                            "enabled": True,
                            "dropped": int(near_dedup_dropped),
                            "threshold": int(threshold),
                            "max_bucket_size": int(max_bucket_size),
                            "sample_match": sample_match,
                        }
                        db_document.doc_metadata = meta
                        db.commit()
                        db.refresh(db_document)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Near-dup stage failed (ignored): %s", str(exc)[:200])
                _add_stage_duration("near_dedup", (time.perf_counter() - t0) * 1000)

            # Optional: TAG/RAG separation for parser-emitted table segments.
            # When sidecar exclusive routing is enabled and sidecar import succeeded,
            # keep table content in TAG only (exclude from RAG vectors/BM25).
            table_sidecar_exclusive_enabled = bool(
                getattr(pipeline_effective, "table_store_sidecar_exclusive_routing", False)
            )
            if chunks and table_sidecar_tables_imported >= 0:
                chunks, table_sidecar_routing_audit = self._apply_table_sidecar_exclusive_routing(
                    chunks=chunks,
                    enabled=table_sidecar_exclusive_enabled,
                    sidecar_tables_imported=table_sidecar_tables_imported,
                )

            # Guardrail: cap chunk count per document (0 disables).
            max_chunks_per_document = max(0, int(getattr(settings, "MAX_CHUNKS_PER_DOCUMENT", 0) or 0))
            truncation_strategy = str(getattr(settings, "MAX_CHUNKS_PER_DOCUMENT_STRATEGY", "head") or "head")
            truncated_from = 0
            truncated_to = 0
            truncated_dropped = 0
            truncated_asset_total = 0
            truncated_asset_kept = 0
            truncated_strategy_used = ""
            if max_chunks_per_document > 0 and chunks and len(chunks) > max_chunks_per_document:
                truncated_from = len(chunks)
                chunks, truncation_info = _truncate_chunks_for_limit(
                    chunks,
                    max_chunks=max_chunks_per_document,
                    strategy=truncation_strategy,
                )
                truncated_to = len(chunks)
                truncated_dropped = max(0, truncated_from - truncated_to)
                truncated_asset_total = int(truncation_info.get("asset_total") or 0)
                truncated_asset_kept = int(truncation_info.get("asset_kept") or 0)
                truncated_strategy_used = str(truncation_info.get("strategy") or "").strip() or str(truncation_strategy)
                logger.info(
                    "Truncated chunks for document %s: kept=%s dropped=%s assets=%s/%s strategy=%s (MAX_CHUNKS_PER_DOCUMENT=%s)",
                    document_id,
                    truncated_to,
                    truncated_dropped,
                    truncated_asset_kept,
                    truncated_asset_total,
                    truncated_strategy_used,
                    max_chunks_per_document,
                )
                log_metrics(
                    {
                        "event": "ingest.chunk_truncate",
                        "chunk_before": int(truncated_from),
                        "chunk_after": int(truncated_to),
                        "dropped": int(truncated_dropped),
                        "max_chunks_per_document": int(max_chunks_per_document),
                        "strategy": truncated_strategy_used,
                        "asset_kept": int(truncated_asset_kept),
                        "asset_total": int(truncated_asset_total),
                    }
                )

            if merge_small_min_chars > 0 or dedup_enabled or max_chunks_per_document > 0:
                self._record_chunk_postprocess_metadata(
                    db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    stats=ChunkPostprocessStats(
                        merge_small_enabled=bool(merge_small_min_chars > 0),
                        merge_small_min_chars=int(merge_small_min_chars),
                        merge_small_before=int(merge_small_before),
                        merge_small_after=int(merge_small_after),
                        merge_small_reduced=int(merge_small_reduced),
                        dedup_enabled=dedup_enabled,
                        dedup_dropped=dedup_dropped,
                        max_chunks_per_document=max_chunks_per_document,
                        max_chunks_strategy=truncated_strategy_used or truncation_strategy,
                        truncated_from=truncated_from,
                        truncated_to=truncated_to,
                        truncated_dropped=truncated_dropped,
                        truncated_asset_total=truncated_asset_total,
                        truncated_asset_kept=truncated_asset_kept,
                    ),
                )

            if governance_stats is not None:
                self._record_governance_metadata(
                    db,
                    tenant_id,
                    document_id,
                    governance_stats,
                    rule_packs=list(getattr(pipeline_effective, "governance_rule_packs", None) or []),
                    audit_patch=governance_audit_patch,
                )

            await raise_if_cancelled()

            if not chunks:
                sidecar_excluded = int((table_sidecar_routing_audit or {}).get("table_chunks_excluded_from_rag") or 0)
                sidecar_imported = int((table_sidecar_routing_audit or {}).get("sidecar_tables_imported") or 0)
                if sidecar_excluded > 0 and sidecar_imported > 0:
                    meta_patch = dict(db_document.doc_metadata or {})
                    meta_patch["table_sidecar_routing"] = dict(table_sidecar_routing_audit or {})
                    meta_patch = _with_stage_durations(meta_patch)
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        "completed",
                        100,
                        "completed",
                        chunk_count=0,
                        total_characters=0,
                        error_message=None,
                        doc_metadata=meta_patch,
                    )
                    return {
                        "status": "completed",
                        "reason": "table_sidecar_exclusive",
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }
                msg = (
                    "No chunks produced for document (empty or filtered by CHUNK_MIN_CHARS). "
                    "Consider lowering CHUNK_MIN_CHARS or checking the parser output."
                )
                logger.warning(LOG_DOC_ID_FMT, msg, document_id)
                meta_patch = _with_stage_durations(dict(db_document.doc_metadata or {}))
                if table_sidecar_routing_audit:
                    meta_patch["table_sidecar_routing"] = dict(table_sidecar_routing_audit)
                await self._update_status(
                    db,
                    tenant_id,
                    document_id,
                    "failed",
                    0,
                    "failed",
                    chunk_count=0,
                    total_characters=0,
                    error_message=msg,
                    doc_metadata=meta_patch,
                )
                return {
                    "status": "failed",
                    "reason": "no_chunks",
                    "chunk_count": 0,
                    "total_characters": 0,
                    "parser_backend": resolved_backend,
                    "chunk_strategy": resolved_chunk_strategy,
                }

            # Best-effort: persist basic chunking stats for audit/debug (does not affect indexing).
            try:
                self._record_chunking_stats_metadata(
                    db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunks=chunks,
                    total_characters=_joined_text_total_characters(parsed_documents, join_separator="\n\n"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to record chunking stats: %s", str(exc)[:200])

            # Chunk-level assets & metadata (image upload/binding).
            await raise_if_cancelled()
            t0 = time.perf_counter()
            with metrics_span("ingest.chunk_assets"):
                chunk_asset = chunk_asset_stage.run(
                    chunks=chunks,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    options=ChunkAssetOptions(
                        dataset_id=dataset_id,
                        resolved_backend=resolved_backend,
                        resolved_chunk_strategy=resolved_chunk_strategy,
                        image_caption_enabled=bool(getattr(pipeline_effective, "image_caption_enabled", False)),
                        image_ocr_enabled=bool(getattr(pipeline_effective, "image_ocr_enabled", False)),
                        image_ocr_max_chars=int(getattr(pipeline_effective, "image_ocr_max_chars", 0) or 0),
                        image_ocr_max_images=int(getattr(pipeline_effective, "image_ocr_max_images", 0) or 0),
                        pii_anonymize=bool(getattr(pipeline_effective, "governance_pii_anonymize", False)),
                        pii_mode=str(getattr(pipeline_effective, "governance_pii_mode", "mask") or "mask"),
                        pii_mask=str(getattr(pipeline_effective, "governance_pii_mask", REDACTED_MASK) or REDACTED_MASK),
                        secrets_redact=bool(getattr(pipeline_effective, "governance_secrets_redact", False)),
                        secrets_mode=str(getattr(pipeline_effective, "governance_secrets_mode", "mask") or "mask"),
                        secrets_mask=str(getattr(pipeline_effective, "governance_secrets_mask", SECRET_MASK) or SECRET_MASK),
                    ),
                )
            _add_stage_duration("chunk_assets", (time.perf_counter() - t0) * 1000)
            chunks = chunk_asset.chunks
            # Ensure stable traceability metadata exists on each chunk (used by citations/filtering).
            pipeline_hash = str((db_document.doc_metadata or {}).get("pipeline_hash") or "").strip()
            file_type = str(getattr(db_document, "file_type", "") or "").strip().lower() or str(file_path.suffix.lstrip(".")).lower()
            governance_version = (
                str(getattr(governance_stats, "version", "") or "").strip()
                if governance_stats is not None
                else ""
            )
            for c in chunks:
                meta = dict(c.metadata or {})
                if pipeline_hash:
                    meta.setdefault("pipeline_hash", pipeline_hash)
                    meta.setdefault("doc_pipeline_key", f"{document_id}:{pipeline_hash}")
                if file_type:
                    meta.setdefault("file_type", file_type)
                if governance_version:
                    meta.setdefault("governance_version", governance_version)
                c.metadata = meta
            for iid in chunk_asset.img_ids:
                if isinstance(iid, str) and iid.strip():
                    document_img_ids.add(iid)

            # If using auto chunking, persist the per-document selection stats for debugging/tuning.
            if resolved_chunk_strategy == "auto" and chunks:
                selected_counts: dict[str, int] = {}
                for c in chunks:
                    meta = c.metadata or {}
                    selected = meta.get("chunk_strategy_selected")
                    if isinstance(selected, str) and selected.strip():
                        selected_counts[selected] = selected_counts.get(selected, 0) + 1
                if selected_counts:
                    self._record_auto_chunking_metadata(
                        db,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        selected_counts=selected_counts,
                    )

            # Persist all image img_id values to document.metadata (for cleanup).
            self._record_document_image_ids(db, tenant_id=tenant_id, document_id=document_id, img_ids=document_img_ids)

            await raise_if_cancelled()

            await self._update_status(db, tenant_id, document_id, "processing", 66, "embedding")

            await raise_if_cancelled()

            # Indexing performs embedding + vector persistence; surface this as a distinct stage so
            # UI/progress polling isn't stuck on "embedding" for the entire index write.
            await self._update_status(db, tenant_id, document_id, "processing", 80, "vector_write")

            t0 = time.perf_counter()
            with metrics_span(
                "ingest.index",
                chunk_count=len(chunks),
                chunk_vector_enabled=bool(getattr(index_options, "chunk_vector_enabled", True)),
                bm25_index_enabled=bool(getattr(index_options, "bm25_index_enabled", True)),
            ):
                indexed = index_stage.run(
                    db=db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    file_path=file_path,
                    default_source=str(getattr(db_document, "filename", "") or "").strip() or str(file_path.name),
                    chunks=chunks,
                    options=index_options,
                )
            _add_stage_duration("index", (time.perf_counter() - t0) * 1000)
            chunk_ids = indexed.chunk_ids
            total_chars = indexed.total_characters
            log_metrics(
                {
                    "event": "ingest.index.result",
                    "chunk_count": len(chunks),
                    "total_characters": total_chars,
                }
            )

            await raise_if_cancelled(force=True)

            # Versioning: only switch the *active* pipeline after a successful completion,
            # so ongoing reprocessing doesn't immediately "downgrade" retrieval quality.
            meta_patch = dict(db_document.doc_metadata or {})
            completed_pipeline_hash = str(meta_patch.get("pipeline_hash") or "").strip()
            if completed_pipeline_hash:
                meta_patch["active_pipeline_hash"] = completed_pipeline_hash
                meta_patch["active_pipeline_ready"] = True
                # Best-effort: record per-version pipeline provenance for reproducibility/debug.
                try:
                    from app.services.pipeline_provenance_service import (
                        build_pipeline_version_snapshot,
                        upsert_pipeline_provenance_version,
                    )

                    snap = build_pipeline_version_snapshot(meta=meta_patch, pipeline_hash=completed_pipeline_hash)
                    meta_patch = upsert_pipeline_provenance_version(
                        meta_patch,
                        pipeline_hash=completed_pipeline_hash,
                        snapshot=snap,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.info("Failed to record pipeline provenance (ignored): %s", str(exc)[:200])

            if table_sidecar_routing_audit:
                meta_patch["table_sidecar_routing"] = dict(table_sidecar_routing_audit)

            meta_patch = _with_stage_durations(meta_patch)
            await self._update_status(
                db,
                tenant_id,
                document_id,
                "completed",
                100,
                "completed",
                chunk_count=len(chunks),
                total_characters=total_chars,
                doc_metadata=meta_patch,
            )

            logger.info(
                "Document processed: %s chunks (parser=%s, chunker=%s)",
                len(chunks),
                resolved_backend,
                resolved_chunk_strategy,
            )
            log_metrics(
                {
                    "event": "ingest.completed",
                    "chunk_count": len(chunks),
                    "total_characters": total_chars,
                    "parser_backend": resolved_backend,
                    "chunk_strategy": resolved_chunk_strategy,
                    "img_count": len(document_img_ids),
                }
            )

            # Step 7: run KG extraction (events/entities) when enabled.
            if pipeline_effective.kg_enabled:
                # When queue is enabled, move KG extraction to the worker for better ingest throughput.
                if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
                    try:
                        from app.core.pipeline_versions import get_active_pipeline_hash  # noqa: WPS433
                        from app.tasks.queue import enqueue_kg_extraction

                        pipeline_hash = (
                            get_active_pipeline_hash(db_document.doc_metadata or {})
                            or (db_document.doc_metadata or {}).get("pipeline_hash")
                            or "unknown"
                        )
                        pipeline_hash = str(pipeline_hash).strip() or "unknown"
                        job_id = f"kg:{tenant_id}:{document_id}:{pipeline_hash}"
                        kg_task_id = await enqueue_kg_extraction(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            requested_by="system",
                            job_id=job_id,
                            pipeline_hash=pipeline_hash,
                        )
                        if kg_task_id:
                            meta = dict(db_document.doc_metadata or {})
                            meta["kg_task_id"] = kg_task_id
                            db_document.doc_metadata = meta
                            db.commit()
                            db.refresh(db_document)
                        logger.info("KG extraction enqueued for document %s (task_id=%s)", document_id, kg_task_id)
                        log_metrics(
                            {
                                "event": "ingest.kg.enqueued",
                                "kg_task_id": kg_task_id,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        # Queue errors should not affect the main document flow.
                        logger.warning("Failed to enqueue KG extraction: %s", str(exc)[:200])
                else:
                    logger.info("Running KG extraction on document chunks...")
                    prompt_template_id = None
                    raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
                    if raw_tid:
                        try:
                            prompt_template_id = UUID(raw_tid)
                        except Exception:
                            logger.warning("Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID: %s", raw_tid[:50])
                    try:
                        kg_python_plugin_ref = str(getattr(pipeline_effective, "kg_python_plugin", "") or "").strip()
                        if not kg_python_plugin_ref:
                            kg_python_plugin_ref = derive_registered_stage_plugin_ref(
                                str(getattr(pipeline_effective, "chunk_python_plugin", "") or "").strip(),
                                "kg",
                            )
                        kg_python_params = dict(getattr(pipeline_effective, "kg_python_params", {}) or {})
                        events = await extract_events(
                            chunk_ids,
                            tenant_id=tenant_id,
                            chunks=indexed.db_chunks,
                            index_options=index_options,
                            prompt_template_id=prompt_template_id,
                            prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                            prompt_ab_experiment_key=(getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None,
                            kg_python_plugin=kg_python_plugin_ref,
                            kg_python_params=kg_python_params,
                        )
                        logger.info("KG extracted %s events for document %s", len(events), document_id)
                        log_metrics(
                            {
                                "event": "ingest.kg.completed",
                                "event_count": len(events),
                                "kg_python_plugin": kg_python_plugin_ref,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("KG extraction failed for document %s: %s", document_id, str(exc)[:200])

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "total_characters": total_chars,
                "parser_backend": resolved_backend,
                "chunk_strategy": resolved_chunk_strategy
            }

        except DocumentCancelledError as e:
            logger.info("Document processing cancelled: tenant=%s document=%s (%s)", tenant_id, document_id, str(e)[:120])
            # Roll back any uncommitted DB work (e.g., flushed chunks) to avoid committing partial results.
            self._rollback_and_cleanup_indexes(db, db_document=db_document, tenant_id=tenant_id, document_id=document_id)
            await self._update_status(
                db,
                tenant_id,
                document_id,
                "cancelled",
                0,
                "cancelled",
                error_message="cancelled",
                doc_metadata=_with_stage_durations(dict(getattr(db_document, "doc_metadata", None) or {})),
            )
            return {"status": "cancelled"}
        except asyncio.CancelledError:
            # arq Job.abort cancels the coroutine; ensure we stop the child parser process and persist status.
            self._rollback_and_cleanup_indexes(db, db_document=db_document, tenant_id=tenant_id, document_id=document_id)
            try:
                await asyncio.shield(
                    self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        "cancelled",
                        0,
                        "cancelled",
                        error_message="cancelled",
                        doc_metadata=_with_stage_durations(dict(getattr(db_document, "doc_metadata", None) or {})),
                    )
                )
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            raise
        except TenantQuotaExceededError as e:
            # NOTE: Keep this block after asyncio.CancelledError so task cancellations propagate.
            quota_key = str(getattr(e, "quota", "") or "").strip() or "quota"
            logger.info(
                "Tenant quota exceeded: tenant=%s document=%s quota=%s",
                tenant_id,
                document_id,
                quota_key,
            )
            log_metrics(
                {
                    "event": "ingest.quota_exceeded",
                    "quota": quota_key,
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                }
            )
            try:
                db.rollback()
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

            meta_patch = dict(getattr(db_document, "doc_metadata", None) or {})
            meta_patch["tenant_quota_exceeded"] = {
                "quota": quota_key,
                "meta": dict(getattr(e, "meta", None) or {}),
            }
            meta_patch = _with_stage_durations(meta_patch)

            from app.core.pipeline_versions import should_preserve_existing_versions  # noqa: WPS433

            update_kwargs: dict[str, Any] = {
                "error_message": str(e)[:300],
                "doc_metadata": meta_patch,
            }
            # When reprocessing a document, keep the currently-active version's stats visible.
            if not should_preserve_existing_versions(meta_patch):
                update_kwargs["chunk_count"] = 0
                update_kwargs["total_characters"] = 0
            await self._update_status(
                db,
                tenant_id,
                document_id,
                "failed",
                0,
                "failed",
                **update_kwargs,
            )
            return {
                "status": "failed",
                "reason": f"tenant_quota_exceeded:{quota_key}",
                "chunk_count": 0,
                "total_characters": 0,
                "parser_backend": resolved_backend,
                "chunk_strategy": resolved_chunk_strategy,
            }
        except Exception as e:
            # Error handling.
            logger.exception("Error processing document %s: %s", document_id, e)
            log_metrics({"event": "ingest.failed", "success": False, "error": str(e)[:200]})
            self._rollback_and_cleanup_indexes(db, db_document=db_document, tenant_id=tenant_id, document_id=document_id)
            await self._update_status(
                db,
                tenant_id,
                document_id,
                "failed",
                0,
                "failed",
                error_message=str(e),
                doc_metadata=_with_stage_durations(dict(getattr(db_document, "doc_metadata", None) or {})),
            )
            raise
        finally:
            if preprocessed_temp_path is not None:
                try:
                    preprocessed_temp_path.unlink(missing_ok=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            if owns_db:
                db.close()

    @staticmethod
    def _status_update_cancel_blocked(db_doc: DBDocument, status: str) -> bool:
        status_norm = str(status).lower()
        current_status = str(db_doc.status or "").lower()
        if current_status == "cancelled" and status_norm != "cancelled":
            return True
        meta = db_doc.doc_metadata or {}
        return isinstance(meta, dict) and bool(meta.get("cancel_requested")) and status_norm != "cancelled"

    @staticmethod
    def _clear_failure_retry_fields(db_doc: DBDocument) -> None:
        for attr in ("failed_stage", "error_code", "next_retry_at"):
            if hasattr(db_doc, attr):
                setattr(db_doc, attr, None)

    @staticmethod
    def _apply_status_update_fields(
        db_doc: DBDocument,
        *,
        status: str,
        progress: int,
        stage: str,
        extra_fields: dict[str, Any],
    ) -> None:
        db_doc.status = status
        db_doc.processing_progress = progress
        db_doc.current_stage = stage
        for key, value in extra_fields.items():
            setattr(db_doc, key, value)

    @staticmethod
    def _record_ingest_dead_letter_for_status(
        db: Session,
        *,
        db_doc: DBDocument,
        status_norm: str,
        stage: str,
        prev_stage: str,
        failed_stage_hint: Any,
        error_code_hint: Any,
    ) -> None:
        if status_norm not in {"failed", "quarantined"}:
            return
        try:
            from app.services.ingest_dead_letter_service import record_ingest_dead_letter

            record_ingest_dead_letter(
                db,
                document=db_doc,
                failed_stage=str(failed_stage_hint or prev_stage or stage or "").strip() or None,
                error_code=(str(error_code_hint).strip() if error_code_hint else None),
                error_message=getattr(db_doc, "error_message", None),
                original_payload={
                    "status": status_norm,
                    "stage": str(stage or ""),
                    "previous_stage": prev_stage,
                },
            )
        except Exception as exc:
            logger.debug("Ignoring non-critical ingest DLQ write failure: %s", exc)

    @staticmethod
    def _adjust_processing_stage_metric(
        *,
        current_status: str,
        prev_stage: str,
        status: str,
        stage: str,
    ) -> None:
        try:
            from app.services.ingestion_prometheus_metrics import adjust_processing_stage_gauge

            adjust_processing_stage_gauge(
                prev_status=current_status,
                prev_stage=prev_stage,
                new_status=str(status or ""),
                new_stage=str(stage or ""),
            )
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @staticmethod
    def _notify_ingestion_run_status(
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        status: str,
        db_doc: DBDocument,
    ) -> None:
        try:
            from app.services.ingestion_run_service import IngestionRunService

            doc_meta = getattr(db_doc, "doc_metadata", None)
            IngestionRunService.on_document_status_update(
                db,
                tenant_id=tenant_id,
                document_id=document_id,
                new_status=str(status or ""),
                error_message=getattr(db_doc, "error_message", None),
                doc_meta=(dict(doc_meta or {}) if isinstance(doc_meta, dict) else None),
            )
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    async def _update_status(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        status: str,
        progress: int,
        stage: str,
        **kwargs
    ):
        """Update document processing status."""
        await asyncio.sleep(0)
        db_doc = (
            db.query(DBDocument)
            .populate_existing()
            .filter(
                DBDocument.id == document_id,
                DBDocument.tenant_id == tenant_id,
            )
            .first()
        )

        if db_doc:
            # Do not overwrite a user-requested cancellation from a long-running worker.
            current_status = str(db_doc.status or "").lower()
            if self._status_update_cancel_blocked(db_doc, status):
                return

            prev_stage = str(getattr(db_doc, "current_stage", None) or "")
            status_norm = str(status or "").strip().lower()
            failed_stage_hint = kwargs.pop("failed_stage", None)
            error_code_hint = kwargs.pop("error_code", None)
            self._apply_status_update_fields(
                db_doc,
                status=status,
                progress=progress,
                stage=stage,
                extra_fields=kwargs,
            )

            if status_norm in {"pending", "completed", "cancelled"}:
                self._clear_failure_retry_fields(db_doc)

            db.commit()
            db.refresh(db_doc)
            self._record_ingest_dead_letter_for_status(
                db,
                db_doc=db_doc,
                status_norm=status_norm,
                stage=stage,
                prev_stage=prev_stage,
                failed_stage_hint=failed_stage_hint,
                error_code_hint=error_code_hint,
            )
            self._adjust_processing_stage_metric(
                current_status=current_status,
                prev_stage=prev_stage,
                status=status,
                stage=stage,
            )
            self._notify_ingestion_run_status(
                db,
                tenant_id=tenant_id,
                document_id=document_id,
                status=status,
                db_doc=db_doc,
            )

    async def _rebuild_bm25_index_for_tenant(self, db: Session, tenant_id: UUID):
        """Rebuild BM25 index for a specific tenant."""
        try:
            if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
                try:
                    from app.tasks.queue import enqueue_rebuild_indexes

                    job_id = f"rebuild:{tenant_id}"
                    await enqueue_rebuild_indexes(tenant_id=tenant_id, requested_by="system", job_id=job_id)
                    logger.info("Rebuild indexes enqueued for tenant %s", tenant_id)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to enqueue rebuild indexes (fallback to inline): %s", str(exc)[:200])

            any_chunk = (
                db.query(DocumentChunk.id)
                .join(DBDocument)
                .filter(DBDocument.status == "completed", DocumentChunk.tenant_id == tenant_id)
                .limit(1)
                .first()
            )
            if not any_chunk:
                logger.warning("No chunks found for BM25 index")
                return

            logger.info("Rebuilding BM25 index for tenant %s", tenant_id)
            Indexer(db).rebuild_tenant(tenant_id=tenant_id, kinds=[IndexKind.CHUNK])

        except Exception as e:
            logger.warning("Failed to rebuild BM25 index: %s", e)

    async def _rebuild_bm25_index(self, db: Session):
        """Rebuild BM25 indexes for all tenants."""
        try:
            if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
                try:
                    from app.tasks.queue import enqueue_rebuild_indexes

                    tenant_rows = db.query(DocumentChunk.tenant_id).distinct().all()
                    tenant_ids = [row[0] for row in tenant_rows if row and row[0]]
                    for tid in tenant_ids:
                        job_id = f"rebuild:{tid}"
                        await enqueue_rebuild_indexes(tenant_id=tid, requested_by="system", job_id=job_id)
                    logger.info("Rebuild indexes enqueued for %s tenants", len(tenant_ids))
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to enqueue rebuild indexes (fallback to inline): %s", str(exc)[:200])

            tenant_ids: list[UUID] = []
            q = (
                db.query(DocumentChunk.tenant_id)
                .distinct()
                .execution_options(stream_results=True)
                .enable_eagerloads(False)
            )
            for row in q.yield_per(2000):
                if row and row[0]:
                    tenant_ids.append(row[0])
            if not tenant_ids:
                logger.warning("No chunks found for BM25 index")
                return
            for tid in tenant_ids:
                Indexer(db).rebuild_tenant(tenant_id=tid, kinds=[IndexKind.CHUNK])
        except Exception as e:
            logger.warning("Failed to rebuild BM25 index: %s", e)

    def _record_processing_metadata(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        parser_backend: str,
        chunk_strategy: str
    ):
        """Ensure document metadata records the final parser selection."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["parser_backend"] = parser_backend
        metadata["chunk_strategy"] = chunk_strategy
        metadata.setdefault("parser_backend_requested", parser_backend)
        metadata.setdefault("chunk_strategy_requested", chunk_strategy)

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)
        # Avoid raising errors to keep the document flow intact.

    @staticmethod
    def _parsed_table_input_from_document(doc: Document, *, table_index: int) -> dict[str, Any] | None:
        meta = doc.metadata if isinstance(getattr(doc, "metadata", None), dict) else {}
        if not _is_table_segment_metadata(meta):
            return None
        markdown = str(doc.page_content or "")
        if not markdown.strip():
            return None

        page_i = _optional_int(meta.get("page")) or 0
        label = f"Table {table_index + 1}"
        if page_i > 0:
            label = f"Page {page_i} Table {table_index + 1}"
        return {
            "markdown": markdown,
            "sheet_name": label,
            "source_page": (page_i if page_i > 0 else None),
            "source_bbox": meta.get("element_bbox") or meta.get("bbox"),
            "source_element_id": meta.get("source_element_id") or meta.get("element_id"),
            "source_table_shape": meta.get("table_shape"),
            "source_table_columns": meta.get("table_columns"),
        }

    @classmethod
    def _collect_parsed_table_inputs(cls, documents: list[Document]) -> list[dict[str, Any]]:
        table_inputs: list[dict[str, Any]] = []
        for doc in documents or []:
            table_input = cls._parsed_table_input_from_document(doc, table_index=len(table_inputs))
            if table_input is None:
                continue
            table_inputs.append(table_input)
            if len(table_inputs) >= 500:
                break
        return table_inputs

    @staticmethod
    def _import_table_store_assets(
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        document_id: UUID,
        table_inputs: list[dict[str, Any]],
        pipeline_effective: PipelineEffective,
    ) -> list[Any] | None:
        try:
            from app.services.table_store_service import import_markdown_tables

            return import_markdown_tables(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                tables=table_inputs,
                max_rows=int(getattr(pipeline_effective, "table_store_max_rows", 0) or 0),
                max_cols=int(getattr(pipeline_effective, "table_store_max_cols", 0) or 0),
                sample_rows=int(getattr(pipeline_effective, "table_store_sample_rows", 0) or 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Parsed table import failed (ignored): %s document_id=%s", str(exc)[:200], document_id)
            return None

    @staticmethod
    def _parsed_table_asset_payload(asset: Any, source_info: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "table_id": str(getattr(asset, "table_id", "")),
            "sheet_index": int(getattr(asset, "sheet_index", 0) or 0),
            "sheet_name": getattr(asset, "sheet_name", None),
            "row_count": int(getattr(asset, "row_count", 0) or 0),
            "col_count": int(getattr(asset, "col_count", 0) or 0),
            "truncated": bool(getattr(asset, "truncated", False)),
            "columns": list(getattr(asset, "columns", None) or []),
            "sample_rows": list(getattr(asset, "sample_rows", None) or []),
            "source_page": source_info.get("source_page"),
            "routing_kind": "tag_sidecar",
            "routing_source": "parser_table_segment",
        }
        for source_key in (
            "source_bbox",
            "source_element_id",
            "source_table_shape",
            "source_table_columns",
        ):
            value = source_info.get(source_key)
            if value not in (None, "", [], {}):
                payload[source_key] = value
        return payload

    @classmethod
    def _parsed_table_assets_payload(
        cls,
        *,
        assets: list[Any],
        table_inputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tables_payload: list[dict[str, Any]] = []
        for idx, asset in enumerate(assets or []):
            source_info = table_inputs[idx] if idx < len(table_inputs) else {}
            tables_payload.append(cls._parsed_table_asset_payload(asset, source_info))
        return tables_payload

    @staticmethod
    def _parsed_table_store_source_ext(db_document: DBDocument) -> str | None:
        source_ext = getattr(db_document, "file_type", None)
        return f".{str(source_ext).lower().lstrip('.')}" if source_ext else None

    @classmethod
    def _apply_parsed_table_store_metadata(
        cls,
        *,
        metadata: dict[str, Any],
        db_document: DBDocument,
        assets: list[Any],
        table_inputs: list[dict[str, Any]],
        pipeline_effective: PipelineEffective,
    ) -> dict[str, Any]:
        if not assets:
            existing = metadata.get("table_store")
            if isinstance(existing, dict) and str(existing.get("source_ext") or "").lower() in {".pdf"}:
                metadata.pop("table_store", None)
            return metadata

        exclusive_enabled = bool(getattr(pipeline_effective, "table_store_sidecar_exclusive_routing", False))
        metadata["table_store"] = {
            "version": "1",
            "source_ext": cls._parsed_table_store_source_ext(db_document),
            "imported_at": dt.datetime.now(dt.UTC).isoformat(),
            "routing": {
                "kind": "tag_sidecar",
                "source": "parser_table_segments",
                "exclusive_rag_routing_enabled": exclusive_enabled,
            },
            "tables": cls._parsed_table_assets_payload(assets=assets, table_inputs=table_inputs),
        }
        return metadata

    @classmethod
    def _persist_parsed_table_store_metadata(
        cls,
        db: Session,
        *,
        db_document: DBDocument,
        assets: list[Any],
        table_inputs: list[dict[str, Any]],
        pipeline_effective: PipelineEffective,
    ) -> None:
        try:
            next_meta = cls._apply_parsed_table_store_metadata(
                metadata=dict(db_document.doc_metadata or {}),
                db_document=db_document,
                assets=assets,
                table_inputs=table_inputs,
                pipeline_effective=pipeline_effective,
            )
            next_meta = apply_parse_quality_gate_metadata(next_meta)
            if next_meta != (db_document.doc_metadata or {}):
                db_document.doc_metadata = next_meta
                db.commit()
                db.refresh(db_document)
        except Exception as exc:  # noqa: BLE001
            logger.info("Failed to persist parsed table_store metadata (ignored): %s document_id=%s", str(exc)[:200], db_document.id)

    def _import_parsed_markdown_tables_to_store(
        self,
        db: Session,
        *,
        db_document: DBDocument,
        tenant_id: UUID,
        documents: list[Document],
        pipeline_effective: PipelineEffective,
    ) -> int:
        """
        Best-effort: import parser-emitted table segments into the per-document Table Store.

        Why:
        - Some parsers (e.g. PDF backends) emit tables as separate Documents with metadata markers.
        - We store those tables as a TAG sidecar so dataset table endpoints + chat TAG can use them.
        """
        if not bool(getattr(pipeline_effective, "table_store_enabled", False)):
            return 0

        dataset_id = getattr(db_document, "dataset_id", None)
        document_id = getattr(db_document, "id", None)
        if dataset_id is None or document_id is None:
            return 0

        table_inputs = self._collect_parsed_table_inputs(documents)
        if not table_inputs:
            return 0

        assets = self._import_table_store_assets(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            table_inputs=table_inputs,
            pipeline_effective=pipeline_effective,
        )
        if assets is None:
            return 0

        self._persist_parsed_table_store_metadata(
            db,
            db_document=db_document,
            assets=assets,
            table_inputs=table_inputs,
            pipeline_effective=pipeline_effective,
        )
        return len(assets or [])

    @staticmethod
    def _table_sidecar_excluded_sample(*, index: int, meta: dict[str, Any]) -> dict[str, Any]:
        page = _optional_int(meta.get("page"))
        return {
            "chunk_index": int(index),
            "page": page,
            "content_type": str(meta.get("content_type") or "").strip().lower() or None,
            "doc_type_kwd": str(meta.get("doc_type_kwd") or "").strip().lower() or None,
        }

    @staticmethod
    def _mark_table_sidecar_routing(meta: dict[str, Any]) -> None:
        meta.setdefault("table_routing_kind", "tag_sidecar")
        meta.setdefault("table_routing_source", "parser_table_segment")

    @staticmethod
    def _mark_non_table_rag_routing(meta: dict[str, Any]) -> None:
        meta.setdefault("table_routing_kind", "rag_text")
        meta.setdefault("table_routing_source", "non_table_content")
        meta.setdefault("table_rag_excluded", False)
        meta.setdefault("table_rag_exclusion_reason", None)

    @staticmethod
    def _build_table_sidecar_audit(
        *,
        enabled: bool,
        imported: int,
        table_seen: int,
        table_excluded: int,
        excluded_samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "version": "1",
            "mode": "table_sidecar_exclusive",
            "enabled": bool(enabled),
            "sidecar_tables_imported": int(imported),
            "table_chunks_seen": int(table_seen),
            "table_chunks_excluded_from_rag": int(table_excluded),
            "rag_exclusion_reason": ("table_sidecar_exclusive" if table_excluded > 0 else None),
            "excluded_samples": excluded_samples,
        }

    def _route_table_sidecar_chunk(
        self,
        *,
        index: int,
        chunk: Document,
        imported: int,
        should_exclude: bool,
        excluded_samples: list[dict[str, Any]],
    ) -> tuple[bool, bool]:
        meta = dict(chunk.metadata or {})
        if not _is_table_segment_metadata(meta):
            if imported > 0:
                self._mark_non_table_rag_routing(meta)
                chunk.metadata = meta
            return False, False

        self._mark_table_sidecar_routing(meta)
        if should_exclude:
            if len(excluded_samples) < 20:
                excluded_samples.append(self._table_sidecar_excluded_sample(index=index, meta=meta))
            return True, True

        meta["table_rag_excluded"] = False
        meta["table_rag_exclusion_reason"] = None
        chunk.metadata = meta
        return True, False

    def _apply_table_sidecar_exclusive_routing(
        self,
        *,
        chunks: list[Document],
        enabled: bool,
        sidecar_tables_imported: int,
    ) -> tuple[list[Document], dict[str, Any]]:
        """
        Optional TAG/RAG separation for parser-emitted table segments.

        When enabled and we already imported parser tables into table_store sidecar,
        drop table chunks from the RAG indexing path to avoid table-noise dominance.
        """
        imported = max(0, int(sidecar_tables_imported or 0))
        should_exclude = bool(enabled) and imported > 0
        excluded_samples: list[dict[str, Any]] = []
        kept: list[Document] = []
        table_seen = 0
        table_excluded = 0

        for idx, chunk in enumerate(chunks or []):
            is_table, excluded = self._route_table_sidecar_chunk(
                index=idx,
                chunk=chunk,
                imported=imported,
                should_exclude=should_exclude,
                excluded_samples=excluded_samples,
            )
            if is_table:
                table_seen += 1
            if excluded:
                table_excluded += 1
                continue
            kept.append(chunk)

        return kept, self._build_table_sidecar_audit(
            enabled=enabled,
            imported=imported,
            table_seen=table_seen,
            table_excluded=table_excluded,
            excluded_samples=excluded_samples,
        )

    def _cleanup_parser_artifacts(self, artifact_dirs: set[str], *, tenant_id: UUID) -> None:
        if not artifact_dirs:
            return
        if bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False)):
            return

        upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
        tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)

        for raw in sorted(artifact_dirs):
            try:
                path = Path(raw).resolve(strict=False)
                if not path.exists():
                    continue
                if not any(p in path.parts for p in {".magicpdf", ".deepseek_ocr", ".qianfan_ocr", ".etl4llm", ".marker", ".paddlevl", ".olmocr", MIMIRQ_PARSE_DIRNAME}):
                    continue
                # Safety: only delete within this tenant's upload directory.
                path.relative_to(tenant_root)
            except Exception:
                logger.warning("Skipping unsafe parser artifact cleanup: %s", str(raw)[:200])
                continue

            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception as exc:
                _log_processor_fallback('_cleanup_parser_artifacts', exc)
                # Best-effort only.

    def _record_pipeline_effective(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        effective: PipelineEffective,
    ) -> None:
        """Persist effective pipeline settings on the document metadata."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if not db_doc:
            return

        kg_python_plugin = str(getattr(effective, "kg_python_plugin", "") or "").strip()
        if not kg_python_plugin:
            kg_python_plugin = derive_registered_stage_plugin_ref(
                str(getattr(effective, "chunk_python_plugin", "") or "").strip(),
                "kg",
            )
        kg_python_params = dict(getattr(effective, "kg_python_params", {}) or {})
        metadata = dict(db_doc.doc_metadata or {})
        metadata["pipeline_effective"] = {
            "governance_enabled": bool(effective.governance_enabled),
            "governance_remove_toc_lines": bool(effective.governance_remove_toc_lines),
            "governance_remove_noise_lines": bool(effective.governance_remove_noise_lines),
            "governance_unwrap_lines": bool(effective.governance_unwrap_lines),
            "governance_remove_common_lines": bool(effective.governance_remove_common_lines),
            "governance_unwrap_max_line_length": int(effective.governance_unwrap_max_line_length),
            "governance_noise_min_chars": int(effective.governance_noise_min_chars),
            "governance_noise_ratio_threshold": float(effective.governance_noise_ratio_threshold),
            "governance_common_lines_min_docs": int(effective.governance_common_lines_min_docs),
            "governance_common_lines_min_ratio": float(effective.governance_common_lines_min_ratio),
            "governance_python_plugin": str(getattr(effective, "governance_python_plugin", "") or ""),
            "governance_python_params": dict(getattr(effective, "governance_python_params", {}) or {}),
            "governance_llm_auto_tagging_enabled": bool(
                getattr(effective, "governance_llm_auto_tagging_enabled", False)
            ),
            "governance_llm_auto_tagging_max_chars": int(
                getattr(effective, "governance_llm_auto_tagging_max_chars", 3000) or 3000
            ),
            "governance_llm_auto_tagging_max_items": int(
                getattr(effective, "governance_llm_auto_tagging_max_items", 16) or 16
            ),
            "ingest_pre_poc_scanner_enabled": bool(getattr(effective, "ingest_pre_poc_scanner_enabled", False)),
            "ingest_pre_poc_quality_gate_mode": str(
                getattr(effective, "ingest_pre_poc_quality_gate_mode", "warn") or "warn"
            ),
            "chunk_size": int(effective.chunk_size),
            "chunk_overlap": int(effective.chunk_overlap),
            "chunk_merge_small_min_chars": int(getattr(effective, "chunk_merge_small_min_chars", 0) or 0),
            "chunk_strategy_params": dict(getattr(effective, "chunk_strategy_params", {}) or {}),
            "chunk_python_plugin": str(getattr(effective, "chunk_python_plugin", "") or ""),
            "chunk_python_params": dict(getattr(effective, "chunk_python_params", {}) or {}),
            "kg_python_plugin": kg_python_plugin,
            "kg_python_params": kg_python_params,
            "chunk_vector_enabled": bool(effective.chunk_vector_enabled),
            "bm25_index_enabled": bool(effective.bm25_index_enabled),
            "kg_enabled": bool(effective.kg_enabled),
            "event_vector_enabled": bool(effective.event_vector_enabled),
            "entity_vector_enabled": bool(effective.entity_vector_enabled),
        }

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _persist_parsed_content(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        original_markdown: str,
        cleaned_markdown: str,
        max_chars: int,
    ) -> dict[str, Any]:
        """
        Persist parsed markdown content for audit/debug purposes.

        This stores two versions:
        - original_markdown_content: parsed output after normalize stage (pre-governance)
        - markdown_content: parsed output after governance cleaning
        """
        def _truncate(text: str) -> tuple[str, bool, int, int]:
            raw = text or ""
            raw_len = len(raw)
            if max_chars <= 0 or raw_len <= max_chars:
                return raw, False, raw_len, raw_len
            marker = "\n\n...[TRUNCATED]..."
            keep = max(0, max_chars - len(marker))
            truncated = raw[:keep] + marker
            return truncated, True, raw_len, len(truncated)

        max_chars_eff = max(0, int(max_chars or 0))
        orig_trunc, orig_is_trunc, orig_raw_len, orig_stored_len = _truncate(original_markdown)
        clean_trunc, clean_is_trunc, clean_raw_len, clean_stored_len = _truncate(cleaned_markdown)

        rec = (
            db.query(DocumentParsedContent)
            .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
            .first()
        )
        if rec is None:
            rec = DocumentParsedContent(
                tenant_id=tenant_id,
                document_id=document_id,
                markdown_content=clean_trunc,
                original_markdown_content=orig_trunc,
            )
            db.add(rec)
        else:
            rec.markdown_content = clean_trunc
            rec.original_markdown_content = orig_trunc

        db.commit()
        db.refresh(rec)

        return {
            "enabled": True,
            "max_chars": int(max_chars_eff),
            "original": {"raw_len": int(orig_raw_len), "stored_len": int(orig_stored_len), "truncated": bool(orig_is_trunc)},
            "cleaned": {"raw_len": int(clean_raw_len), "stored_len": int(clean_stored_len), "truncated": bool(clean_is_trunc)},
        }

    def _build_governance_audit_metadata_patch(
        self,
        *,
        before_items: list[Document] | None,
        after_items: list[Document] | None,
    ) -> dict[str, Any]:
        """
        Build lightweight governance audit metadata (privacy-safe).

        This is intentionally small and derived from:
        - char counts (before/after governance)
        - governance quality metrics (density / outline ratio)
        """

        before = list(before_items or [])
        after = list(after_items or [])

        original_chars = sum(len(d.page_content or "") for d in before)
        cleaned_chars = sum(len(d.page_content or "") for d in after)
        patch: dict[str, Any] = {
            "governance_char_stats": {
                "original_chars": int(max(0, original_chars)),
                "cleaned_chars": int(max(0, cleaned_chars)),
                "reduction_pct": int(max(0, min(100, _governance_reduction_pct(
                    original_chars=original_chars,
                    cleaned_chars=cleaned_chars,
                )))),
            }
        }

        # Prefer post-governance text for quality metrics; fallback to pre-governance when fully dropped.
        source_items = after if after else before
        if not source_items:
            return patch

        patch["governance_quality"] = _aggregate_governance_quality(source_items)
        patch["governance_quality_source"] = "cleaned" if after else "pre_governance"
        return patch

    def _record_governance_metadata(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        stats: GovernanceStats,
        rule_packs: list[str] | None = None,
        audit_patch: dict[str, Any] | None = None,
    ) -> None:
        """Persist governance stats on the document metadata."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["governance_enabled"] = True
        metadata["governance_version"] = str(getattr(stats, "version", None) or metadata.get("governance_version") or "1")
        metadata["governance_documents"] = int(stats.documents)
        metadata["governance_changed_documents"] = int(stats.changed)
        metadata["governance_rules_applied"] = int(stats.applied_rules)
        metadata["governance_dropped_documents"] = int(getattr(stats, "dropped", 0) or 0)

        drop_reasons = _string_count_map(getattr(stats, "drop_reasons", None))
        if drop_reasons:
            metadata["governance_drop_reasons"] = drop_reasons
        pii_hits = _string_count_map(getattr(stats, "pii_hits", None))
        if pii_hits:
            metadata["governance_pii_hits"] = pii_hits
        secrets_hits = _string_count_map(getattr(stats, "secrets_hits", None))
        if secrets_hits:
            metadata["governance_secrets_hits"] = secrets_hits

        # Persist richer "effects" counters for dataset-level governance audit (best-effort).
        metadata.update(_positive_governance_counts(stats))

        languages = _positive_string_count_map(getattr(stats, "languages", None))
        if languages:
            # Keep small; caller can still use governance_enrichment.language for a canonical single value.
            metadata["governance_languages"] = languages

        cleaned_rule_packs = _clean_governance_rule_packs(rule_packs)
        if cleaned_rule_packs:
            metadata["governance_rule_packs"] = cleaned_rule_packs

        if isinstance(audit_patch, dict) and audit_patch:
            metadata.update(audit_patch)

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    @staticmethod
    def _add_limited_string_values(target: set[str], values: Any, *, max_len: int) -> None:
        if not isinstance(values, list):
            return
        for item in values:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value:
                target.add(value[:max_len])

    @staticmethod
    def _update_governance_frontmatter_and_title(state: dict[str, Any], meta: dict[str, Any]) -> None:
        if state.get("frontmatter") is None:
            frontmatter = meta.get("document_frontmatter")
            if isinstance(frontmatter, dict) and frontmatter:
                state["frontmatter"] = frontmatter

        if state.get("title") is None:
            raw_title = meta.get("document_title")
            if isinstance(raw_title, str) and raw_title.strip():
                state["title"] = raw_title.strip()[:200]

    @staticmethod
    def _update_governance_keyword_provider(state: dict[str, Any], meta: dict[str, Any]) -> None:
        if state.get("keywords_provider") is not None:
            return
        raw_provider = meta.get("document_keywords_provider")
        if isinstance(raw_provider, str) and raw_provider.strip():
            state["keywords_provider"] = raw_provider.strip()[:50]

    @staticmethod
    def _update_governance_language_state(state: dict[str, Any], meta: dict[str, Any]) -> None:
        raw_lang = meta.get("document_language")
        if not isinstance(raw_lang, str) or not raw_lang.strip():
            return
        lang = raw_lang.strip()
        state["lang_counts"][lang] = state["lang_counts"].get(lang, 0) + 1
        raw_conf = meta.get("document_language_confidence")
        if isinstance(raw_conf, (int, float)):
            state["conf_sum"] += float(raw_conf)
            state["conf_n"] += 1

    @staticmethod
    def _update_governance_enrichment_state(state: dict[str, Any], meta: dict[str, Any]) -> None:
        DocumentProcessorService._update_governance_frontmatter_and_title(state, meta)
        DocumentProcessorService._add_limited_string_values(state["tags"], meta.get("document_tags"), max_len=64)
        DocumentProcessorService._add_limited_string_values(
            state["keywords"],
            meta.get("document_keywords"),
            max_len=64,
        )
        DocumentProcessorService._update_governance_keyword_provider(state, meta)
        DocumentProcessorService._update_governance_language_state(state, meta)

    @staticmethod
    def _build_governance_enrichment_payload(state: dict[str, Any]) -> dict[str, object]:
        enrichment: dict[str, object] = {}
        if state.get("title"):
            enrichment["title"] = state["title"]
        if state.get("tags"):
            enrichment["tags"] = sorted(state["tags"])
        lang_counts = state.get("lang_counts") if isinstance(state.get("lang_counts"), dict) else {}
        if lang_counts:
            language = min(lang_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            enrichment["language"] = language
            if int(state.get("conf_n") or 0) > 0:
                enrichment["language_confidence"] = round(float(state.get("conf_sum") or 0.0) / int(state["conf_n"]), 3)
        if state.get("keywords"):
            enrichment["keywords"] = sorted(state["keywords"])
            enrichment["keywords_provider"] = state.get("keywords_provider") or "auto"
        if state.get("frontmatter"):
            enrichment["frontmatter"] = state["frontmatter"]
        return enrichment

    @staticmethod
    def _collect_governance_enrichment_payload(items: list[Document]) -> dict[str, object]:
        state: dict[str, Any] = {
            "title": None,
            "tags": set(),
            "keywords": set(),
            "keywords_provider": None,
            "frontmatter": None,
            "lang_counts": {},
            "conf_sum": 0.0,
            "conf_n": 0,
        }
        for doc in items:
            DocumentProcessorService._update_governance_enrichment_state(state, doc.metadata or {})
        return DocumentProcessorService._build_governance_enrichment_payload(state)

    async def _apply_llm_auto_tagging(
        self,
        items: list[Document] | None,
        *,
        pipeline_effective: PipelineEffective,
    ) -> dict[str, Any] | None:
        if not items or not bool(getattr(pipeline_effective, "governance_llm_auto_tagging_enabled", False)):
            return None
        max_chars = max(200, int(getattr(pipeline_effective, "governance_llm_auto_tagging_max_chars", 3000) or 3000))
        max_items = max(1, int(getattr(pipeline_effective, "governance_llm_auto_tagging_max_items", 16) or 16))
        text_parts: list[str] = []
        remaining = max_chars
        for item in items:
            content = str(getattr(item, "page_content", "") or "").strip()
            if not content:
                continue
            text_parts.append(content[:remaining])
            remaining -= min(len(content), remaining)
            if remaining <= 0:
                break
        source_text = "\n\n".join(text_parts).strip()
        if not source_text:
            return {"enabled": True, "used": False, "reason": "empty_text"}

        try:
            from app.rag.preprocessing.llm_tagger import extract_llm_tags

            result = await extract_llm_tags(text=source_text, max_chars=max_chars, max_items=max_items)
        except Exception as exc:  # noqa: BLE001
            _log_processor_fallback('_apply_llm_auto_tagging', exc)
            return {"enabled": True, "used": False, "error": str(exc)[:160]}

        tag_values: list[str] = []
        keyword_values: list[str] = []
        structured_tags: list[dict[str, Any]] = []
        for tag in list(getattr(result, "document_tags", []) or [])[:max_items]:
            value = str(getattr(tag, "value", "") or "").strip()
            if not value:
                continue
            tag_type = str(getattr(tag, "type", "") or "").strip()
            if tag_type == "keyword":
                keyword_values.append(value)
            else:
                tag_values.append(value)
            structured_tags.append(tag.model_dump() if hasattr(tag, "model_dump") else dict(tag))
        if not tag_values and not keyword_values and not structured_tags:
            return {"enabled": True, "used": False, "provider": getattr(result, "provider", "llm")}

        first = items[0]
        meta = dict(first.metadata or {})
        existing_tags = [str(x).strip() for x in (meta.get("document_tags") or []) if isinstance(x, str) and str(x).strip()]
        existing_keywords = [
            str(x).strip() for x in (meta.get("document_keywords") or []) if isinstance(x, str) and str(x).strip()
        ]
        meta["document_tags"] = list(dict.fromkeys([*existing_tags, *tag_values]))[:max_items]
        if keyword_values:
            meta["document_keywords"] = list(dict.fromkeys([*existing_keywords, *keyword_values]))[:max_items]
            meta["document_keywords_provider"] = "llm"
        if structured_tags:
            meta["document_llm_auto_tags"] = structured_tags[:max_items]
        summary = str(getattr(result, "summary", "") or "").strip()
        if summary:
            meta["document_llm_auto_summary"] = summary[:1000]
        meta["document_llm_auto_tagging"] = {
            "enabled": True,
            "used": True,
            "provider": str(getattr(result, "provider", "llm") or "llm"),
            "tag_count": len(meta.get("document_tags") or []),
            "keyword_count": len(meta.get("document_keywords") or []),
        }
        first.metadata = meta
        return dict(meta["document_llm_auto_tagging"])

    def _record_governance_enrichment_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        items: list[Document] | None,
    ) -> None:
        if not items:
            return

        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        enrichment = self._collect_governance_enrichment_payload(items)
        if not enrichment:
            return

        metadata = dict(db_doc.doc_metadata or {})
        existing = metadata.get("governance_enrichment")
        merged: dict[str, object] = dict(existing) if isinstance(existing, dict) else {}
        merged.update(enrichment)
        metadata["governance_enrichment"] = merged
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    @staticmethod
    def _strip_doc_enrichment_fields(items: list[Document] | None) -> None:
        if not items:
            return
        to_drop = {
            "document_frontmatter",
            "document_tags",
            "document_keywords",
            "document_keywords_provider",
            "document_llm_auto_summary",
            "document_llm_auto_tags",
            "document_llm_auto_tagging",
            # Stored at document-level; avoid duplicating into every chunk metadata.
            "governance_quality",
        }
        for d in items:
            meta = dict(d.metadata or {})
            changed = False
            for k in to_drop:
                if k in meta:
                    meta.pop(k, None)
                    changed = True
            if changed:
                d.metadata = meta

    def _record_auto_chunking_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        selected_counts: dict[str, int],
    ) -> None:
        """Persist auto-chunk selection stats on the document metadata."""
        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return
        metadata = dict(db_doc.doc_metadata or {})
        metadata["auto_chunking"] = {
            "selected_counts": {str(k): int(v) for k, v in sorted(selected_counts.items())},
        }
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_chunk_postprocess_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        stats: ChunkPostprocessStats,
    ) -> None:
        """Persist chunk postprocessing stats (dedup/truncation) on the document metadata."""
        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["chunk_postprocess"] = {
            "merge_small_enabled": bool(stats.merge_small_enabled),
            "merge_small_min_chars": int(stats.merge_small_min_chars),
            "merge_small_before": int(stats.merge_small_before),
            "merge_small_after": int(stats.merge_small_after),
            "merge_small_reduced": int(stats.merge_small_reduced),
            "dedup_enabled": bool(stats.dedup_enabled),
            "dedup_dropped": int(stats.dedup_dropped),
            "max_chunks_per_document": int(stats.max_chunks_per_document),
            "max_chunks_strategy": str(stats.max_chunks_strategy or "").strip() or "head",
            "truncated": bool(int(stats.truncated_dropped) > 0),
            "truncated_from": int(stats.truncated_from),
            "truncated_to": int(stats.truncated_to),
            "truncated_dropped": int(stats.truncated_dropped),
            "truncated_asset_total": int(stats.truncated_asset_total),
            "truncated_asset_kept": int(stats.truncated_asset_kept),
        }
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    @staticmethod
    def _chunk_coverage_range(chunk: Document) -> tuple[int, int] | None:
        meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        start = _optional_int(meta.get("start_char"))
        if start is None:
            return None
        end = _optional_int(meta.get("end_char"))
        if end is None:
            end = start + len(chunk.page_content or "")
        if end <= start:
            return None
        return start, end

    @staticmethod
    def _chunk_coverage_ranges(chunks: list[Document]) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        for chunk in chunks:
            text_range = DocumentProcessorService._chunk_coverage_range(chunk)
            if text_range is not None:
                ranges.append(text_range)
        return ranges

    @staticmethod
    def _chunk_quality_gate_inputs(
        *,
        stats: dict[str, Any] | None,
        coverage: dict[str, float | int] | None,
    ) -> dict[str, float | int]:
        def int_metric(source: dict[str, Any] | None, key: str) -> int:
            return int((source or {}).get(key) or 0) if isinstance(source, dict) else 0

        def float_metric(source: dict[str, Any] | None, key: str) -> float:
            return float((source or {}).get(key) or 0.0) if isinstance(source, dict) else 0.0

        return {
            "count": int_metric(stats, "count"),
            "short_count": int_metric(stats, "short_count"),
            "duplicate_count": int_metric(stats, "duplicate_count"),
            "covered_chars": int_metric(coverage, "covered_chars"),
            "coverage_ratio": float_metric(coverage, "coverage_ratio"),
            "overlap_waste_ratio": float_metric(coverage, "overlap_waste_ratio"),
            "gap_count": int_metric(coverage, "gap_count"),
        }

    @staticmethod
    def _compute_chunk_quality_gate_metadata(
        *,
        metadata: dict[str, Any],
        stats: dict[str, Any] | None,
        coverage: dict[str, float | int] | None,
        chunks_count: int,
        total_chars: int,
        compute_chunk_quality_gate: Any,
    ) -> tuple[dict[str, object] | None, list[str], list[dict[str, object]]]:
        try:
            effective = metadata.get("pipeline_effective") if isinstance(metadata.get("pipeline_effective"), dict) else {}
            gate_raw, recs_raw, patches_raw = compute_chunk_quality_gate(
                stats=DocumentProcessorService._chunk_quality_gate_inputs(stats=stats, coverage=coverage),
                total_chunks=int(chunks_count),
                total_characters=total_chars,
                chunk_size=int(effective.get("chunk_size") or 0),
                chunk_overlap=int(effective.get("chunk_overlap") or 0),
                original_text_included=False,
                original_text_truncated=False,
                original_text_max_chars=0,
            )
            gate = gate_raw if isinstance(gate_raw, dict) else None
            recs = [str(x) for x in (recs_raw or []) if str(x or "").strip()]
            patches = [p for p in (patches_raw or []) if isinstance(p, dict)]
            return gate, recs, patches
        except Exception as exc:
            _log_processor_fallback('_record_chunking_stats_metadata', exc)
            return None, [], []

    @staticmethod
    def _apply_chunking_stats_metadata(
        metadata: dict[str, Any],
        *,
        stats: dict[str, Any] | None,
        token_stats: dict[str, Any] | None,
        coverage: dict[str, float | int] | None,
        ranges_count: int,
        gate: dict[str, object] | None,
        recs: list[str],
        patches: list[dict[str, object]],
    ) -> None:
        if stats:
            metadata["chunking_stats"] = stats
        if token_stats:
            metadata["chunking_stats_tokens"] = token_stats
        if coverage:
            cov = dict(coverage)
            cov["ranges_used"] = int(ranges_count)
            metadata["chunk_coverage"] = cov
        if gate:
            metadata["chunk_quality_gate"] = gate
        if recs:
            metadata["chunk_quality_recommendations"] = recs[:10]
        if patches:
            metadata["chunk_quality_patches"] = patches[:10]

    def _record_chunking_stats_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        chunks: list[Document],
        short_threshold: int = 120,
        total_characters: int | None = None,
    ) -> None:
        """Persist basic chunking stats (length distribution, duplicates) on the document metadata.

        This is best-effort and should never affect ingestion success.
        """
        if not chunks:
            return

        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges
        from app.services.chunk_quality_gate import compute_chunk_quality_gate
        from app.services.chunking_stats_utils import (
            compute_chunking_stats_from_texts,
            compute_chunking_stats_from_texts_tokens,
        )

        stats = compute_chunking_stats_from_texts(
            ((c.page_content or "") for c in chunks),
            short_threshold=int(short_threshold or 0),
        )
        token_stats = compute_chunking_stats_from_texts_tokens(((c.page_content or "") for c in chunks))

        # Best-effort chunk coverage metrics (requires offsets).
        ranges = self._chunk_coverage_ranges(chunks)
        total_chars = int(total_characters or 0) or int(getattr(db_doc, "total_characters", 0) or 0)
        coverage: dict[str, float | int] | None = None
        if ranges and total_chars > 0:
            coverage = compute_chunk_coverage_metrics_from_ranges(
                ranges,
                total_characters=total_chars,
            )

        metadata = dict(db_doc.doc_metadata or {})
        # Quality gate (heuristics; same as preview but best-effort here).
        gate, recs, patches = self._compute_chunk_quality_gate_metadata(
            metadata=metadata,
            stats=stats,
            coverage=coverage,
            chunks_count=len(chunks),
            total_chars=total_chars,
            compute_chunk_quality_gate=compute_chunk_quality_gate,
        )
        self._apply_chunking_stats_metadata(
            metadata,
            stats=stats,
            token_stats=token_stats,
            coverage=coverage,
            ranges_count=len(ranges),
            gate=gate,
            recs=recs,
            patches=patches,
        )
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_document_image_ids(self, db: Session, tenant_id: UUID, document_id: UUID, img_ids: set[str]):
        """
        Store all img_id values for a document in documents.metadata for cleanup.

        Notes:
        - This is a document-level aggregated list (deduped); it does not affect per-chunk img_id.
        - Only written when MinIO is enabled to avoid misleading metadata.
        """
        if not settings.MINIO_ENABLED:
            return
        if not img_ids:
            return

        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        existing = metadata.get("img_ids")
        merged: set[str] = set()
        if isinstance(existing, list):
            for v in existing:
                if isinstance(v, str) and v.strip():
                    merged.add(v)

        merged |= {v for v in img_ids if isinstance(v, str) and v.strip()}
        if not merged:
            return

        metadata["img_ids"] = sorted(merged)
        metadata["image_count"] = len(merged)
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _extract_img_id_from_content(self, content: str) -> str | None:
        """
        Extract the first image-url/{img_id} from chunk content to backfill chunk metadata.
        """
        if not isinstance(content, str) or not content:
            return None

        # Supported patterns:
        # - ![](/api/v1/documents/image-url/{img_id})
        # - <img src="/api/v1/documents/image-url/{img_id}">
        # - http://host/api/v1/documents/image-url/{img_id}
        pattern = re.compile(r"(?:https?://[^\s)\"']+)?/api/v1/documents/image-url/([^\s)\"']+)")
        m = pattern.search(content)
        if not m:
            return None
        img_id = m.group(1)
        return img_id.strip() or None

    @staticmethod
    def _inline_image_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
        return (
            re.compile(
                r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
                flags=re.IGNORECASE,
            ),
            re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE),
        )

    @staticmethod
    def _collect_inline_image_refs(markdown_text: str, patterns: tuple[re.Pattern[str], re.Pattern[str]]) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in pattern.finditer(markdown_text):
                ref = match.group(1)
                if not isinstance(ref, str):
                    continue
                ref = ref.strip()
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                found.append(ref)
        return found

    @staticmethod
    def _resolve_inline_image_base_dir(origin_path: Path | None) -> Path | None:
        if origin_path is None:
            return None
        resolved_origin = origin_path.resolve(strict=False)
        base_dir = resolved_origin if resolved_origin.is_dir() else resolved_origin.parent
        return base_dir.resolve(strict=False)

    @staticmethod
    def _inline_image_ref_skipped(ref: str) -> bool:
        return urlparse(ref).scheme in {"http", "https"} or "/api/v1/documents/image-url/" in ref

    @staticmethod
    def _inline_file_url_path(ref: str) -> str | None:
        parsed = urlparse(ref)
        if str(parsed.scheme or "").lower() != "file":
            return None
        netloc = str(parsed.netloc or "").strip().lower()
        if netloc and netloc not in {"localhost", "127.0.0.1"}:
            return None
        resolved_ref = unquote(str(parsed.path or ""))
        if not resolved_ref:
            return None
        if re.match(r"^/[a-zA-Z]:/", resolved_ref):
            return resolved_ref[1:]
        return resolved_ref

    @staticmethod
    def _inline_local_ref_path_text(ref: str) -> str | None:
        if ref.lower().startswith("file://"):
            return DocumentProcessorService._inline_file_url_path(ref)
        return unquote(ref)

    @staticmethod
    def _resolve_inline_path_candidate(path_text: str, *, base_dir_resolved: Path) -> Path | None:
        path_obj = Path(path_text)
        if not path_obj.is_absolute():
            path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
        else:
            path_obj = path_obj.resolve(strict=False)
        try:
            path_obj.relative_to(base_dir_resolved)
        except Exception as exc:
            _log_processor_fallback('_upload_inline_images_to_minio', exc)
            return None
        return path_obj

    @staticmethod
    def _decode_inline_data_uri(ref: str, *, max_image_bytes: int) -> bytes | None:
        header, b64_part = ref.split(",", 1)
        if "base64" not in header:
            return None
        b64_part = re.sub(r"\s+", "", b64_part)
        if len(b64_part) > int(max_image_bytes * 4 / 3) + 32:
            return None
        return base64.b64decode(b64_part)

    @staticmethod
    def _resolve_inline_local_image_path(ref: str, *, base_dir_resolved: Path | None) -> Path | None:
        if not base_dir_resolved:
            return None
        path_text = DocumentProcessorService._inline_local_ref_path_text(ref)
        if not path_text:
            return None
        return DocumentProcessorService._resolve_inline_path_candidate(path_text, base_dir_resolved=base_dir_resolved)

    @classmethod
    def _read_inline_image_ref(
        cls,
        ref: str,
        *,
        base_dir_resolved: Path | None,
        max_image_bytes: int,
    ) -> bytes | None:
        if ref.startswith("data:image"):
            return cls._decode_inline_data_uri(ref, max_image_bytes=max_image_bytes)
        path_obj = cls._resolve_inline_local_image_path(ref, base_dir_resolved=base_dir_resolved)
        if path_obj is None or not path_obj.exists() or not path_obj.is_file():
            return None
        try:
            if path_obj.stat().st_size > max_image_bytes:
                return None
        except Exception as exc:
            _log_processor_fallback('_upload_inline_images_to_minio', exc)
            return None
        return path_obj.read_bytes()

    @staticmethod
    def _jpeg_bytes_from_binary(binary: bytes) -> bytes:
        img = None
        converted = None
        try:
            img = PILImage.open(BytesIO(binary))
            if img.mode in ("RGBA", "P"):
                converted = img.convert("RGB")
                out_img = converted
            else:
                out_img = img
            out = BytesIO()
            out_img.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue()
        finally:
            if converted is not None:
                try:
                    converted.close()
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            if img is not None:
                try:
                    img.close()
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @staticmethod
    def _rewrite_inline_image_refs(
        markdown_text: str,
        *,
        replacements: dict[str, str],
        patterns: tuple[re.Pattern[str], re.Pattern[str]],
    ) -> str:
        if not replacements:
            return markdown_text

        def replace_match(match: re.Match) -> str:
            raw = match.group(1) or ""
            new = replacements.get(raw.strip())
            if not new:
                return match.group(0)
            return match.group(0).replace(raw, new, 1)

        md_pat, html_pat = patterns
        markdown_text = md_pat.sub(replace_match, markdown_text)
        return html_pat.sub(replace_match, markdown_text)

    def _upload_inline_image_ref_to_minio(
        self,
        ref: str,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        cache: dict[str, str],
        idx: int,
        base_dir_resolved: Path | None,
        max_image_bytes: int,
    ) -> tuple[str | None, str | None, int]:
        if self._inline_image_ref_skipped(ref):
            return None, None, idx
        try:
            binary = self._read_inline_image_ref(
                ref,
                base_dir_resolved=base_dir_resolved,
                max_image_bytes=max_image_bytes,
            )
            if binary is None or len(binary) > max_image_bytes:
                return None, None, idx

            image_bytes = self._jpeg_bytes_from_binary(binary)
            digest = hashlib.sha256(image_bytes).hexdigest()
            img_id = cache.get(digest)
            new_img_id: str | None = None
            if not img_id:
                chunk_key = f"asset{idx}"
                idx += 1
                img_id = minio_service.upload_image(
                    image_data=image_bytes,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    document_id=document_id,
                    chunk_key=chunk_key,
                    extension="jpg",
                )
                cache[digest] = img_id
                new_img_id = img_id
            return f"/api/v1/documents/image-url/{img_id}", new_img_id, idx
        except Exception as exc:
            logger.warning("Inline/local image upload failed (skipped): %s", exc)
            return None, None, idx

    @classmethod
    def _collect_limited_inline_upload_refs(
        cls,
        markdown_text: str,
    ) -> tuple[tuple[re.Pattern[str], re.Pattern[str]], list[str]] | None:
        lowered = markdown_text.lower()
        if "data:image" not in lowered and "![" not in lowered and "<img" not in lowered:
            return None
        patterns = cls._inline_image_patterns()
        found = cls._collect_inline_image_refs(markdown_text, patterns)
        if not found:
            return None
        max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
        if max_inline_images and len(found) > max_inline_images:
            found = found[:max_inline_images]
        return patterns, found

    def _collect_inline_image_upload_replacements(
        self,
        found: list[str],
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        cache: dict[str, str],
        start_index: int,
        base_dir_resolved: Path | None,
        max_image_bytes: int,
    ) -> tuple[dict[str, str], list[str], int]:
        idx = int(start_index or 0)
        new_ids: list[str] = []
        replacements: dict[str, str] = {}
        for ref in found:
            url, new_img_id, idx = self._upload_inline_image_ref_to_minio(
                ref,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                cache=cache,
                idx=idx,
                base_dir_resolved=base_dir_resolved,
                max_image_bytes=max_image_bytes,
            )
            if url:
                replacements[ref] = url
            if new_img_id:
                new_ids.append(new_img_id)
        return replacements, new_ids, idx

    def _upload_inline_images_to_minio(
        self,
        markdown_text: str,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        cache: dict[str, str],
        start_index: int = 0,
        origin_path: Path | None = None,
    ) -> tuple[str, list[str], int]:
        """
        Upload image references in Markdown/HTML to MinIO and rewrite to /image-url/{img_id}.

        Supported:
        - data URI: data:image/...
        - local/relative paths: ![alt](images/foo.png) or <img src="images/foo.png">
          path resolution is relative to `origin_path.parent` (absolute paths are used as-is).
        - skip http/https URLs or already rewritten /api/v1/documents/image-url/... refs.

        Returns:
        - rewritten markdown_text
        - list of newly uploaded img_id values
        - updated asset index (for stable chunk_key: asset{n})
        """
        if not settings.MINIO_ENABLED:
            return markdown_text, [], start_index
        if not isinstance(markdown_text, str) or not markdown_text:
            return markdown_text, [], start_index

        refs = self._collect_limited_inline_upload_refs(markdown_text)
        if refs is None:
            return markdown_text, [], start_index
        patterns, found = refs

        base_dir_resolved = self._resolve_inline_image_base_dir(origin_path)
        max_image_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
        max_image_bytes = max(1_000_000, max_image_bytes)
        replacements, new_ids, idx = self._collect_inline_image_upload_replacements(
            found,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            cache=cache,
            start_index=start_index,
            base_dir_resolved=base_dir_resolved,
            max_image_bytes=max_image_bytes,
        )

        return self._rewrite_inline_image_refs(markdown_text, replacements=replacements, patterns=patterns), new_ids, idx

    def _integrated_chunk_file(self, file_path: Path, strategy: str):
        """
        Use integrated presets (naive/book/laws/email) to parse and chunk directly.
        Returns a list of LangChain Documents.
        """
        from langchain_core.documents import Document

        from app.rag.chunking.integrated_pipeline import chunk_file

        chunks_dict = chunk_file(file_path, strategy=strategy)  # type: ignore[arg-type]

        documents = []
        for item in chunks_dict:
            text = item.get("content_with_weight") or item.get("text") or ""
            if not text:
                continue
            meta = {k: v for k, v in item.items() if k not in {"content_with_weight", "text", "content_ltks", "content_sm_ltks"}}
            documents.append(Document(page_content=text, metadata=meta))

        return documents

    @staticmethod
    def _existing_metadata_image_id(metadata: dict[str, Any]) -> str | None:
        img_id = metadata.get("img_id")
        if isinstance(img_id, str) and img_id.strip():
            return img_id
        return None

    @staticmethod
    def _metadata_image_keys() -> tuple[str, ...]:
        return ("image_base64", "image", "img_base64", "img", "image_data")

    @staticmethod
    def _metadata_doc_type_is_image(metadata: dict[str, Any]) -> bool:
        return str(metadata.get("doc_type_kwd") or "").lower() == "image"

    @staticmethod
    def _drop_minio_disabled_image_metadata(metadata: dict[str, Any]) -> None:
        metadata.pop("image", None)

    @classmethod
    def _metadata_embedded_image(cls, metadata: dict[str, Any]) -> tuple[Any | None, str | None]:
        value = metadata.get("image")
        if value is None:
            return None, None
        if cls._metadata_doc_type_is_image(metadata):
            return value, "image"
        metadata.pop("image", None)
        return None, None

    @staticmethod
    def _metadata_image_path_candidate(raw_path: str, *, tenant_id: str) -> Path | None:
        try:
            upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
            tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
            candidate = Path(raw_path.strip()).resolve(strict=False)
            candidate.relative_to(tenant_root)
        except Exception as exc:
            _log_processor_fallback('_extract_and_upload_image_to_minio', exc)
            return None
        if not candidate.exists() or not candidate.is_file():
            return None
        return candidate

    @staticmethod
    def _safe_unlink_processor_path(path: Path) -> None:
        try:
            path.unlink()
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @staticmethod
    def _metadata_image_path_within_limit(path: Path) -> bool:
        max_bytes = int(getattr(settings, "MINIO_IMAGE_MAX_BYTES", 0) or 0)
        if max_bytes <= 0:
            return True
        try:
            size = int(path.stat().st_size)
        except Exception as exc:
            _log_processor_fallback('_extract_and_upload_image_to_minio', exc)
            size = 0
        return size <= max_bytes

    @classmethod
    def _metadata_image_path_payload(
        cls,
        metadata: dict[str, Any],
        *,
        tenant_id: str,
    ) -> tuple[Path | None, bytes | None, str | None]:
        raw_path = metadata.get("image_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None, None, None
        if not cls._metadata_doc_type_is_image(metadata):
            metadata.pop("image_path", None)
            return None, None, None

        candidate = cls._metadata_image_path_candidate(raw_path, tenant_id=tenant_id)
        if candidate is None:
            metadata.pop("image_path", None)
            return None, None, None
        if not cls._metadata_image_path_within_limit(candidate):
            metadata.pop("image_path", None)
            cls._safe_unlink_processor_path(candidate)
            return None, None, None
        try:
            return candidate, candidate.read_bytes(), "image_path"
        except Exception as exc:
            _log_processor_fallback('_extract_and_upload_image_to_minio', exc)
            metadata.pop("image_path", None)
            return None, None, None

    @staticmethod
    def _metadata_base64_image(metadata: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, str | None]:
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value, key
        return None, None

    @staticmethod
    def _strip_data_uri_payload(value: str | None) -> str | None:
        if not isinstance(value, str) or not value.startswith("data:"):
            return value
        parts = value.split(",", 1)
        return parts[1] if len(parts) == 2 else value

    @staticmethod
    def _jpeg_bytes_from_pil_image(img: Any) -> bytes:
        converted = None
        try:
            out_img = img
            if img.mode in ("RGBA", "P"):
                converted = img.convert("RGB")
                out_img = converted
            out = BytesIO()
            out_img.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue()
        finally:
            if converted is not None:
                try:
                    converted.close()
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @classmethod
    def _metadata_image_bytes(cls, *, raw_image: Any | None, b64_data: str | None) -> bytes:
        if raw_image is not None:
            if isinstance(raw_image, bytes):
                return cls._jpeg_bytes_from_binary(raw_image)
            return cls._jpeg_bytes_from_pil_image(raw_image)
        return cls._jpeg_bytes_from_binary(base64.b64decode(b64_data or ""))

    @staticmethod
    def _close_metadata_raw_image(raw_image: Any | None) -> None:
        if raw_image is None or isinstance(raw_image, bytes) or not hasattr(raw_image, "close"):
            return
        try:
            raw_image.close()
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @classmethod
    def _cleanup_uploaded_metadata_image_fields(
        cls,
        metadata: dict[str, Any],
        *,
        keys: tuple[str, ...],
        found_key: str | None,
        image_path: Path | None,
    ) -> None:
        if found_key:
            metadata.pop(found_key, None)
        for key in keys:
            if key != found_key:
                metadata.pop(key, None)
        if image_path is not None:
            cls._safe_unlink_processor_path(image_path)

    @classmethod
    def _upload_extracted_metadata_image(
        cls,
        metadata: dict[str, Any],
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        chunk_index: int,
        image_bytes: bytes,
        keys: tuple[str, ...],
        found_key: str | None,
        image_path: Path | None,
    ) -> str | None:
        try:
            img_id = minio_service.upload_image(
                image_data=image_bytes,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                chunk_key=str(metadata.get("chunk_key") or chunk_index),
                extension="jpg",
            )
            cls._cleanup_uploaded_metadata_image_fields(
                metadata,
                keys=keys,
                found_key=found_key,
                image_path=image_path,
            )
            logger.info("Image uploaded and bound: img_id=%s", img_id)
            return img_id
        except Exception as exc:
            logger.exception("Image upload failed: %s", exc)
            return None

    def _extract_and_upload_image_to_minio(
        self,
        metadata: dict[str, Any],
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        chunk_index: int,
    ) -> str | None:
        """
        Detect image data in chunk metadata, upload to MinIO, and return img_id.
        After upload, original image data is removed from metadata to save memory.

        img_id format: "{tenant_id}:{dataset_id}:{document_id}:{chunk_index}"

        Recognized fields: image (PIL.Image/bytes) / image_base64 / img_base64 / img / image_data
        """
        existing_img_id = self._existing_metadata_image_id(metadata)
        if existing_img_id is not None:
            return existing_img_id

        if not settings.MINIO_ENABLED:
            self._drop_minio_disabled_image_metadata(metadata)
            return None

        possible_keys = self._metadata_image_keys()
        raw_image, found_key = self._metadata_embedded_image(metadata)

        image_path: Path | None = None
        if raw_image is None:
            image_path, raw_image, path_key = self._metadata_image_path_payload(metadata, tenant_id=tenant_id)
            found_key = path_key or found_key

        b64_data = None
        if raw_image is None:
            b64_data, found_key = self._metadata_base64_image(metadata, possible_keys)

        if raw_image is None and not b64_data:
            return None

        b64_data = self._strip_data_uri_payload(b64_data)

        try:
            image_bytes = self._metadata_image_bytes(raw_image=raw_image, b64_data=b64_data)
        except Exception as exc:
            logger.warning("Image conversion failed (skip upload): %s", exc)
            if found_key == "image":
                metadata.pop("image", None)
            return None
        finally:
            self._close_metadata_raw_image(raw_image)

        return self._upload_extracted_metadata_image(
            metadata,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            chunk_index=chunk_index,
            image_bytes=image_bytes,
            keys=possible_keys,
            found_key=found_key,
            image_path=image_path,
        )

    def _extract_and_save_image(self, metadata: dict[str, Any], tenant_id: UUID) -> str | None:
        """
        Fallback: detect image data in chunk metadata and save to local disk.
        Used when MinIO is disabled.
        """
        if isinstance(metadata.get("img_id"), str) and metadata.get("img_id").strip():
            return metadata.get("img_id")

        possible_keys = ["image_base64", "image", "img_base64", "img"]
        b64_data = None
        for key in possible_keys:
            val = metadata.get(key)
            if isinstance(val, str) and val.strip():
                b64_data = val
                break
        if not b64_data:
            return None

        if b64_data.startswith("data:"):
            parts = b64_data.split(",", 1)
            if len(parts) == 2:
                b64_data = parts[1]

        try:
            binary = base64.b64decode(b64_data)
        except Exception as exc:
            _log_processor_fallback('_extract_and_save_image', exc)
            return None

        image_id = hashlib.sha256(binary).hexdigest()[:32]
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        file_path = images_dir / f"{image_id}.png"
        if not file_path.exists():
            with file_path.open("wb") as f:
                f.write(binary)

        return image_id


# Global instance.
document_processor = DocumentProcessorService()
