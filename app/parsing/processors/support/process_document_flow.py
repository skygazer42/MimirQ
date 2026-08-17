"""
Process-document flow helpers extracted from the main processor module.
"""


import asyncio
import contextlib
import datetime as dt
import re
import sys
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
from app.parsing.preprocess.file_preprocessor import preprocess_file
from app.parsing.preprocess.image_preprocess import preprocess_image_document
from app.parsing.processors.cross_page_merge import merge_cross_page_documents
from app.parsing.processors.parse_cache import LocalParseCacheStore
from app.parsing.processors.parse_cache import ParseCacheEntry as LocalParseCacheEntry
from app.parsing.processors.parse_cache import build_parse_cache_key as build_local_parse_cache_key
from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata
from app.parsing.processors.support.assets import _apply_inline_asset_audit_patch, _collect_parser_asset_refs
from app.parsing.processors.support.chunk_postprocess import (
    _ensure_ingest_page_indices,
    _joined_text_total_characters,
    _merge_small_chunks_by_min_chars,
    _rebase_chunk_offsets_by_page_index,
    _should_skip_near_dedup_for_chunk,
    _truncate_chunks_for_limit,
)
from app.parsing.processors.support.common import (
    _PROCESSOR_CLEANUP_LOG_MESSAGE,
    REDACTED_MASK,
    SECRET_MASK,
    _log_processor_fallback,
)
from app.parsing.processors.support.parse_io import (
    _attach_logical_source_metadata,
    _deserialize_documents_from_parse_cache,
    _join_document_page_content,
    _join_original_markdown_for_persistence,
    _serialize_documents_for_parse_cache,
)
from app.parsing.processors.support.quality import _seal_summary_to_specialty_signals
from app.parsing.processors.support.recovery import (
    audit_ingest_gate,
    indexed_checkpoint_is_reusable,
    parsed_checkpoint_is_reusable,
    record_ingest_gate_outcome,
    upsert_ingest_checkpoint,
)
from app.parsing.processors.support.recovery import (
    maybe_enrich_document_questions as _maybe_enrich_document_questions,
)
from app.parsing.processors.support.recovery import (
    run_post_completion_kg as _run_post_completion_kg,
)
from app.parsing.processors.support.results import ChunkAssetOptions, ChunkPostprocessStats, ParseResult
from app.parsing.processors.vlm_correction import apply_vlm_correction_async, should_apply_vlm_correction
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.reading_order import score_reading_order
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.parsing.routing import should_attempt_pdf_fallback
from app.rag.chunking.factory import chunker_factory
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.runtime import apply_governance_python_plugin
from app.rag.preprocessing.near_dedup import add_simhashes, find_near_duplicate, with_near_dedup_index
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.processor import GovernanceStats
from app.rag.preprocessing.simhash import simhash64, simhash64_hex
from app.services.metrics_logger import log_metrics as _log_metrics
from app.services.metrics_logger import metrics_span as _metrics_span
from app.services.metrics_logger import set_metrics_context
from app.services.pipeline_config import build_indexing_options as _build_indexing_options
from app.services.pipeline_config import resolve_pipeline_effective as _resolve_pipeline_effective
from app.types.pipeline import PipelineEffective

logger = get_logger("parsing.document_processor")
LOG_DOC_ID_FMT = "%s document_id=%s"
AUDIT_ACTION_DOCUMENT_QUARANTINE = "document.quarantine"


def _processor_override(name: str, default: Any) -> Any:
    processor_module = sys.modules.get("app.parsing.processors.processor")
    if processor_module is None:
        return default
    return getattr(processor_module, name, default)


def metrics_span(*args: Any, **kwargs: Any) -> Any:
    return _processor_override("metrics_span", _metrics_span)(*args, **kwargs)


def log_metrics(*args: Any, **kwargs: Any) -> Any:
    return _processor_override("log_metrics", _log_metrics)(*args, **kwargs)


def resolve_pipeline_effective(*args: Any, **kwargs: Any) -> Any:
    return _processor_override("resolve_pipeline_effective", _resolve_pipeline_effective)(*args, **kwargs)


def build_indexing_options(*args: Any, **kwargs: Any) -> Any:
    return _processor_override("build_indexing_options", _build_indexing_options)(*args, **kwargs)


def maybe_enrich_document_questions(*args: Any, **kwargs: Any) -> Any:
    return _processor_override("maybe_enrich_document_questions", _maybe_enrich_document_questions)(*args, **kwargs)


async def run_post_completion_kg(*args: Any, **kwargs: Any) -> Any:
    return await _processor_override("run_post_completion_kg", _run_post_completion_kg)(*args, **kwargs)


def record_stage_duration(stage_durations_ms: dict[str, int], stage: str, elapsed_ms: float) -> None:
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


def attach_stage_durations(stage_durations_ms: dict[str, int], meta: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(meta or {})
    if stage_durations_ms:
        out["ingest_stage_durations_ms"] = dict(stage_durations_ms)
    return out


async def raise_if_cancelled(cancel_check: Any, *, force: bool = False) -> None:
    if await cancel_check(force=force):
        from app.parsing.processors.support.results import DocumentCancelledError

        raise DocumentCancelledError("cancel_requested")


@dataclass
class PreparedProcessDocumentState:
    file_path: Path
    preprocessed_temp_path: Path | None
    dataset_id: str
    document_img_ids: set[str]
    artifact_dirs: set[str]
    pipeline_effective: PipelineEffective
    index_options: Any
    governance_kwargs: dict[str, Any]
    table_sidecar_tables_imported: int = 0
    table_sidecar_routing_audit: dict[str, Any] | None = None
    pdf_quality: dict[str, Any] | None = None


@dataclass
class ParseExecutionState:
    parsed: ParseResult
    resolved_backend: str
    resolved_chunk_strategy: str
    resumed_from_checkpoint: bool
    resumed_from_parse_cache: bool


def _build_combined_governance_rules(pipeline_effective: PipelineEffective):
    extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
    rule_packs = list(getattr(pipeline_effective, "governance_rule_packs", None) or [])
    from app.rag.preprocessing.rules import build_governance_rules

    return build_governance_rules(extra_rules, rule_packs=rule_packs) if (extra_rules or rule_packs) else None


def _commit_document_metadata(db: Session, db_document: DBDocument, metadata: dict[str, Any]) -> None:
    db_document.doc_metadata = metadata
    db.commit()
    db.refresh(db_document)


def _table_store_tables_payload(assets: Any) -> list[dict[str, Any]]:
    tables_payload: list[dict[str, Any]] = []
    for asset in assets or []:
        tables_payload.append(
            {
                "table_id": str(getattr(asset, "table_id", "")),
                "sheet_index": int(getattr(asset, "sheet_index", 0) or 0),
                "sheet_name": getattr(asset, "sheet_name", None),
                "row_count": int(getattr(asset, "row_count", 0) or 0),
                "col_count": int(getattr(asset, "col_count", 0) or 0),
                "truncated": bool(getattr(asset, "truncated", False)),
                "columns": list(getattr(asset, "columns", None) or []),
                "sample_rows": list(getattr(asset, "sample_rows", None) or []),
            }
        )
    return tables_payload


def _build_governance_kwargs(pipeline_effective: PipelineEffective) -> dict[str, Any]:
    combined_rules = _build_combined_governance_rules(pipeline_effective)
    return {
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


def _dataset_metadata(db: Session, *, db_document: DBDocument, tenant_id: UUID) -> dict[str, Any]:
    if not db_document.dataset_id:
        return {}
    ds = db.query(Dataset).filter(Dataset.id == db_document.dataset_id, Dataset.tenant_id == tenant_id).first()
    if ds is None or not isinstance(getattr(ds, "dataset_metadata", None), dict):
        return {}
    return dict(ds.dataset_metadata or {})


def _initialize_prepared_process_document_state(
    service: Any,
    db: Session,
    *,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
) -> PreparedProcessDocumentState:
    dataset_id = str(db_document.dataset_id) if db_document.dataset_id else str(tenant_id)
    set_metrics_context(tenant_id=tenant_id, document_id=document_id, dataset_id=dataset_id)
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=_dataset_metadata(db, db_document=db_document, tenant_id=tenant_id),
        document_metadata=(db_document.doc_metadata or {}),
        request_overrides=None,
    )
    index_options = build_indexing_options(pipeline_effective)
    service._record_pipeline_effective(db, tenant_id, document_id, pipeline_effective)
    return PreparedProcessDocumentState(
        file_path=Path(),
        preprocessed_temp_path=None,
        dataset_id=dataset_id,
        document_img_ids=set(),
        artifact_dirs=set(),
        pipeline_effective=pipeline_effective,
        index_options=index_options,
        governance_kwargs={},
    )


async def _resume_from_indexed_checkpoint(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
    prepared_state: PreparedProcessDocumentState,
    with_stage_durations: Any,
) -> dict[str, Any] | None:
    meta0 = dict(db_document.doc_metadata or {})
    if not indexed_checkpoint_is_reusable(meta0):
        return None
    checkpoint = dict(meta0.get("ingest_checkpoint") or {})
    doc_pipeline_key = str(
        checkpoint.get("doc_pipeline_key") or f"{document_id}:{str(meta0.get('pipeline_hash') or '').strip()}"
    ).strip()
    indexed_chunks_query = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id,
        DocumentChunk.tenant_id == tenant_id,
    )
    if doc_pipeline_key:
        indexed_chunks_query = indexed_chunks_query.filter(
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == doc_pipeline_key,  # type: ignore[attr-defined]
        )
    indexed_chunks = list(indexed_chunks_query.order_by(DocumentChunk.chunk_index, DocumentChunk.id).all())
    if not indexed_chunks:
        return None

    logger.info(
        "Resuming ingest finalization from indexed checkpoint: tenant=%s document=%s checkpoint=%s",
        tenant_id,
        document_id,
        doc_pipeline_key or "document",
    )
    resolved_backend = (
        str(meta0.get("parser_backend") or meta0.get("parser_backend_requested") or parser_backend or "auto").strip()
        or "auto"
    )
    resolved_chunk_strategy = (
        str(meta0.get("chunk_strategy") or meta0.get("chunk_strategy_requested") or chunk_strategy or "auto").strip()
        or "auto"
    )
    total_chars = int(
        checkpoint.get("total_characters")
        or meta0.get("indexed_total_characters")
        or sum(len(str(getattr(chunk, "content", "") or "")) for chunk in indexed_chunks)
    )
    meta_patch = dict(db_document.doc_metadata or {})
    meta_patch.pop("ingest_resume_required", None)
    meta_patch = with_stage_durations(meta_patch)
    await service._update_status(
        db,
        tenant_id,
        document_id,
        "completed",
        100,
        "completed",
        chunk_count=len(indexed_chunks),
        total_characters=total_chars,
        doc_metadata=meta_patch,
    )
    await run_post_completion_kg(
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_ids=[chunk.id for chunk in indexed_chunks],
        db_chunks=indexed_chunks,
        index_options=prepared_state.index_options,
        pipeline_effective=prepared_state.pipeline_effective,
    )
    return {
        "status": "success",
        "reason": "indexed_checkpoint_resume",
        "chunk_count": len(indexed_chunks),
        "total_characters": total_chars,
        "parser_backend": resolved_backend,
        "chunk_strategy": resolved_chunk_strategy,
    }


async def _run_pre_poc_quality_gate(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
    prepared_state: PreparedProcessDocumentState,
    add_stage_duration: Any,
    with_stage_durations: Any,
) -> dict[str, Any] | None:
    if not bool(getattr(prepared_state.pipeline_effective, "ingest_pre_poc_scanner_enabled", False)):
        return None
    try:
        from app.services.ingest_pre_poc_quality_gate import evaluate_ingest_pre_poc_quality_gate

        t0 = time.perf_counter()
        with metrics_span("ingest.pre_poc_quality_gate", file_ext=prepared_state.file_path.suffix.lower()):
            pre_poc_gate = evaluate_ingest_pre_poc_quality_gate(
                prepared_state.file_path,
                enabled=True,
                mode=str(
                    getattr(prepared_state.pipeline_effective, "ingest_pre_poc_quality_gate_mode", "warn") or "warn"
                ),
            )
        add_stage_duration("pre_poc_quality_gate", (time.perf_counter() - t0) * 1000)
        next_meta = dict(db_document.doc_metadata or {})
        next_meta["pre_poc_quality_gate"] = pre_poc_gate
        next_meta = apply_parse_quality_gate_metadata(next_meta)
        _commit_document_metadata(db, db_document, next_meta)
        if not bool(pre_poc_gate.get("blocked")):
            return None
        msg = "Document blocked by Pre-POC quality gate"
        await service._update_status(
            db,
            tenant_id,
            document_id,
            "failed",
            0,
            "failed",
            chunk_count=0,
            total_characters=0,
            error_message=msg,
            doc_metadata=with_stage_durations(next_meta),
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
        _log_processor_fallback("process_document", exc)
        if (
            str(
                getattr(prepared_state.pipeline_effective, "ingest_pre_poc_quality_gate_mode", "warn") or "warn"
            ).lower()
            == "strict"
        ):
            raise RuntimeError(f"pre_poc_quality_gate_failed: {str(exc)[:200]}") from exc
        return None


def _apply_document_preprocess(
    *,
    db: Session,
    db_document: DBDocument,
    file_path: Path,
    preprocessed_temp_path: Path | None,
    add_stage_duration: Any,
) -> tuple[Path, Path | None]:
    try:
        meta = db_document.doc_metadata or {}
        ingestion = meta.get("ingestion") if isinstance(meta, dict) else None
        preprocess_cfg = ingestion.get("preprocess") if isinstance(ingestion, dict) else None
        steps = preprocess_cfg.get("steps") if isinstance(preprocess_cfg, dict) else None
        if not isinstance(steps, list) or not steps:
            return file_path, preprocessed_temp_path
        t0 = time.perf_counter()
        with metrics_span("ingest.preprocess", file_ext=file_path.suffix.lower()):
            result = preprocess_file(input_path=file_path, steps=steps)
        add_stage_duration("preprocess", (time.perf_counter() - t0) * 1000)
        try:
            next_meta = dict(db_document.doc_metadata or {})
            next_meta["preprocess"] = result.to_dict()
            _commit_document_metadata(db, db_document, next_meta)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        if not bool(getattr(result, "changed", False)):
            return file_path, preprocessed_temp_path
        out_path = Path(str(getattr(result, "output_path", "") or "")).resolve(strict=False)
        return out_path, out_path
    except Exception as exc:  # noqa: BLE001
        _log_processor_fallback("process_document", exc)
        raise RuntimeError(f"preprocess_failed: {str(exc)[:200]}") from exc


def _apply_image_preprocess(
    *,
    db: Session,
    db_document: DBDocument,
    document_id: UUID,
    file_path: Path,
    preprocessed_temp_path: Path | None,
    add_stage_duration: Any,
) -> tuple[Path, Path | None, dict[str, Any] | None]:
    try:
        if not bool(getattr(settings, "IMAGE_PREPROCESS_ENABLED", False)):
            return file_path, preprocessed_temp_path, None
        ext = file_path.suffix.lower()
        if ext != ".pdf" and ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            return file_path, preprocessed_temp_path, None
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
                    try:
                        if isinstance(pdf_quality, dict) and pdf_quality.get("score") is not None:
                            next_meta = dict(db_document.doc_metadata or {})
                            next_meta["pdf_quality"] = pdf_quality
                            _commit_document_metadata(db, db_document, next_meta)
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                except Exception as exc:
                    _log_processor_fallback("process_document", exc)
                    pdf_quality = None
            result = preprocess_image_document(
                input_path=file_path,
                document_id=str(document_id) if document_id else None,
                pdf_quality=pdf_quality,
            )
        add_stage_duration("image_preprocess", (time.perf_counter() - t0) * 1000)
        try:
            next_meta = dict(db_document.doc_metadata or {})
            next_meta["image_preprocess"] = result.to_dict()
            _commit_document_metadata(db, db_document, next_meta)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        if bool(getattr(result, "changed", False)):
            out_path = Path(str(getattr(result, "output_path", "") or "")).resolve(strict=False)
            return out_path, out_path, pdf_quality if isinstance(pdf_quality, dict) else None
        return file_path, preprocessed_temp_path, pdf_quality if isinstance(pdf_quality, dict) else None
    except Exception as exc:  # noqa: BLE001
        _log_processor_fallback("process_document", exc)
        raise RuntimeError(f"image_preprocess_failed: {str(exc)[:200]}") from exc


async def _maybe_import_tabular_document(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    with_stage_durations: Any,
    raise_if_cancelled: Any,
    add_stage_duration: Any,
) -> dict[str, Any] | None:
    if not (
        bool(getattr(prepared_state.pipeline_effective, "table_store_enabled", False))
        and db_document.dataset_id is not None
        and prepared_state.file_path.suffix.lower() in {".csv", ".xls", ".xlsx"}
    ):
        return None

    table_decision = None
    try:
        from app.services.table_routing import decide_table_route

        table_decision = decide_table_route(
            file_path=prepared_state.file_path,
            auto_route=bool(getattr(prepared_state.pipeline_effective, "table_store_auto_route", False)),
            file_bytes_threshold=int(
                getattr(prepared_state.pipeline_effective, "table_store_auto_file_bytes_threshold", 0) or 0
            ),
            row_threshold=int(getattr(prepared_state.pipeline_effective, "table_store_auto_row_threshold", 0) or 0),
            col_threshold=int(getattr(prepared_state.pipeline_effective, "table_store_auto_col_threshold", 0) or 0),
            sheet_threshold=int(getattr(prepared_state.pipeline_effective, "table_store_auto_sheet_threshold", 0) or 0),
        )
    except Exception as exc:
        _log_processor_fallback("process_document", exc)

    if table_decision is not None:
        try:
            next_meta = dict(db_document.doc_metadata or {})
            next_meta["table_routing"] = {
                "version": "1",
                "route": getattr(table_decision, "route", None),
                "reason": getattr(table_decision, "reason", None),
                "stats": dict(getattr(table_decision, "stats", None) or {}),
            }
            _commit_document_metadata(db, db_document, next_meta)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    if table_decision is not None and str(getattr(table_decision, "route", "") or "").lower() == "rag":
        return None

    await raise_if_cancelled(force=True)
    await service._update_status(db, tenant_id, document_id, "processing", 15, "table_import")
    try:
        from app.services.table_store_service import import_table_document

        t0 = time.perf_counter()
        assets = import_table_document(
            tenant_id=tenant_id,
            dataset_id=db_document.dataset_id,
            document_id=document_id,
            file_path=prepared_state.file_path,
            max_rows=int(getattr(prepared_state.pipeline_effective, "table_store_max_rows", 0) or 0),
            max_cols=int(getattr(prepared_state.pipeline_effective, "table_store_max_cols", 0) or 0),
            sample_rows=int(getattr(prepared_state.pipeline_effective, "table_store_sample_rows", 0) or 0),
        )
        add_stage_duration("table_import", (time.perf_counter() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        msg = f"table_import_failed: {(str(exc) or exc.__class__.__name__)[:200]}"
        logger.warning("Table import failed: %s document_id=%s", msg, document_id)
        meta_patch = with_stage_durations(dict(db_document.doc_metadata or {}))
        await service._update_status(
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
    try:
        next_meta = dict(db_document.doc_metadata or {})
        next_meta["table_store"] = {
            "version": "1",
            "source_ext": prepared_state.file_path.suffix.lower(),
            "imported_at": dt.datetime.now(dt.UTC).isoformat(),
            "tables": _table_store_tables_payload(assets),
        }
        next_meta = apply_parse_quality_gate_metadata(next_meta)
        _commit_document_metadata(db, db_document, next_meta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist table_store metadata (ignored): %s", str(exc)[:200])

    await service._update_status(
        db,
        tenant_id,
        document_id,
        "completed",
        100,
        "completed",
        chunk_count=0,
        total_characters=0,
        error_message=None,
        doc_metadata=with_stage_durations(dict(db_document.doc_metadata or {})),
    )
    return {
        "status": "completed",
        "reason": "table_store",
        "chunk_count": 0,
        "total_characters": 0,
        "parser_backend": "table_store",
        "chunk_strategy": "none",
    }


async def _maybe_import_docx_table_sidecar(
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    raise_if_cancelled: Any,
) -> None:
    if not (
        bool(getattr(prepared_state.pipeline_effective, "table_store_enabled", False))
        and db_document.dataset_id is not None
        and prepared_state.file_path.suffix.lower() == ".docx"
    ):
        return
    await raise_if_cancelled(force=True)
    try:
        from app.services.table_store_service import import_docx_tables

        assets = import_docx_tables(
            tenant_id=tenant_id,
            dataset_id=db_document.dataset_id,
            document_id=document_id,
            file_path=prepared_state.file_path,
            max_rows=int(getattr(prepared_state.pipeline_effective, "table_store_max_rows", 0) or 0),
            max_cols=int(getattr(prepared_state.pipeline_effective, "table_store_max_cols", 0) or 0),
            sample_rows=int(getattr(prepared_state.pipeline_effective, "table_store_sample_rows", 0) or 0),
        )
        await raise_if_cancelled(force=True)
        try:
            next_meta = dict(db_document.doc_metadata or {})
            if assets:
                next_meta["table_store"] = {
                    "version": "1",
                    "source_ext": prepared_state.file_path.suffix.lower(),
                    "imported_at": dt.datetime.now(dt.UTC).isoformat(),
                    "tables": _table_store_tables_payload(assets),
                }
            else:
                next_meta.pop("table_store", None)
            next_meta = apply_parse_quality_gate_metadata(next_meta)
            if next_meta != (db_document.doc_metadata or {}):
                _commit_document_metadata(db, db_document, next_meta)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist DOCX table_store metadata (ignored): %s", str(exc)[:200])
    except Exception as exc:  # noqa: BLE001
        logger.info("DOCX table import failed (ignored): %s document_id=%s", str(exc)[:200], document_id)


async def prepare_process_document_pipeline(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
    file_path: Path,
    add_stage_duration: Any,
    with_stage_durations: Any,
    raise_if_cancelled: Any,
) -> dict[str, Any]:
    prepared_state = _initialize_prepared_process_document_state(
        service,
        db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
    )
    prepared_state.file_path = file_path

    early_result = await _resume_from_indexed_checkpoint(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        prepared_state=prepared_state,
        with_stage_durations=with_stage_durations,
    )
    if early_result is not None:
        return {"state": prepared_state, "result": early_result}

    prepared_state.governance_kwargs = _build_governance_kwargs(prepared_state.pipeline_effective)

    early_result = await _run_pre_poc_quality_gate(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        prepared_state=prepared_state,
        add_stage_duration=add_stage_duration,
        with_stage_durations=with_stage_durations,
    )
    if early_result is not None:
        return {"state": prepared_state, "result": early_result}

    prepared_state.file_path, prepared_state.preprocessed_temp_path = _apply_document_preprocess(
        db=db,
        db_document=db_document,
        file_path=prepared_state.file_path,
        preprocessed_temp_path=prepared_state.preprocessed_temp_path,
        add_stage_duration=add_stage_duration,
    )
    (
        prepared_state.file_path,
        prepared_state.preprocessed_temp_path,
        prepared_state.pdf_quality,
    ) = _apply_image_preprocess(
        db=db,
        db_document=db_document,
        document_id=document_id,
        file_path=prepared_state.file_path,
        preprocessed_temp_path=prepared_state.preprocessed_temp_path,
        add_stage_duration=add_stage_duration,
    )

    early_result = await _maybe_import_tabular_document(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        with_stage_durations=with_stage_durations,
        raise_if_cancelled=raise_if_cancelled,
        add_stage_duration=add_stage_duration,
    )
    if early_result is not None:
        return {"state": prepared_state, "result": early_result}

    await _maybe_import_docx_table_sidecar(
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        raise_if_cancelled=raise_if_cancelled,
    )
    return {"state": prepared_state, "result": None}


def _resume_parse_result_from_checkpoint(
    db: Session,
    *,
    db_document: DBDocument,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> ParseResult | None:
    try:
        meta0 = dict(db_document.doc_metadata or {})
        checkpoint = meta0.get("ingest_checkpoint") if isinstance(meta0, dict) else None
        if not parsed_checkpoint_is_reusable(meta0):
            return None
        pipeline_hash0 = str(meta0.get("pipeline_hash") or "").strip()
        file_sha0 = str(meta0.get("file_sha256") or "").strip().lower()
        checkpoint_pipeline = str((checkpoint or {}).get("pipeline_hash") or "").strip()
        checkpoint_sha = str((checkpoint or {}).get("file_sha256") or "").strip().lower()
        if (pipeline_hash0 and checkpoint_pipeline != pipeline_hash0) or (
            file_sha0 and checkpoint_sha and checkpoint_sha != file_sha0
        ):
            return None
        rec = (
            db.query(DocumentParsedContent)
            .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
            .first()
        )
        cleaned_md = str(getattr(rec, "markdown_content", "") or "").strip() if rec is not None else ""
        if not cleaned_md:
            return None
        original_md = str(getattr(rec, "original_markdown_content", "") or "").strip() if rec is not None else ""
        logger.info(
            "Resuming ingest from parsed checkpoint: tenant=%s document=%s pipeline_hash=%s",
            tenant_id,
            document_id,
            pipeline_hash0[:16] if pipeline_hash0 else "",
        )
        resume_meta: dict[str, Any] = {"page": 1}
        if original_md and original_md != cleaned_md:
            resume_meta["position_tagged_markdown"] = original_md
        return ParseResult(
            resolved_backend=(
                str(
                    meta0.get("parser_backend") or meta0.get("parser_backend_requested") or parser_backend or "auto"
                ).strip()
                or "auto"
            ),
            resolved_chunk_strategy=chunker_factory.resolve_strategy(chunk_strategy),
            documents=[Document(page_content=cleaned_md, metadata=resume_meta)],
        )
    except Exception as exc:
        _log_processor_fallback("process_document", exc)
        return None


def _resume_parse_result_from_cache(
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
    pipeline_effective: PipelineEffective,
) -> tuple[ParseResult | None, LocalParseCacheStore | None, str | None]:
    try:
        meta0 = dict(db_document.doc_metadata or {})
        file_sha0 = str(meta0.get("file_sha256") or "").strip().lower()
        pipeline_hash0 = str(meta0.get("pipeline_hash") or "").strip()
        parser_backend_key = str(parser_backend or "").strip().lower() or "auto"
        if not (bool(getattr(pipeline_effective, "parse_cache_enabled", False)) and file_sha0 and pipeline_hash0):
            return None, None, None
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
        if cached_entry is None or (cached_entry.documents is None and cached_entry.chunks is None):
            return None, parse_cache_store, parse_cache_key
        parsed = ParseResult(
            resolved_backend=str(cached_entry.resolved_backend or parser_backend_key),
            resolved_chunk_strategy=str(
                cached_entry.resolved_chunk_strategy or chunker_factory.resolve_strategy(chunk_strategy)
            ),
            documents=_deserialize_documents_from_parse_cache(cached_entry.documents),
            chunks=_deserialize_documents_from_parse_cache(cached_entry.chunks),
        )
        meta_hit = dict(db_document.doc_metadata or {})
        meta_hit["parse_cache"] = {
            "enabled": True,
            "hit": True,
            "age_ms": int(cached_age_ms or 0),
            "ttl_sec": int(getattr(pipeline_effective, "parse_cache_ttl_sec", 0) or 0),
        }
        _commit_document_metadata(db, db_document, meta_hit)
        return parsed, parse_cache_store, parse_cache_key
    except Exception as exc:
        _log_processor_fallback("process_document", exc)
        return None, None, None


def _parse_stage_otel_attributes(
    *,
    db_document: DBDocument,
    file_path: Path,
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> dict[str, Any]:
    return {
        "ingest.stage": "parse",
        "document.file_type": str(file_path.suffix.lstrip(".") or "unknown").lower(),
        "parser.backend_requested": (
            str(
                (db_document.doc_metadata or {}).get("parser_backend_requested")
                or (db_document.doc_metadata or {}).get("parser_backend")
                or parser_backend
                or "auto"
            )
            .strip()
            .lower()
            or "auto"
        ),
        "chunk.strategy_requested": (
            str(
                (db_document.doc_metadata or {}).get("chunk_strategy_requested")
                or (db_document.doc_metadata or {}).get("chunk_strategy")
                or chunk_strategy
                or ""
            )
            .strip()
            .lower()
            or "default"
        ),
    }


async def _run_parse_stage(
    parsing_stage: Any,
    *,
    db: Session,
    db_document: DBDocument,
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    dataset_id: str,
    parser_backend: str | None,
    chunk_strategy: str | None,
    pipeline_effective: PipelineEffective,
) -> tuple[ParseResult, float]:
    with metrics_span(
        "ingest.parse",
        parser_backend_requested=parser_backend,
        chunk_strategy_requested=chunk_strategy,
        otel_span_name="ingest.parse",
        otel_attributes=_parse_stage_otel_attributes(
            db_document=db_document,
            file_path=file_path,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
        ),
    ):
        started_at = time.perf_counter()
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
                pipeline_effective.governance_html_xpath if file_path.suffix.lower() in {".html", ".htm"} else None
            ),
        )
    return parsed, started_at


def _parsed_joined_text(documents: list[Document] | None) -> str:
    return "\n\n".join([(doc.page_content or "") for doc in (documents or [])])


def _magicpdf_available() -> bool:
    if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
        return False
    from app.parsing.parsers.magic_pdf_parser import magicpdf_service_configured, resolve_magicpdf_models_dir
    from app.parsing.utils.cli import resolve_cli_command

    if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
        return True
    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    return bool(resolve_cli_command(cli) and resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", "")))


def _parse_fallback_candidates(*, current_backend: str) -> list[str]:
    candidates: list[str] = []
    candidate_checks = (
        (
            "mineru",
            lambda: settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL),
        ),
        (
            "deepseek_ocr",
            lambda: (
                bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
                and bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
            ),
        ),
        (
            "qianfan_ocr",
            lambda: (
                bool(getattr(settings, "QIANFAN_OCR_ENABLED", False))
                and bool((getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip())
            ),
        ),
        (
            "etl4llm",
            lambda: (
                bool(getattr(settings, "ETL4LLM_ENABLED", False))
                and bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
            ),
        ),
        ("deepdoc", lambda: settings.DEEPDOC_ENABLED),
        ("docling", lambda: getattr(settings, "DOCLING_ENABLED", False)),
        ("magicpdf", _magicpdf_available),
        ("markitdown", lambda: settings.MARKITDOWN_ENABLED),
        ("basic", lambda: True),
    )
    for candidate, enabled in candidate_checks:
        if enabled():
            candidates.append(candidate)
    filtered: list[str] = []
    for candidate in candidates:
        candidate_norm = (candidate or "").strip().lower()
        if not candidate_norm or candidate_norm == current_backend or candidate_norm in filtered:
            continue
        filtered.append(candidate_norm)
    return filtered


async def begin_process_document(
    service: Any,
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    raise_if_cancelled: Any,
) -> tuple[DBDocument | None, dict[str, Any] | None]:
    db_document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if db_document is None:
        logger.warning("Document not found for processing: tenant=%s document=%s", tenant_id, document_id)
        return None, {"status": "skipped", "reason": "document_not_found"}

    await raise_if_cancelled(force=True)
    retry_cleanup_status = service._apply_pending_retry_cleanup(
        db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
    )
    if retry_cleanup_status == "invalid":
        await service._update_status(
            db,
            tenant_id,
            document_id,
            "failed",
            0,
            "failed",
            error_message="invalid_retry_cleanup_intent",
        )
        return db_document, {"status": "failed", "reason": "invalid_retry_cleanup_intent"}
    if retry_cleanup_status == "deferred":
        await service._update_status(
            db,
            tenant_id,
            document_id,
            "failed",
            0,
            "failed",
            error_message="retry_cleanup_deferred",
        )
        return db_document, {"status": "failed", "reason": "retry_cleanup_deferred"}

    await service._update_status(db, tenant_id, document_id, "processing", 0, "parsing")
    return db_document, None


async def handle_document_cancelled(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    error: Exception,
    with_stage_durations: Any,
) -> dict[str, Any]:
    logger.info("Document processing cancelled: tenant=%s document=%s (%s)", tenant_id, document_id, str(error)[:120])
    service._rollback_and_cleanup_indexes(db, db_document=db_document, tenant_id=tenant_id, document_id=document_id)
    await service._update_status(
        db,
        tenant_id,
        document_id,
        "cancelled",
        0,
        "cancelled",
        error_message="cancelled",
        doc_metadata=with_stage_durations(dict(getattr(db_document, "doc_metadata", None) or {})),
    )
    return {"status": "cancelled"}


async def handle_asyncio_cancelled(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    with_stage_durations: Any,
) -> None:
    service._rollback_and_cleanup_indexes(db, db_document=db_document, tenant_id=tenant_id, document_id=document_id)
    try:
        await asyncio.shield(
            service._update_status(
                db,
                tenant_id,
                document_id,
                "cancelled",
                0,
                "cancelled",
                error_message="cancelled",
                doc_metadata=with_stage_durations(dict(getattr(db_document, "doc_metadata", None) or {})),
            )
        )
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


def handle_retry_boundary_failure(*, tenant_id: UUID, document_id: UUID, error: Exception) -> dict[str, Any]:
    logger.warning(
        "Document finalization deferred to retry boundary: tenant=%s document=%s reason=%s",
        tenant_id,
        document_id,
        str(error)[:160],
    )
    log_metrics(
        {
            "event": "ingest.retry_boundary",
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "reason": str(error)[:160],
        }
    )
    return {"status": "failed", "reason": str(error)}


async def handle_tenant_quota_exceeded(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    error: Exception,
    with_stage_durations: Any,
    resolved_backend: str | None,
    resolved_chunk_strategy: str | None,
) -> dict[str, Any]:
    quota_key = str(getattr(error, "quota", "") or "").strip() or "quota"
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
        "meta": dict(getattr(error, "meta", None) or {}),
    }
    meta_patch = record_ingest_gate_outcome(
        with_stage_durations(meta_patch),
        gate="tenant_quota",
        outcome="closed",
        reason=f"tenant_quota_exceeded:{quota_key}",
        details=dict(getattr(error, "meta", None) or {}),
    )

    from app.core.pipeline_versions import should_preserve_existing_versions

    update_kwargs: dict[str, Any] = {
        "error_message": str(error)[:300],
        "doc_metadata": meta_patch,
    }
    if not should_preserve_existing_versions(meta_patch):
        update_kwargs["chunk_count"] = 0
        update_kwargs["total_characters"] = 0
    await service._update_status(
        db,
        tenant_id,
        document_id,
        "failed",
        0,
        "failed",
        **update_kwargs,
    )
    audit_ingest_gate(
        db,
        tenant_id=tenant_id,
        db_document=db_document,
        gate="tenant_quota",
        outcome="closed",
        reason=f"tenant_quota_exceeded:{quota_key}",
        details=dict(getattr(error, "meta", None) or {}),
    )
    return {
        "status": "failed",
        "reason": f"tenant_quota_exceeded:{quota_key}",
        "chunk_count": 0,
        "total_characters": 0,
        "parser_backend": resolved_backend,
        "chunk_strategy": resolved_chunk_strategy,
    }


async def handle_process_document_failure(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    error: Exception,
    with_stage_durations: Any,
) -> None:
    logger.exception("Error processing document %s: %s", document_id, error)
    log_metrics({"event": "ingest.failed", "success": False, "error": str(error)[:200]})
    service._rollback_and_cleanup_indexes(db, db_document=db_document, tenant_id=tenant_id, document_id=document_id)
    await service._update_status(
        db,
        tenant_id,
        document_id,
        "failed",
        0,
        "failed",
        error_message=str(error),
        doc_metadata=with_stage_durations(dict(getattr(db_document, "doc_metadata", None) or {})),
    )


async def run_process_document_body(
    service: Any,
    *,
    db: Session,
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
    runtime_state: dict[str, Any],
    parsing_stage_factory: Any,
    inline_asset_stage_factory: Any,
    normalize_stage_factory: Any,
    governance_stage_factory: Any,
    chunking_stage_factory: Any,
    chunk_dedup_stage_factory: Any,
    chunk_asset_stage_factory: Any,
    index_stage_factory: Any,
) -> dict[str, Any]:
    cancel_check = service._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)
    stage_durations_ms: dict[str, int] = {}
    add_stage_duration = partial(record_stage_duration, stage_durations_ms)
    with_stage_durations = partial(attach_stage_durations, stage_durations_ms)
    raise_if_cancelled_cb = partial(raise_if_cancelled, cancel_check)
    runtime_state["with_stage_durations"] = with_stage_durations

    db_document, early_result = await begin_process_document(
        service,
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        raise_if_cancelled=raise_if_cancelled_cb,
    )
    runtime_state["db_document"] = db_document
    if early_result is not None:
        return early_result
    if db_document is None:
        return {"status": "skipped", "reason": "document_not_found"}

    prepared = await prepare_process_document_pipeline(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        file_path=file_path,
        add_stage_duration=add_stage_duration,
        with_stage_durations=with_stage_durations,
        raise_if_cancelled=raise_if_cancelled_cb,
    )
    prepared_state = prepared["state"]
    runtime_state["preprocessed_temp_path"] = prepared_state.preprocessed_temp_path
    early_result = prepared.get("result")
    if early_result is not None:
        return early_result

    parsing_stage = parsing_stage_factory(service)
    parse_result = await execute_parse_pipeline(
        service,
        parsing_stage,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        prepared_state=prepared_state,
        add_stage_duration=add_stage_duration,
        with_stage_durations=with_stage_durations,
        raise_if_cancelled=raise_if_cancelled_cb,
    )
    early_result = parse_result["result"]
    runtime_state["parse_state"] = parse_result["state"]
    if early_result is not None:
        return early_result

    return await continue_process_document_flow(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        parse_state=parse_result["state"],
        inline_asset_stage=inline_asset_stage_factory(service),
        normalize_stage=normalize_stage_factory(),
        governance_stage=governance_stage_factory(),
        chunking_stage=chunking_stage_factory(),
        chunk_dedup_stage=chunk_dedup_stage_factory(),
        chunk_asset_stage=chunk_asset_stage_factory(service),
        index_stage=index_stage_factory(),
        add_stage_duration=add_stage_duration,
        with_stage_durations=with_stage_durations,
        raise_if_cancelled=raise_if_cancelled_cb,
    )


async def _attempt_parse_fallback_candidates(
    parsing_stage: Any,
    *,
    db: Session,
    db_document: DBDocument,
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    dataset_id: str,
    chunk_strategy: str | None,
    q0: Any,
    pdf_quality: dict[str, Any] | None,
    min_chars: int,
    min_parse_score: float,
    max_retries: int,
    current_backend: str,
) -> tuple[ParseResult | None, list[dict[str, object]]]:
    attempts: list[dict[str, object]] = []
    accepted_parse: ParseResult | None = None
    retries_left = max_retries
    for candidate in _parse_fallback_candidates(current_backend=current_backend):
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
            _log_processor_fallback("process_document", exc)
            attempts.append(
                {
                    "from": current_backend,
                    "to": candidate,
                    "quality_before": q0.to_dict(),
                    "error": str(exc)[:200],
                    "accepted": False,
                }
            )
            continue
        if alt.documents is None:
            continue
        joined_alt = _parsed_joined_text(alt.documents)
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
                "from": current_backend,
                "to": candidate,
                "quality_before": q0.to_dict(),
                "quality_after": q1.to_dict(),
                "accepted": bool(accepted),
            }
        )
        if accepted:
            accepted_parse = alt
            break
    return accepted_parse, attempts


async def _maybe_apply_parse_fallback(
    parsing_stage: Any,
    *,
    db: Session,
    db_document: DBDocument,
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    dataset_id: str,
    parser_backend: str | None,
    chunk_strategy: str | None,
    pipeline_effective: PipelineEffective,
    parsed: ParseResult,
    resumed_from_checkpoint: bool,
    resumed_from_parse_cache: bool,
    pdf_quality: dict[str, Any] | None,
) -> ParseResult:
    if not (
        bool(getattr(pipeline_effective, "parse_fallback_enabled", False))
        and file_path.suffix.lower() == ".pdf"
        and (str(parser_backend or "").strip().lower() in {"", "auto"})
        and (not resumed_from_checkpoint)
        and (not resumed_from_parse_cache)
        and parsed.documents is not None
    ):
        return parsed
    try:
        min_chars = max(0, int(getattr(pipeline_effective, "parse_fallback_min_content_chars", 0) or 0))
        min_parse_score = max(0.0, float(getattr(pipeline_effective, "parse_fallback_min_parse_score", 0.0) or 0.0))
        max_retries = max(0, int(getattr(pipeline_effective, "parse_fallback_max_retries", 0) or 0))
        if (min_chars <= 0 and min_parse_score <= 0.0) or max_retries <= 0:
            return parsed
        joined = _parsed_joined_text(parsed.documents)
        q0 = score_parsed_text_quality(joined)
        q0_quality = score_document_parse_quality(
            pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
            parsed_text_quality=q0.to_dict(),
        )
        q0_score = float(q0_quality.get("score") or 0.0)
        q0_chars = int(getattr(q0, "content_chars", 0) or 0)
        if not should_attempt_pdf_fallback(
            grade="fail" if q0_chars <= 0 else "warn",
            parse_score=q0_score,
            content_chars=q0_chars,
            min_content_chars=min_chars,
            min_parse_score=min_parse_score,
        ):
            return parsed
        accepted_parse, attempts = await _attempt_parse_fallback_candidates(
            parsing_stage,
            db=db,
            db_document=db_document,
            file_path=file_path,
            document_id=document_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            chunk_strategy=chunk_strategy,
            q0=q0,
            pdf_quality=pdf_quality,
            min_chars=min_chars,
            min_parse_score=min_parse_score,
            max_retries=max_retries,
            current_backend=str(parsed.resolved_backend or "").strip().lower(),
        )
        if attempts:
            meta = dict(db_document.doc_metadata or {})
            meta["parse_fallback"] = {
                "enabled": True,
                "attempts": attempts,
                "min_content_chars": int(min_chars),
                "max_retries": int(max_retries),
            }
            _commit_document_metadata(db, db_document, meta)
        return accepted_parse or parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Parse fallback failed (ignored): %s", str(exc)[:200])
        return parsed


def _attach_logical_source_metadata_to_parsed_result(
    parsed: ParseResult,
    *,
    db_document: DBDocument,
    file_path: Path,
) -> ParseResult:
    return ParseResult(
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


def _persist_parse_cache_entry(
    *,
    db: Session,
    db_document: DBDocument,
    parser_backend: str | None,
    pipeline_effective: PipelineEffective,
    parse_cache_store: LocalParseCacheStore | None,
    parse_cache_key: str | None,
    parsed: ParseResult,
    resolved_backend: str,
    resolved_chunk_strategy: str,
    resumed_from_checkpoint: bool,
    resumed_from_parse_cache: bool,
) -> None:
    if resumed_from_checkpoint or resumed_from_parse_cache or parse_cache_store is None or not parse_cache_key:
        return
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
        _commit_document_metadata(db, db_document, meta_cached)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Persisted parse cache write failed (ignored): %s", str(exc)[:200])


async def _maybe_apply_parse_quality_gate(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    parser_backend: str | None,
    pipeline_effective: PipelineEffective,
    parsed: ParseResult,
    resumed_from_checkpoint: bool,
    resumed_from_parse_cache: bool,
    resolved_backend: str,
    resolved_chunk_strategy: str,
    with_stage_durations: Any,
    pdf_quality: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not (
        bool(getattr(pipeline_effective, "parse_fallback_enabled", False))
        and db_document.file_type == "pdf"
        and (str(parser_backend or "").strip().lower() in {"", "auto"})
        and (not resumed_from_checkpoint)
        and (not resumed_from_parse_cache)
        and parsed.documents is not None
    ):
        return None
    try:
        min_chars = max(0, int(getattr(pipeline_effective, "parse_fallback_min_content_chars", 0) or 0))
        min_parse_score = max(0.0, float(getattr(pipeline_effective, "parse_fallback_min_parse_score", 0.0) or 0.0))
        if min_chars <= 0 and min_parse_score <= 0.0:
            return None
        joined_final = _parsed_joined_text(parsed.documents)
        q_final = score_parsed_text_quality(joined_final)
        final_chars = int(getattr(q_final, "content_chars", 0) or 0)
        meta = dict(db_document.doc_metadata or {})
        attempted = bool(meta.get("parse_fallback"))
        specialty_signals = _seal_summary_to_specialty_signals(
            meta.get("seal_summary") if isinstance(meta.get("seal_summary"), dict) else None
        )
        if attempted or final_chars < min_chars:
            meta["parsed_text_quality"] = q_final.to_dict()
            with contextlib.suppress(Exception):
                meta["parse_quality"] = score_document_parse_quality(
                    pdf_quality=(meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None),
                    parsed_text_quality=(
                        meta.get("parsed_text_quality") if isinstance(meta.get("parsed_text_quality"), dict) else None
                    ),
                    specialty_signals=specialty_signals,
                )
            meta = apply_parse_quality_gate_metadata(meta)
            _commit_document_metadata(db, db_document, meta)

        final_quality = score_document_parse_quality(
            pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
            parsed_text_quality=q_final.to_dict(),
            specialty_signals=specialty_signals,
        )
        final_score = float(final_quality.get("score") or 0.0)
        if not should_attempt_pdf_fallback(
            grade="warn",
            parse_score=final_score,
            content_chars=final_chars,
            min_content_chars=min_chars,
            min_parse_score=min_parse_score,
        ):
            return None
        quarantined = bool(getattr(pipeline_effective, "governance_quarantine_on_drop", False))
        status = "quarantined" if quarantined else "failed"
        reason = "quarantined_by_parse_quality" if quarantined else "dropped_by_parse_quality"
        msg = (
            f"Document {'quarantined' if quarantined else 'failed'} by parse quality gate "
            f"(content_chars={final_chars}, parse_score={round(final_score, 3)}). "
            "Consider enabling OCR/backends or lowering parse fallback thresholds."
        )
        logger.warning(LOG_DOC_ID_FMT, msg, document_id)
        meta_patch = record_ingest_gate_outcome(
            with_stage_durations(dict(db_document.doc_metadata or {})),
            gate="parse_quality",
            outcome=("quarantine" if quarantined else "closed"),
            reason=reason,
            details={
                "parser_backend": str(resolved_backend or ""),
                "parsed_content_chars": int(final_chars),
                "parse_score": round(float(final_score), 3),
            },
        )

        from app.core.pipeline_versions import should_preserve_existing_versions

        update_kwargs: dict[str, Any] = {"error_message": msg, "doc_metadata": meta_patch}
        if not should_preserve_existing_versions(meta_patch):
            update_kwargs["chunk_count"] = 0
            update_kwargs["total_characters"] = 0
        await service._update_status(db, tenant_id, document_id, status, 0, status, **update_kwargs)
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
        degraded_meta = record_ingest_gate_outcome(
            with_stage_durations(dict(db_document.doc_metadata or {})),
            gate="parse_quality",
            outcome="degraded",
            reason="parse_quality_gate_failed",
            details={"error": str(exc)[:200]},
        )
        _commit_document_metadata(db, db_document, degraded_meta)
        audit_ingest_gate(
            db,
            tenant_id=tenant_id,
            db_document=db_document,
            gate="parse_quality",
            outcome="degraded",
            reason="parse_quality_gate_failed",
            details={"error": str(exc)[:200]},
        )
        logger.warning("Parse quality gate degraded: %s", str(exc)[:200])
        return None


async def execute_parse_pipeline(
    service: Any,
    parsing_stage: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
    prepared_state: PreparedProcessDocumentState,
    add_stage_duration: Any,
    with_stage_durations: Any,
    raise_if_cancelled: Any,
) -> dict[str, Any]:
    resumed_from_checkpoint = False
    resumed_from_parse_cache = False
    parse_cache_store: LocalParseCacheStore | None = None
    parse_cache_key: str | None = None
    parsed = _resume_parse_result_from_checkpoint(
        db,
        db_document=db_document,
        document_id=document_id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
    )
    if parsed is not None:
        resumed_from_checkpoint = True
    else:
        parsed, parse_cache_store, parse_cache_key = _resume_parse_result_from_cache(
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            pipeline_effective=prepared_state.pipeline_effective,
        )
        resumed_from_parse_cache = parsed is not None

    parse_started_at = 0.0
    if parsed is None:
        parsed, parse_started_at = await _run_parse_stage(
            parsing_stage,
            db=db,
            db_document=db_document,
            file_path=prepared_state.file_path,
            document_id=document_id,
            tenant_id=tenant_id,
            dataset_id=prepared_state.dataset_id,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            pipeline_effective=prepared_state.pipeline_effective,
        )
        await raise_if_cancelled(force=True)

    parsed = await _maybe_apply_parse_fallback(
        parsing_stage,
        db=db,
        db_document=db_document,
        file_path=prepared_state.file_path,
        document_id=document_id,
        tenant_id=tenant_id,
        dataset_id=prepared_state.dataset_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        pipeline_effective=prepared_state.pipeline_effective,
        parsed=parsed,
        resumed_from_checkpoint=resumed_from_checkpoint,
        resumed_from_parse_cache=resumed_from_parse_cache,
        pdf_quality=prepared_state.pdf_quality,
    )

    if resumed_from_checkpoint:
        meta0 = dict(db_document.doc_metadata or {})
        resolved_backend = (
            str(
                meta0.get("parser_backend") or meta0.get("parser_backend_requested") or parser_backend or "auto"
            ).strip()
            or "auto"
        )
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    else:
        if not resumed_from_parse_cache:
            add_stage_duration("parse", (time.perf_counter() - parse_started_at) * 1000)
        resolved_backend = parsed.resolved_backend
        resolved_chunk_strategy = parsed.resolved_chunk_strategy

    parsed = _attach_logical_source_metadata_to_parsed_result(
        parsed,
        db_document=db_document,
        file_path=prepared_state.file_path,
    )
    _persist_parse_cache_entry(
        db=db,
        db_document=db_document,
        parser_backend=parser_backend,
        pipeline_effective=prepared_state.pipeline_effective,
        parse_cache_store=parse_cache_store,
        parse_cache_key=parse_cache_key,
        parsed=parsed,
        resolved_backend=resolved_backend,
        resolved_chunk_strategy=resolved_chunk_strategy,
        resumed_from_checkpoint=resumed_from_checkpoint,
        resumed_from_parse_cache=resumed_from_parse_cache,
    )
    early_result = await _maybe_apply_parse_quality_gate(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        parser_backend=parser_backend,
        pipeline_effective=prepared_state.pipeline_effective,
        parsed=parsed,
        resumed_from_checkpoint=resumed_from_checkpoint,
        resumed_from_parse_cache=resumed_from_parse_cache,
        resolved_backend=resolved_backend,
        resolved_chunk_strategy=resolved_chunk_strategy,
        with_stage_durations=with_stage_durations,
        pdf_quality=prepared_state.pdf_quality,
    )
    return {
        "state": ParseExecutionState(
            parsed=parsed,
            resolved_backend=resolved_backend,
            resolved_chunk_strategy=resolved_chunk_strategy,
            resumed_from_checkpoint=resumed_from_checkpoint,
            resumed_from_parse_cache=resumed_from_parse_cache,
        ),
        "result": early_result,
    }


def _is_pdf_document(file_path: Path) -> bool:
    return file_path.suffix.lower() == ".pdf"


def _maybe_merge_cross_page_parsed_documents(
    parsed_documents: list[Document] | None,
    *,
    pipeline_effective: PipelineEffective,
    add_stage_duration: Any,
) -> list[Document] | None:
    if not parsed_documents or not bool(getattr(pipeline_effective, "cross_page_merge_enabled", False)):
        return parsed_documents
    t0 = time.perf_counter()
    with metrics_span("ingest.cross_page_merge"):
        merged_documents = merge_cross_page_documents(
            parsed_documents,
            max_page_gap=int(getattr(pipeline_effective, "cross_page_merge_max_page_gap", 1) or 1),
        )
    add_stage_duration("cross_page_merge", (time.perf_counter() - t0) * 1000)
    return merged_documents


def _maybe_record_pdf_reading_order(
    *,
    db: Session,
    db_document: DBDocument,
    file_path: Path,
    parsed: ParseResult,
    parsed_documents: list[Document] | None,
) -> None:
    if parsed.chunks is None or not parsed_documents or not _is_pdf_document(file_path):
        return
    try:
        joined_for_ro = "\n\n".join([(d.page_content or "") for d in parsed_documents])
        meta_patch = dict(db_document.doc_metadata or {})
        meta_patch["reading_order"] = score_reading_order(joined_for_ro)
        _commit_document_metadata(db, db_document, meta_patch)
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


async def _maybe_apply_vlm_correction_to_documents(
    *,
    db: Session,
    db_document: DBDocument,
    parsed_documents: list[Document] | None,
    prepared_state: PreparedProcessDocumentState,
    pipeline_effective: PipelineEffective,
    add_stage_duration: Any,
) -> list[Document] | None:
    if not parsed_documents or not _is_pdf_document(prepared_state.file_path):
        return parsed_documents
    if not should_apply_vlm_correction(
        enabled=bool(getattr(pipeline_effective, "vlm_correction_enabled", False)),
        pdf_quality=prepared_state.pdf_quality,
        min_table_score=float(getattr(pipeline_effective, "vlm_correction_min_table_score", 0.6) or 0.6),
    ):
        return parsed_documents
    t0 = time.perf_counter()
    with metrics_span("ingest.vlm_correction"):
        corrected_docs, correction_meta = await apply_vlm_correction_async(
            documents=parsed_documents,
            file_path=prepared_state.file_path,
            max_pages=int(getattr(pipeline_effective, "vlm_correction_max_pages", 2) or 2),
        )
    add_stage_duration("vlm_correction", (time.perf_counter() - t0) * 1000)
    if bool(correction_meta.get("applied")):
        meta_vlm = dict(db_document.doc_metadata or {})
        meta_vlm["vlm_correction"] = correction_meta
        _commit_document_metadata(db, db_document, meta_vlm)
    return corrected_docs


def _maybe_import_pdf_table_sidecars(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    parsed_documents: list[Document] | None,
    prepared_state: PreparedProcessDocumentState,
    pipeline_effective: PipelineEffective,
) -> int:
    if not parsed_documents or not _is_pdf_document(prepared_state.file_path):
        return prepared_state.table_sidecar_tables_imported
    return service._import_parsed_markdown_tables_to_store(
        db,
        db_document=db_document,
        tenant_id=tenant_id,
        documents=parsed_documents,
        pipeline_effective=pipeline_effective,
    )


async def _prepare_parsed_documents_for_continuation(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    parse_state: ParseExecutionState,
    inline_asset_stage: Any,
    add_stage_duration: Any,
    raise_if_cancelled: Any,
) -> tuple[list[Document] | None, int]:
    parsed = parse_state.parsed
    pipeline_effective = prepared_state.pipeline_effective
    document_img_ids = prepared_state.document_img_ids
    artifact_dirs = prepared_state.artifact_dirs
    _collect_parser_asset_refs(parsed, document_img_ids=document_img_ids, artifact_dirs=artifact_dirs)

    parsed_documents: list[Document] | None = None
    if parsed.documents:
        t0 = time.perf_counter()
        with metrics_span("ingest.inline_assets"):
            inline_result = inline_asset_stage.run(
                documents=parsed.documents,
                tenant_id=tenant_id,
                dataset_id=prepared_state.dataset_id,
                document_id=document_id,
                origin_path=prepared_state.file_path,
                start_index=0,
                image_caption_enabled=bool(getattr(pipeline_effective, "image_caption_enabled", False)),
            )
        add_stage_duration("inline_assets", (time.perf_counter() - t0) * 1000)
        parsed_documents = inline_result.documents
        for iid in inline_result.uploaded_img_ids:
            if isinstance(iid, str) and iid.strip():
                document_img_ids.add(iid)
        _apply_inline_asset_audit_patch(db, db_document, inline_result)

    parsed_documents = _maybe_merge_cross_page_parsed_documents(
        parsed_documents,
        pipeline_effective=pipeline_effective,
        add_stage_duration=add_stage_duration,
    )
    _maybe_record_pdf_reading_order(
        db=db,
        db_document=db_document,
        file_path=prepared_state.file_path,
        parsed=parse_state.parsed,
        parsed_documents=parsed_documents,
    )
    parsed_documents = await _maybe_apply_vlm_correction_to_documents(
        db=db,
        db_document=db_document,
        parsed_documents=parsed_documents,
        prepared_state=prepared_state,
        pipeline_effective=pipeline_effective,
        add_stage_duration=add_stage_duration,
    )
    table_sidecar_tables_imported = _maybe_import_pdf_table_sidecars(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        parsed_documents=parsed_documents,
        prepared_state=prepared_state,
        pipeline_effective=pipeline_effective,
    )
    service._cleanup_parser_artifacts(artifact_dirs, tenant_id=tenant_id)
    await raise_if_cancelled()
    return parsed_documents, table_sidecar_tables_imported


def _governance_plugin_ref(pipeline_effective: PipelineEffective) -> str:
    return str(getattr(pipeline_effective, "governance_python_plugin", "") or "").strip()


def _run_governance_stage(
    governance_stage: Any,
    *,
    items: list[Document],
    file_path: Path,
    pipeline_effective: PipelineEffective,
    governance_kwargs: dict[str, Any],
    add_stage_duration: Any,
) -> Any:
    t0 = time.perf_counter()
    with metrics_span(
        "ingest.governance",
        enabled=bool(pipeline_effective.governance_enabled),
        otel_span_name="ingest.governance",
        otel_attributes={
            "ingest.stage": "governance",
            "document.file_type": str(file_path.suffix.lstrip(".") or "unknown").lower(),
            "governance.enabled": bool(pipeline_effective.governance_enabled),
        },
    ):
        gov = governance_stage.run(
            items=items,
            enabled=bool(pipeline_effective.governance_enabled),
            kwargs=governance_kwargs,
        )
    add_stage_duration("governance", (time.perf_counter() - t0) * 1000)
    return gov


def _apply_governance_python_plugin_if_needed(
    items: list[Document],
    *,
    governance_plugin_ref: str,
    pipeline_effective: PipelineEffective,
    document_id: UUID,
    tenant_id: UUID,
    stage: str,
    add_stage_duration: Any,
) -> list[Document]:
    if not governance_plugin_ref:
        return items
    t0 = time.perf_counter()
    with metrics_span("ingest.governance_python_plugin", enabled=True):
        processed_items = apply_governance_python_plugin(
            items,
            plugin_ref=governance_plugin_ref,
            params=dict(getattr(pipeline_effective, "governance_python_params", {}) or {}),
            context={
                "document_id": str(document_id),
                "tenant_id": str(tenant_id),
                "stage": stage,
            },
        )
    add_stage_duration("governance_python_plugin", (time.perf_counter() - t0) * 1000)
    return processed_items


def _maybe_build_governance_audit_patch(
    service: Any,
    *,
    before_items: list[Document] | None,
    after_items: list[Document] | None,
    enabled: bool,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    try:
        return service._build_governance_audit_metadata_patch(
            before_items=before_items,
            after_items=after_items,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record governance audit metadata: %s", str(exc)[:200])
        return None


async def _maybe_apply_llm_auto_tagging_audit(
    service: Any,
    items: list[Document],
    *,
    pipeline_effective: PipelineEffective,
    governance_audit_patch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not items:
        return governance_audit_patch
    llm_tagging_meta = await service._apply_llm_auto_tagging(items, pipeline_effective=pipeline_effective)
    if not llm_tagging_meta:
        return governance_audit_patch
    audit_patch = dict(governance_audit_patch or {})
    audit_patch["governance_llm_auto_tagging"] = llm_tagging_meta
    return audit_patch


async def _maybe_return_governance_drop_result(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    items: list[Document],
    pipeline_effective: PipelineEffective,
    governance_stats: GovernanceStats | None,
    governance_audit_patch: dict[str, Any] | None,
    with_stage_durations: Any,
    resolved_backend: str,
    resolved_chunk_strategy: str,
) -> dict[str, Any] | None:
    if not bool(pipeline_effective.governance_enabled):
        return None
    if governance_stats is None or items:
        return None
    if int(getattr(governance_stats, "dropped", 0) or 0) <= 0:
        return None
    service._record_governance_metadata(
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
    meta_patch = with_stage_durations(dict(db_document.doc_metadata or {}))
    from app.core.pipeline_versions import should_preserve_existing_versions

    update_kwargs: dict[str, Any] = {"error_message": msg, "doc_metadata": meta_patch}
    if not should_preserve_existing_versions(meta_patch):
        update_kwargs["chunk_count"] = 0
        update_kwargs["total_characters"] = 0
    await service._update_status(db, tenant_id, document_id, status, 0, status, **update_kwargs)
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


def _should_record_governance_enrichment(
    pipeline_effective: PipelineEffective,
    *,
    governance_plugin_ref: str,
) -> bool:
    return (
        bool(pipeline_effective.governance_enabled)
        or bool(governance_plugin_ref)
        or bool(getattr(pipeline_effective, "governance_llm_auto_tagging_enabled", False))
    )


def _maybe_record_governance_enrichment(
    service: Any,
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    items: list[Document],
    pipeline_effective: PipelineEffective,
    governance_plugin_ref: str,
) -> None:
    if not items or not _should_record_governance_enrichment(
        pipeline_effective,
        governance_plugin_ref=governance_plugin_ref,
    ):
        return
    try:
        service._record_governance_enrichment_metadata(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            items=items,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record governance enrichment: %s", str(exc)[:200])
    service._strip_doc_enrichment_fields(items)


def _maybe_persist_parsed_content(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    parsed_documents_before_governance: list[Document] | None,
    parsed_documents: list[Document],
    pipeline_effective: PipelineEffective,
) -> None:
    if not bool(getattr(pipeline_effective, "persist_parsed_content", False)):
        return
    try:
        original_md = _join_original_markdown_for_persistence(parsed_documents_before_governance)
        cleaned_md = _join_document_page_content(parsed_documents)
        persist_meta = service._persist_parsed_content(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            original_markdown=original_md,
            cleaned_markdown=cleaned_md,
            max_chars=int(getattr(pipeline_effective, "persist_parsed_content_max_chars", 0) or 0),
        )
        meta = dict(db_document.doc_metadata or {})
        meta["parsed_content_persisted"] = persist_meta
        if bool((persist_meta.get("cleaned") or {}).get("truncated")):
            meta.pop("ingest_checkpoint", None)
        else:
            meta = upsert_ingest_checkpoint(meta, stage="parsed", source="document_parsed_contents")
        _commit_document_metadata(db, db_document, meta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist parsed content: %s", str(exc)[:200])


async def _run_chunk_governance_flow(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    parse_state: ParseExecutionState,
    normalize_stage: Any,
    governance_stage: Any,
    add_stage_duration: Any,
    with_stage_durations: Any,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    with metrics_span("ingest.normalize"):
        parsed_chunks = normalize_stage.run(items=parse_state.parsed.chunks)
    add_stage_duration("normalize", (time.perf_counter() - t0) * 1000)

    pipeline_effective = prepared_state.pipeline_effective
    gov = _run_governance_stage(
        governance_stage,
        items=parsed_chunks,
        file_path=prepared_state.file_path,
        pipeline_effective=pipeline_effective,
        governance_kwargs=prepared_state.governance_kwargs,
        add_stage_duration=add_stage_duration,
    )
    governance_plugin = _governance_plugin_ref(pipeline_effective)
    chunks = _apply_governance_python_plugin_if_needed(
        gov.items,
        governance_plugin_ref=governance_plugin,
        pipeline_effective=pipeline_effective,
        document_id=document_id,
        tenant_id=tenant_id,
        stage="post_governance_chunks",
        add_stage_duration=add_stage_duration,
    )
    governance_audit_patch = _maybe_build_governance_audit_patch(
        service,
        before_items=parsed_chunks,
        after_items=chunks,
        enabled=bool(pipeline_effective.governance_enabled) or bool(governance_plugin),
    )
    governance_audit_patch = await _maybe_apply_llm_auto_tagging_audit(
        service,
        chunks,
        pipeline_effective=pipeline_effective,
        governance_audit_patch=governance_audit_patch,
    )
    early_result = await _maybe_return_governance_drop_result(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        items=chunks,
        pipeline_effective=pipeline_effective,
        governance_stats=gov.stats,
        governance_audit_patch=governance_audit_patch,
        with_stage_durations=with_stage_durations,
        resolved_backend=parse_state.resolved_backend,
        resolved_chunk_strategy=parse_state.resolved_chunk_strategy,
    )
    if early_result is not None:
        return {"result": early_result}
    _maybe_record_governance_enrichment(
        service,
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        items=chunks,
        pipeline_effective=pipeline_effective,
        governance_plugin_ref=governance_plugin,
    )
    return {
        "chunks": chunks,
        "governance_stats": gov.stats,
        "governance_audit_patch": governance_audit_patch,
    }


async def _run_document_governance_flow(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    parse_state: ParseExecutionState,
    parsed_documents: list[Document] | None,
    normalize_stage: Any,
    governance_stage: Any,
    add_stage_duration: Any,
    with_stage_durations: Any,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    with metrics_span("ingest.normalize"):
        normalized_documents = normalize_stage.run(items=parsed_documents or [])
    add_stage_duration("normalize", (time.perf_counter() - t0) * 1000)

    pipeline_effective = prepared_state.pipeline_effective
    parsed_documents_before_governance = normalized_documents
    governance_plugin = _governance_plugin_ref(pipeline_effective)
    normalized_documents = _apply_governance_python_plugin_if_needed(
        normalized_documents,
        governance_plugin_ref=governance_plugin,
        pipeline_effective=pipeline_effective,
        document_id=document_id,
        tenant_id=tenant_id,
        stage="pre_builtin_governance_documents",
        add_stage_duration=add_stage_duration,
    )
    gov = _run_governance_stage(
        governance_stage,
        items=normalized_documents,
        file_path=prepared_state.file_path,
        pipeline_effective=pipeline_effective,
        governance_kwargs=prepared_state.governance_kwargs,
        add_stage_duration=add_stage_duration,
    )
    normalized_documents = gov.items
    governance_audit_patch = _maybe_build_governance_audit_patch(
        service,
        before_items=parsed_documents_before_governance,
        after_items=normalized_documents,
        enabled=bool(pipeline_effective.governance_enabled) or bool(governance_plugin),
    )
    governance_audit_patch = await _maybe_apply_llm_auto_tagging_audit(
        service,
        normalized_documents,
        pipeline_effective=pipeline_effective,
        governance_audit_patch=governance_audit_patch,
    )
    _ensure_ingest_page_indices(normalized_documents)
    _maybe_persist_parsed_content(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        parsed_documents_before_governance=parsed_documents_before_governance,
        parsed_documents=normalized_documents,
        pipeline_effective=pipeline_effective,
    )
    early_result = await _maybe_return_governance_drop_result(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        items=normalized_documents,
        pipeline_effective=pipeline_effective,
        governance_stats=gov.stats,
        governance_audit_patch=governance_audit_patch,
        with_stage_durations=with_stage_durations,
        resolved_backend=parse_state.resolved_backend,
        resolved_chunk_strategy=parse_state.resolved_chunk_strategy,
    )
    if early_result is not None:
        return {"result": early_result}
    _maybe_record_governance_enrichment(
        service,
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        items=normalized_documents,
        pipeline_effective=pipeline_effective,
        governance_plugin_ref=governance_plugin,
    )
    return {
        "parsed_documents": normalized_documents,
        "governance_stats": gov.stats,
        "governance_audit_patch": governance_audit_patch,
    }


async def _chunk_governed_documents(
    service: Any,
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    resolved_chunk_strategy: str,
    parsed_documents: list[Document],
    chunking_stage: Any,
    add_stage_duration: Any,
) -> dict[str, Any]:
    await service._update_status(db, tenant_id, document_id, "processing", 33, "chunking")
    t0 = time.perf_counter()
    pipeline_effective = prepared_state.pipeline_effective
    with metrics_span(
        "ingest.chunking",
        chunk_strategy=resolved_chunk_strategy,
        chunk_size=int(pipeline_effective.chunk_size),
        chunk_overlap=int(pipeline_effective.chunk_overlap),
        otel_span_name="ingest.chunk",
        otel_attributes={
            "ingest.stage": "chunk",
            "document.file_type": str(prepared_state.file_path.suffix.lstrip(".") or "unknown").lower(),
            "chunk.strategy": str(resolved_chunk_strategy or "").strip().lower() or "default",
        },
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
    add_stage_duration("chunking", (time.perf_counter() - t0) * 1000)
    merge_min = max(0, int(getattr(pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
    merge_small_after = len(chunks)
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
        add_stage_duration("chunk_merge_small", (time.perf_counter() - t0) * 1000)
        merge_small_after = len(merged)
        merge_small_reduced = max(0, len(chunks) - merge_small_after)
        chunks = merged
    return {
        "chunks": chunks,
        "merge_small_min_chars": int(merge_min),
        "merge_small_before": len(chunked.chunks),
        "merge_small_after": int(merge_small_after),
        "merge_small_reduced": int(merge_small_reduced),
    }


def _filter_short_chunks(chunks: list[Document], *, min_chars: int, document_id: UUID) -> list[Document]:
    if min_chars <= 0 or not chunks:
        return chunks
    before = len(chunks)
    filtered: list[Document] = []
    for chunk in chunks:
        content = (chunk.page_content or "").strip()
        if len(content) >= min_chars:
            filtered.append(chunk)
            continue
        meta = chunk.metadata or {}
        doc_type = str(meta.get("doc_type_kwd") or "").lower()
        if (
            doc_type in {"image", "table"}
            or meta.get("image") is not None
            or meta.get("img_id")
            or meta.get("image_id")
            or meta.get("image_url")
        ):
            filtered.append(chunk)
    kept_short_fallback = False
    if not filtered:
        longest = max(chunks, key=lambda d: len((d.page_content or "").strip()))
        filtered = [longest]
        kept_short_fallback = True
    dropped = before - len(filtered)
    if kept_short_fallback:
        kept_len = len((filtered[0].page_content or "").strip()) if filtered else 0
        logger.info(
            "All chunks shorter than %s chars; kept 1 (%s chars) and dropped %s for document %s",
            min_chars,
            kept_len,
            dropped,
            document_id,
        )
    elif dropped:
        logger.info("Dropped %s short chunks (<%s chars) for document %s", dropped, min_chars, document_id)
    return filtered


def _run_chunk_dedup_stage(
    chunk_dedup_stage: Any,
    *,
    chunks: list[Document],
    document_id: UUID,
    add_stage_duration: Any,
) -> tuple[list[Document], int]:
    t0 = time.perf_counter()
    with metrics_span("ingest.chunk_dedup", enabled=True):
        deduped = chunk_dedup_stage.run(chunks=chunks, enabled=True)
    add_stage_duration("chunk_dedup", (time.perf_counter() - t0) * 1000)
    duplicates_dropped = int(deduped.duplicates_dropped)
    if duplicates_dropped > 0:
        logger.info("Dropped %s duplicate chunks for document %s", duplicates_dropped, document_id)
        log_metrics({"event": "ingest.chunk_dedup", "duplicates_dropped": duplicates_dropped})
    return deduped.chunks, duplicates_dropped


def _compute_near_dedup_state(
    *,
    chunks: list[Document],
    threshold: int,
    max_bucket_size: int,
    index_path: Path,
) -> dict[str, Any]:
    kept_chunks: list[Document] = []
    kept_hashes: list[str] = []
    near_dedup_dropped = 0
    sample_match: dict[str, Any] | None = None

    def update_fn(buckets: dict[str, list[str]]):
        nonlocal near_dedup_dropped, sample_match
        for chunk in chunks:
            meta = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
            if _should_skip_near_dedup_for_chunk(chunk):
                kept_chunks.append(chunk)
                continue
            content_norm = normalize_text(
                chunk.page_content or "",
                normalize_line_endings=True,
                remove_control_chars=True,
            )
            sh_hex = str(meta.get("simhash64") or "").strip().lower()
            if not sh_hex:
                sh_hex = simhash64_hex(simhash64(content_norm))
                meta = dict(meta)
                meta["simhash64"] = sh_hex
                meta.setdefault("simhash_algo", "simhash64_sha1")
                chunk.metadata = meta
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
            kept_chunks.append(chunk)
            kept_hashes.append(sh_hex)
        if kept_hashes:
            add_simhashes(buckets=buckets, simhashes=kept_hashes, max_bucket_size=max_bucket_size)
        return buckets

    with metrics_span("ingest.near_dedup", enabled=True, threshold=threshold):
        with_near_dedup_index(path=index_path, fn=update_fn)
    return {
        "kept_chunks": kept_chunks,
        "near_dedup_dropped": near_dedup_dropped,
        "sample_match": sample_match,
    }


def _finalize_near_dedup_result(
    *,
    db: Session,
    db_document: DBDocument,
    document_id: UUID,
    chunks: list[Document],
    threshold: int,
    max_bucket_size: int,
    state: dict[str, Any],
) -> list[Document]:
    near_dedup_dropped = int(state["near_dedup_dropped"])
    if near_dedup_dropped <= 0:
        return chunks
    updated_chunks = list(state["kept_chunks"])
    if not updated_chunks:
        longest = max(chunks, key=lambda d: len((d.page_content or "").strip()), default=None)
        if longest is not None:
            updated_chunks = [longest]
    logger.info(
        "Dropped %s near-duplicate chunks for document %s (threshold=%s)",
        near_dedup_dropped,
        document_id,
        int(threshold),
    )
    log_metrics({"event": "ingest.near_dedup", "dropped": near_dedup_dropped, "threshold": int(threshold)})
    meta = dict(db_document.doc_metadata or {})
    meta["near_dedup"] = {
        "enabled": True,
        "dropped": near_dedup_dropped,
        "threshold": int(threshold),
        "max_bucket_size": int(max_bucket_size),
        "sample_match": state["sample_match"],
    }
    _commit_document_metadata(db, db_document, meta)
    return updated_chunks


def _run_near_dedup_stage(
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    chunks: list[Document],
    pipeline_effective: PipelineEffective,
    add_stage_duration: Any,
) -> list[Document]:
    t0 = time.perf_counter()
    updated_chunks = chunks
    try:
        threshold = max(0, int(getattr(pipeline_effective, "near_dedup_hamming_threshold", 0) or 0))
        max_bucket_size = max(0, int(getattr(pipeline_effective, "near_dedup_max_bucket_size", 0) or 0))
        safe_dataset = re.sub(r"[^A-Za-z0-9._-]+", "_", str(prepared_state.dataset_id or tenant_id))
        index_path = Path(settings.UPLOAD_DIR) / str(tenant_id) / ".mimirq_dedup" / f"{safe_dataset}.json"
        state = _compute_near_dedup_state(
            chunks=chunks,
            threshold=threshold,
            max_bucket_size=max_bucket_size,
            index_path=index_path,
        )
        updated_chunks = _finalize_near_dedup_result(
            db=db,
            db_document=db_document,
            document_id=document_id,
            chunks=chunks,
            threshold=threshold,
            max_bucket_size=max_bucket_size,
            state=state,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Near-dup stage failed (ignored): %s", str(exc)[:200])
    add_stage_duration("near_dedup", (time.perf_counter() - t0) * 1000)
    return updated_chunks


def _truncate_chunks_for_document(
    chunks: list[Document],
    *,
    document_id: UUID,
    max_chunks_per_document: int,
    truncation_strategy: str,
) -> tuple[list[Document], dict[str, Any]]:
    truncation_info = {
        "truncated_from": 0,
        "truncated_to": 0,
        "truncated_dropped": 0,
        "truncated_asset_total": 0,
        "truncated_asset_kept": 0,
        "truncated_strategy_used": "",
    }
    if max_chunks_per_document <= 0 or not chunks or len(chunks) <= max_chunks_per_document:
        return chunks, truncation_info
    truncation_info["truncated_from"] = len(chunks)
    truncated_chunks, details = _truncate_chunks_for_limit(
        chunks,
        max_chunks=max_chunks_per_document,
        strategy=truncation_strategy,
    )
    truncation_info["truncated_to"] = len(truncated_chunks)
    truncation_info["truncated_dropped"] = max(0, len(chunks) - len(truncated_chunks))
    truncation_info["truncated_asset_total"] = int(details.get("asset_total") or 0)
    truncation_info["truncated_asset_kept"] = int(details.get("asset_kept") or 0)
    truncation_info["truncated_strategy_used"] = str(details.get("strategy") or "").strip() or str(truncation_strategy)
    logger.info(
        "Truncated chunks for document %s: kept=%s dropped=%s assets=%s/%s strategy=%s (MAX_CHUNKS_PER_DOCUMENT=%s)",
        document_id,
        truncation_info["truncated_to"],
        truncation_info["truncated_dropped"],
        truncation_info["truncated_asset_kept"],
        truncation_info["truncated_asset_total"],
        truncation_info["truncated_strategy_used"],
        max_chunks_per_document,
    )
    log_metrics(
        {
            "event": "ingest.chunk_truncate",
            "chunk_before": int(truncation_info["truncated_from"]),
            "chunk_after": int(truncation_info["truncated_to"]),
            "dropped": int(truncation_info["truncated_dropped"]),
            "max_chunks_per_document": int(max_chunks_per_document),
            "strategy": truncation_info["truncated_strategy_used"],
            "asset_kept": int(truncation_info["truncated_asset_kept"]),
            "asset_total": int(truncation_info["truncated_asset_total"]),
        }
    )
    return truncated_chunks, truncation_info


def _record_chunk_postprocess_metadata_if_needed(
    service: Any,
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    merge_small_min_chars: int,
    merge_small_before: int,
    merge_small_after: int,
    merge_small_reduced: int,
    dedup_enabled: bool,
    dedup_dropped: int,
    max_chunks_per_document: int,
    truncation_strategy: str,
    truncation_info: dict[str, Any],
) -> None:
    if merge_small_min_chars <= 0 and not dedup_enabled and max_chunks_per_document <= 0:
        return
    service._record_chunk_postprocess_metadata(
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
            max_chunks_strategy=str(truncation_info["truncated_strategy_used"] or truncation_strategy),
            truncated_from=int(truncation_info["truncated_from"]),
            truncated_to=int(truncation_info["truncated_to"]),
            truncated_dropped=int(truncation_info["truncated_dropped"]),
            truncated_asset_total=int(truncation_info["truncated_asset_total"]),
            truncated_asset_kept=int(truncation_info["truncated_asset_kept"]),
        ),
    )


def _apply_common_chunk_postprocess(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    chunks: list[Document],
    pipeline_effective: PipelineEffective,
    chunk_dedup_stage: Any,
    add_stage_duration: Any,
    table_sidecar_tables_imported: int,
    table_sidecar_routing_audit: dict[str, Any] | None,
    merge_small_min_chars: int,
    merge_small_before: int,
    merge_small_after: int,
    merge_small_reduced: int,
) -> dict[str, Any]:
    filtered_chunks = _filter_short_chunks(
        chunks,
        min_chars=max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0)),
        document_id=document_id,
    )
    dedup_enabled = bool(getattr(settings, "CHUNK_DEDUP_ENABLED", False))
    dedup_dropped = 0
    if dedup_enabled and filtered_chunks:
        filtered_chunks, dedup_dropped = _run_chunk_dedup_stage(
            chunk_dedup_stage,
            chunks=filtered_chunks,
            document_id=document_id,
            add_stage_duration=add_stage_duration,
        )
    if bool(getattr(pipeline_effective, "near_dedup_enabled", False)) and filtered_chunks:
        filtered_chunks = _run_near_dedup_stage(
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            document_id=document_id,
            prepared_state=prepared_state,
            chunks=filtered_chunks,
            pipeline_effective=pipeline_effective,
            add_stage_duration=add_stage_duration,
        )
    if filtered_chunks and table_sidecar_tables_imported >= 0:
        filtered_chunks, table_sidecar_routing_audit = service._apply_table_sidecar_exclusive_routing(
            chunks=filtered_chunks,
            enabled=bool(getattr(pipeline_effective, "table_store_sidecar_exclusive_routing", False)),
            sidecar_tables_imported=table_sidecar_tables_imported,
        )
    max_chunks_per_document = max(0, int(getattr(settings, "MAX_CHUNKS_PER_DOCUMENT", 0) or 0))
    truncation_strategy = str(getattr(settings, "MAX_CHUNKS_PER_DOCUMENT_STRATEGY", "head") or "head")
    filtered_chunks, truncation_info = _truncate_chunks_for_document(
        filtered_chunks,
        document_id=document_id,
        max_chunks_per_document=max_chunks_per_document,
        truncation_strategy=truncation_strategy,
    )
    _record_chunk_postprocess_metadata_if_needed(
        service,
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        merge_small_min_chars=merge_small_min_chars,
        merge_small_before=merge_small_before,
        merge_small_after=merge_small_after,
        merge_small_reduced=merge_small_reduced,
        dedup_enabled=dedup_enabled,
        dedup_dropped=dedup_dropped,
        max_chunks_per_document=max_chunks_per_document,
        truncation_strategy=truncation_strategy,
        truncation_info=truncation_info,
    )
    return {
        "chunks": filtered_chunks,
        "table_sidecar_routing_audit": table_sidecar_routing_audit,
    }


def _maybe_record_governance_metadata(
    service: Any,
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    governance_stats: GovernanceStats | None,
    pipeline_effective: PipelineEffective,
    governance_audit_patch: dict[str, Any] | None,
) -> None:
    if governance_stats is None:
        return
    service._record_governance_metadata(
        db,
        tenant_id,
        document_id,
        governance_stats,
        rule_packs=list(getattr(pipeline_effective, "governance_rule_packs", None) or []),
        audit_patch=governance_audit_patch,
    )


async def _maybe_return_no_chunks_result(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    with_stage_durations: Any,
    table_sidecar_routing_audit: dict[str, Any] | None,
    resolved_backend: str,
    resolved_chunk_strategy: str,
) -> dict[str, Any] | None:
    sidecar_excluded = int((table_sidecar_routing_audit or {}).get("table_chunks_excluded_from_rag") or 0)
    sidecar_imported = int((table_sidecar_routing_audit or {}).get("sidecar_tables_imported") or 0)
    if sidecar_excluded > 0 and sidecar_imported > 0:
        meta_patch = dict(db_document.doc_metadata or {})
        meta_patch["table_sidecar_routing"] = dict(table_sidecar_routing_audit or {})
        meta_patch = with_stage_durations(meta_patch)
        await service._update_status(
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
    meta_patch = with_stage_durations(dict(db_document.doc_metadata or {}))
    if table_sidecar_routing_audit:
        meta_patch["table_sidecar_routing"] = dict(table_sidecar_routing_audit)
    await service._update_status(
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


def _record_chunking_stats_metadata_with_guard(
    service: Any,
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    chunks: list[Document],
    parsed_documents: list[Document] | None,
) -> None:
    try:
        service._record_chunking_stats_metadata(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            chunks=chunks,
            total_characters=_joined_text_total_characters(parsed_documents, join_separator="\n\n"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record chunking stats: %s", str(exc)[:200])


def _selected_chunk_strategy_counts(chunks: list[Document]) -> dict[str, int]:
    selected_counts: dict[str, int] = {}
    for chunk in chunks:
        selected = (chunk.metadata or {}).get("chunk_strategy_selected")
        if isinstance(selected, str) and selected.strip():
            selected_counts[selected] = selected_counts.get(selected, 0) + 1
    return selected_counts


def _apply_chunk_asset_stage_and_metadata(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    chunks: list[Document],
    pipeline_effective: PipelineEffective,
    chunk_asset_stage: Any,
    add_stage_duration: Any,
    governance_stats: GovernanceStats | None,
    resolved_backend: str,
    resolved_chunk_strategy: str,
) -> list[Document]:
    t0 = time.perf_counter()
    with metrics_span("ingest.chunk_assets"):
        chunk_asset = chunk_asset_stage.run(
            chunks=chunks,
            tenant_id=tenant_id,
            document_id=document_id,
            options=ChunkAssetOptions(
                dataset_id=prepared_state.dataset_id,
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
    add_stage_duration("chunk_assets", (time.perf_counter() - t0) * 1000)
    chunked_items = chunk_asset.chunks
    pipeline_hash = str((db_document.doc_metadata or {}).get("pipeline_hash") or "").strip()
    file_type = (
        str(getattr(db_document, "file_type", "") or "").strip().lower()
        or str(prepared_state.file_path.suffix.lstrip(".")).lower()
    )
    governance_version = (
        str(getattr(governance_stats, "version", "") or "").strip() if governance_stats is not None else ""
    )
    for chunk in chunked_items:
        meta = dict(chunk.metadata or {})
        if pipeline_hash:
            meta.setdefault("pipeline_hash", pipeline_hash)
            meta.setdefault("doc_pipeline_key", f"{document_id}:{pipeline_hash}")
        if file_type:
            meta.setdefault("file_type", file_type)
        if governance_version:
            meta.setdefault("governance_version", governance_version)
        chunk.metadata = meta
    for iid in chunk_asset.img_ids:
        if isinstance(iid, str) and iid.strip():
            prepared_state.document_img_ids.add(iid)
    if resolved_chunk_strategy == "auto" and chunked_items:
        selected_counts = _selected_chunk_strategy_counts(chunked_items)
        if selected_counts:
            service._record_auto_chunking_metadata(
                db,
                tenant_id=tenant_id,
                document_id=document_id,
                selected_counts=selected_counts,
            )
    service._record_document_image_ids(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        img_ids=prepared_state.document_img_ids,
    )
    return chunked_items


def _run_index_stage(
    index_stage: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    chunks: list[Document],
    add_stage_duration: Any,
) -> Any:
    t0 = time.perf_counter()
    with metrics_span(
        "ingest.index",
        chunk_count=len(chunks),
        chunk_vector_enabled=bool(getattr(prepared_state.index_options, "chunk_vector_enabled", True)),
        bm25_index_enabled=bool(getattr(prepared_state.index_options, "bm25_index_enabled", True)),
        otel_span_name="ingest.index",
        otel_attributes={
            "ingest.stage": "index",
            "document.file_type": str(prepared_state.file_path.suffix.lstrip(".") or "unknown").lower(),
            "index.chunk_vector_enabled": bool(getattr(prepared_state.index_options, "chunk_vector_enabled", True)),
            "index.bm25_index_enabled": bool(getattr(prepared_state.index_options, "bm25_index_enabled", True)),
        },
    ):
        indexed = index_stage.run(
            db=db,
            tenant_id=tenant_id,
            document_id=document_id,
            file_path=prepared_state.file_path,
            default_source=str(getattr(db_document, "filename", "") or "").strip()
            or str(prepared_state.file_path.name),
            chunks=chunks,
            options=prepared_state.index_options,
        )
    add_stage_duration("index", (time.perf_counter() - t0) * 1000)
    return indexed


async def _finalize_indexed_document(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    pipeline_effective: PipelineEffective,
    chunks: list[Document],
    indexed: Any,
    table_sidecar_routing_audit: dict[str, Any] | None,
    with_stage_durations: Any,
    raise_if_cancelled: Any,
    resolved_backend: str,
    resolved_chunk_strategy: str,
) -> dict[str, Any]:
    total_chars = indexed.total_characters
    log_metrics({"event": "ingest.index.result", "chunk_count": len(chunks), "total_characters": total_chars})
    with metrics_span(
        "ingest.finalize",
        chunk_count=len(chunks),
        total_characters=total_chars,
        kg_enabled=bool(getattr(pipeline_effective, "kg_enabled", False)),
        otel_span_name="ingest.finalize",
        otel_attributes={
            "ingest.stage": "finalize",
            "document.file_type": str(prepared_state.file_path.suffix.lstrip(".") or "unknown").lower(),
            "pipeline.kg_enabled": bool(getattr(pipeline_effective, "kg_enabled", False)),
        },
    ):
        checkpoint_meta = with_stage_durations(dict(db_document.doc_metadata or {}))
        checkpoint_meta["indexed_total_characters"] = int(total_chars)
        checkpoint_meta = upsert_ingest_checkpoint(
            checkpoint_meta,
            stage="indexed",
            source="document_chunks",
            extra={
                "chunk_count": len(chunks),
                "total_characters": int(total_chars),
                "doc_pipeline_key": (
                    f"{document_id}:{str(checkpoint_meta.get('pipeline_hash') or '').strip()}"
                    if str(checkpoint_meta.get("pipeline_hash") or "").strip()
                    else None
                ),
            },
        )
        _commit_document_metadata(db, db_document, checkpoint_meta)
        await raise_if_cancelled(force=True)
        meta_patch = dict(db_document.doc_metadata or {})
        completed_pipeline_hash = str(meta_patch.get("pipeline_hash") or "").strip()
        if completed_pipeline_hash:
            meta_patch["active_pipeline_hash"] = completed_pipeline_hash
            meta_patch["active_pipeline_ready"] = True
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
        meta_patch = with_stage_durations(meta_patch)
        await service._update_status(
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
                "img_count": len(prepared_state.document_img_ids),
            }
        )
        await run_post_completion_kg(
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_ids=indexed.chunk_ids,
            db_chunks=indexed.db_chunks,
            index_options=prepared_state.index_options,
            pipeline_effective=pipeline_effective,
        )
    return {
        "status": "success",
        "chunk_count": len(chunks),
        "total_characters": total_chars,
        "parser_backend": resolved_backend,
        "chunk_strategy": resolved_chunk_strategy,
    }


async def continue_process_document_flow(
    service: Any,
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    prepared_state: PreparedProcessDocumentState,
    parse_state: ParseExecutionState,
    inline_asset_stage: Any,
    normalize_stage: Any,
    governance_stage: Any,
    chunking_stage: Any,
    chunk_dedup_stage: Any,
    chunk_asset_stage: Any,
    index_stage: Any,
    add_stage_duration: Any,
    with_stage_durations: Any,
    raise_if_cancelled: Any,
) -> dict[str, Any]:
    pipeline_effective = prepared_state.pipeline_effective
    parsed_documents, table_sidecar_tables_imported = await _prepare_parsed_documents_for_continuation(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        parse_state=parse_state,
        inline_asset_stage=inline_asset_stage,
        add_stage_duration=add_stage_duration,
        raise_if_cancelled=raise_if_cancelled,
    )
    governance_stats: GovernanceStats | None = None
    governance_audit_patch: dict[str, Any] | None = None
    merge_small_min_chars = 0
    merge_small_before = 0
    merge_small_after = 0
    merge_small_reduced = 0
    table_sidecar_routing_audit = prepared_state.table_sidecar_routing_audit

    if parse_state.parsed.chunks is not None:
        chunk_flow = await _run_chunk_governance_flow(
            service,
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            document_id=document_id,
            prepared_state=prepared_state,
            parse_state=parse_state,
            normalize_stage=normalize_stage,
            governance_stage=governance_stage,
            add_stage_duration=add_stage_duration,
            with_stage_durations=with_stage_durations,
        )
        early_result = chunk_flow.get("result")
        if early_result is not None:
            return early_result
        chunks = chunk_flow["chunks"]
        governance_stats = chunk_flow["governance_stats"]
        governance_audit_patch = chunk_flow["governance_audit_patch"]
    else:
        document_flow = await _run_document_governance_flow(
            service,
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            document_id=document_id,
            prepared_state=prepared_state,
            parse_state=parse_state,
            parsed_documents=parsed_documents,
            normalize_stage=normalize_stage,
            governance_stage=governance_stage,
            add_stage_duration=add_stage_duration,
            with_stage_durations=with_stage_durations,
        )
        early_result = document_flow.get("result")
        if early_result is not None:
            return early_result
        parsed_documents = document_flow["parsed_documents"]
        governance_stats = document_flow["governance_stats"]
        governance_audit_patch = document_flow["governance_audit_patch"]
        await raise_if_cancelled()
        chunking_flow = await _chunk_governed_documents(
            service,
            db=db,
            tenant_id=tenant_id,
            document_id=document_id,
            prepared_state=prepared_state,
            resolved_chunk_strategy=parse_state.resolved_chunk_strategy,
            parsed_documents=parsed_documents,
            chunking_stage=chunking_stage,
            add_stage_duration=add_stage_duration,
        )
        chunks = chunking_flow["chunks"]
        merge_small_min_chars = chunking_flow["merge_small_min_chars"]
        merge_small_before = chunking_flow["merge_small_before"]
        merge_small_after = chunking_flow["merge_small_after"]
        merge_small_reduced = chunking_flow["merge_small_reduced"]

    await raise_if_cancelled()
    postprocess = _apply_common_chunk_postprocess(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        chunks=chunks,
        pipeline_effective=pipeline_effective,
        chunk_dedup_stage=chunk_dedup_stage,
        add_stage_duration=add_stage_duration,
        table_sidecar_tables_imported=table_sidecar_tables_imported,
        table_sidecar_routing_audit=table_sidecar_routing_audit,
        merge_small_min_chars=merge_small_min_chars,
        merge_small_before=merge_small_before,
        merge_small_after=merge_small_after,
        merge_small_reduced=merge_small_reduced,
    )
    chunks = postprocess["chunks"]
    table_sidecar_routing_audit = postprocess["table_sidecar_routing_audit"]
    _maybe_record_governance_metadata(
        service,
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        governance_stats=governance_stats,
        pipeline_effective=pipeline_effective,
        governance_audit_patch=governance_audit_patch,
    )
    try:
        maybe_enrich_document_questions(
            db,
            db_document=db_document,
            documents=(parsed_documents or chunks),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist document questions metadata: %s", str(exc)[:200])

    await raise_if_cancelled()
    if not chunks:
        empty_result = await _maybe_return_no_chunks_result(
            service,
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            document_id=document_id,
            with_stage_durations=with_stage_durations,
            table_sidecar_routing_audit=table_sidecar_routing_audit,
            resolved_backend=parse_state.resolved_backend,
            resolved_chunk_strategy=parse_state.resolved_chunk_strategy,
        )
        if empty_result is not None:
            return empty_result

    _record_chunking_stats_metadata_with_guard(
        service,
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        chunks=chunks,
        parsed_documents=parsed_documents,
    )
    await raise_if_cancelled()
    chunks = _apply_chunk_asset_stage_and_metadata(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        chunks=chunks,
        pipeline_effective=pipeline_effective,
        chunk_asset_stage=chunk_asset_stage,
        add_stage_duration=add_stage_duration,
        governance_stats=governance_stats,
        resolved_backend=parse_state.resolved_backend,
        resolved_chunk_strategy=parse_state.resolved_chunk_strategy,
    )
    await raise_if_cancelled()
    await service._update_status(db, tenant_id, document_id, "processing", 66, "embedding")
    await raise_if_cancelled()
    await service._update_status(db, tenant_id, document_id, "processing", 80, "vector_write")
    indexed = _run_index_stage(
        index_stage,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        chunks=chunks,
        add_stage_duration=add_stage_duration,
    )
    return await _finalize_indexed_document(
        service,
        db=db,
        db_document=db_document,
        tenant_id=tenant_id,
        document_id=document_id,
        prepared_state=prepared_state,
        pipeline_effective=pipeline_effective,
        chunks=chunks,
        indexed=indexed,
        table_sidecar_routing_audit=table_sidecar_routing_audit,
        with_stage_durations=with_stage_durations,
        raise_if_cancelled=raise_if_cancelled,
        resolved_backend=parse_state.resolved_backend,
        resolved_chunk_strategy=parse_state.resolved_chunk_strategy,
    )
