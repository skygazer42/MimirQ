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
import uuid  # noqa: F401
from dataclasses import dataclass  # noqa: F401
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
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
from app.parsing.artifact_stats import POSITION_TAG_RE, compute_parsing_artifact_stats  # noqa: F401
from app.parsing.enrich.chart_to_data import add_chart_data_blocks  # noqa: F401
from app.parsing.enrich.formula_ocr import add_formula_latex_blocks  # noqa: F401
from app.parsing.enrich.image_caption import add_image_captions  # noqa: F401
from app.parsing.enrich.image_code import add_image_code_blocks  # noqa: F401
from app.parsing.enrich.vlm_image_caption import add_vlm_image_captions  # noqa: F401
from app.parsing.errors import ParsingError  # noqa: F401
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
from app.parsing.processors.support.assets import (  # noqa: F401
    _apply_inline_asset_audit_patch,
    _asset_metadata,
    _chunk_has_asset,
    _collect_artifact_dir_from_meta,
    _collect_image_ids_from_meta,
    _collect_item_asset_refs,
    _collect_parser_asset_refs,
    _inline_asset_audit_needed,
)
from app.parsing.processors.support.chunk_postprocess import (  # noqa: F401
    _MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS,
    _append_unmergeable_chunk,
    _build_page_start_offsets,
    _build_page_text_lookup,
    _chunk_asset_indices,
    _chunk_has_record_identity,
    _chunk_mergeable,
    _chunk_page_index,
    _chunk_record_identity_key,
    _chunks_share_record_identity_boundary,
    _document_page_index,
    _ensure_ingest_page_indices,
    _fill_uniform_sample,
    _flush_pending_on_page_change,
    _initial_uniform_sample,
    _joined_text_total_characters,
    _local_chunk_range,
    _merge_small_chunks_by_min_chars,
    _merge_two_small_chunks,
    _merge_with_pending_small_chunk,
    _optional_int,
    _rebase_chunk_offsets_by_page_index,
    _rebase_single_chunk_offsets,
    _refresh_merged_chunk_content_metadata,
    _retrieval_text_for_merge,
    _should_skip_near_dedup_for_chunk,
    _truncate_asset_uniform_chunks,
    _truncate_chunks_for_limit,
    _truncate_head_chunks,
    _try_merge_with_previous_chunk,
    _uniform_sample_indices,
)
from app.parsing.processors.support.common import (  # noqa: F401
    _PROCESSOR_CLEANUP_LOG_MESSAGE,
    MIMIRQ_PARSE_DIRNAME,
    REDACTED_MASK,
    SECRET_MASK,
    _log_processor_fallback,
)
from app.parsing.processors.support.parse_io import (  # noqa: F401
    _attach_logical_source_metadata,
    _deserialize_documents_from_parse_cache,
    _get_position_tagged_markdown,
    _join_document_page_content,
    _join_original_markdown_for_persistence,
    _logical_source_from_db_document,
    _serialize_documents_for_parse_cache,
)
from app.parsing.processors.support.quality import (  # noqa: F401
    _aggregate_governance_quality,
    _append_ocr_quality_candidate,
    _build_ocr_quality_summary,
    _build_seal_summary,
    _clean_governance_rule_packs,
    _coerce_float,
    _coerce_int,
    _compute_governance_quality_metrics,
    _format_seal_summary,
    _governance_quality_from_metadata,
    _governance_reduction_pct,
    _is_seal_segment_metadata,
    _is_table_segment_metadata,
    _iter_ocr_quality_candidates,
    _low_confidence_span,
    _ocr_confidence_from_metadata,
    _positive_governance_counts,
    _positive_string_count_map,
    _safe_governance_int,
    _seal_candidate_from_document,
    _seal_primary_metadata,
    _seal_segment_candidate_count,
    _seal_segment_page,
    _seal_summary_to_specialty_signals,
    _string_count_map,
)
from app.parsing.processors.support.recovery import (
    CheckpointedRetryRequiredError,
    apply_pending_retry_cleanup,
    audit_ingest_gate,
    checkpoint_stage,
    indexed_checkpoint_is_reusable,
    maybe_enrich_document_questions,
    parsed_checkpoint_is_reusable,
    persist_retry_boundary_failure,
    record_ingest_gate_outcome,
    resolve_ingestion_run_update_criticality,
    run_post_completion_kg,
    upsert_ingest_checkpoint,
)
from app.parsing.processors.support.results import (  # noqa: F401
    ChunkAssetOptions,
    ChunkAssetResult,
    ChunkDedupResult,
    ChunkingResult,
    ChunkPostprocessStats,
    DocumentCancelledError,
    GovernanceResult,
    IndexResult,
    InlineAssetResult,
    ParseResult,
)
from app.parsing.processors.support.stages import (  # noqa: F401
    ChunkAssetStage,
    ChunkDedupStage,
    ChunkingStage,
    GovernanceStage,
    InlineAssetStage,
    NormalizeStage,
    ParsingStage,
)
from app.parsing.processors.vlm_correction import apply_vlm_correction_async, should_apply_vlm_correction
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.reading_order import score_reading_order
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.parsing.routing import route_pdf_backend, should_attempt_pdf_fallback  # noqa: F401
from app.parsing.subprocess_runner import SubprocessCancelled, run_parser_subprocess  # noqa: F401
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.roles import classify_chunk_semantic_role, classify_chunk_type  # noqa: F401
from app.rag.chunking.strategies import SeparatorChunker  # noqa: F401
from app.rag.chunking.utils.hierarchical import apply_sequence_hierarchy_metadata  # noqa: F401
from app.rag.core.logging import get_logger
from app.rag.core.metadata import (
    ensure_hierarchy_overlay_metadata,  # noqa: F401
    infer_chunk_structure,  # noqa: F401
    normalize_image_metadata,  # noqa: F401
    normalize_section_metadata,  # noqa: F401
)
from app.rag.pipeline_plugins.registry import derive_registered_stage_plugin_ref
from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin, apply_governance_python_plugin  # noqa: F401
from app.rag.preprocessing.markdown_canonical import canonicalize_markdown  # noqa: F401
from app.rag.preprocessing.near_dedup import add_simhashes, find_near_duplicate, with_near_dedup_index
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.processor import GovernanceStats, governance_processor  # noqa: F401
from app.rag.preprocessing.rules import build_governance_rules
from app.rag.preprocessing.simhash import simhash64, simhash64_hex
from app.services.indexer import Indexer
from app.services.metrics_logger import log_metrics, metrics_span, set_metrics_context
from app.services.parse_cache import (
    ParseCacheEntry as RemoteParseCacheEntry,  # noqa: F401
)
from app.services.parse_cache import (
    build_parse_cache_key as build_remote_parse_cache_key,  # noqa: F401
)
from app.services.parse_cache import (
    parse_cache_service,  # noqa: F401
)
from app.services.pipeline_config import (
    build_indexing_options,
    resolve_pipeline_effective,
)
from app.services.tenant_quota_service import TenantQuotaExceededError
from app.storage.object.minio import minio_service
from app.types.document_analytics import compute_document_analytics  # noqa: F401
from app.types.indexing import IndexKind, IndexRecord
from app.types.pipeline import PipelineEffective

logger = get_logger("parsing.document_processor")
RetryCleanupStatus = Literal["applied", "deferred", "invalid"]

LOG_DOC_ID_FMT = '%s document_id=%s'
AUDIT_ACTION_DOCUMENT_QUARANTINE = 'document.quarantine'

_parsed_checkpoint_is_reusable = parsed_checkpoint_is_reusable
_indexed_checkpoint_is_reusable = indexed_checkpoint_is_reusable


def _build_combined_governance_rules(pipeline_effective: PipelineEffective):
    """
    Build the explicit regex-rule list for GovernanceProcessor when rule packs or custom regex rules are enabled.

    When no extra rules are enabled, return None so GovernanceProcessor can reuse its internal defaults.
    """
    extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
    rule_packs = list(getattr(pipeline_effective, "governance_rule_packs", None) or [])
    return build_governance_rules(extra_rules, rule_packs=rule_packs) if (extra_rules or rule_packs) else None


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
    ) -> RetryCleanupStatus:
        return apply_pending_retry_cleanup(
            db,
            db_document=db_document,
            tenant_id=tenant_id,
            document_id=document_id,
            indexer_factory=Indexer,
            parsed_content_model=DocumentParsedContent,
            chunk_model=DocumentChunk,
        )

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

            retry_cleanup_status = self._apply_pending_retry_cleanup(
                db,
                db_document=db_document,
                tenant_id=tenant_id,
                document_id=document_id,
            )
            if retry_cleanup_status == "invalid":
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
            if retry_cleanup_status == "deferred":
                await self._update_status(
                    db,
                    tenant_id,
                    document_id,
                    "failed",
                    0,
                    "failed",
                    error_message="retry_cleanup_deferred",
                )
                return {"status": "failed", "reason": "retry_cleanup_deferred"}

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

            meta0 = dict(db_document.doc_metadata or {})
            if indexed_checkpoint_is_reusable(meta0):
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
                if indexed_chunks:
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
                    meta_patch = _with_stage_durations(meta_patch)
                    await self._update_status(
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
                        index_options=index_options,
                        pipeline_effective=pipeline_effective,
                    )
                    return {
                        "status": "success",
                        "reason": "indexed_checkpoint_resume",
                        "chunk_count": len(indexed_chunks),
                        "total_characters": total_chars,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }

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
                ck_ok = parsed_checkpoint_is_reusable(meta0)
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
                    otel_span_name="ingest.parse",
                    otel_attributes={
                        "ingest.stage": "parse",
                        "document.file_type": str(file_path.suffix.lstrip(".") or "unknown").lower(),
                        "parser.backend_requested": (
                            str(
                                (db_document.doc_metadata or {}).get("parser_backend_requested")
                                or (db_document.doc_metadata or {}).get("parser_backend")
                                or parser_backend
                                or "auto"
                            ).strip().lower()
                            or "auto"
                        ),
                        "chunk.strategy_requested": (
                            str(
                                (db_document.doc_metadata or {}).get("chunk_strategy_requested")
                                or (db_document.doc_metadata or {}).get("chunk_strategy")
                                or chunk_strategy
                                or ""
                            ).strip().lower()
                            or "default"
                        ),
                    },
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
                            meta_patch = record_ingest_gate_outcome(
                                _with_stage_durations(dict(db_document.doc_metadata or {})),
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
                    degraded_meta = record_ingest_gate_outcome(
                        _with_stage_durations(dict(db_document.doc_metadata or {})),
                        gate="parse_quality",
                        outcome="degraded",
                        reason="parse_quality_gate_failed",
                        details={"error": str(exc)[:200]},
                    )
                    db_document.doc_metadata = degraded_meta
                    db.commit()
                    db.refresh(db_document)
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
                            meta = upsert_ingest_checkpoint(
                                meta,
                                stage="parsed",
                                source="document_parsed_contents",
                            )
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
                    otel_span_name="ingest.chunk",
                    otel_attributes={
                        "ingest.stage": "chunk",
                        "document.file_type": str(file_path.suffix.lstrip(".") or "unknown").lower(),
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
                otel_span_name="ingest.index",
                otel_attributes={
                    "ingest.stage": "index",
                    "document.file_type": str(file_path.suffix.lstrip(".") or "unknown").lower(),
                    "index.chunk_vector_enabled": bool(getattr(index_options, "chunk_vector_enabled", True)),
                    "index.bm25_index_enabled": bool(getattr(index_options, "bm25_index_enabled", True)),
                },
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

            with metrics_span(
                "ingest.finalize",
                chunk_count=len(chunks),
                total_characters=total_chars,
                kg_enabled=bool(getattr(pipeline_effective, "kg_enabled", False)),
                otel_span_name="ingest.finalize",
                otel_attributes={
                    "ingest.stage": "finalize",
                    "document.file_type": str(file_path.suffix.lstrip(".") or "unknown").lower(),
                    "pipeline.kg_enabled": bool(getattr(pipeline_effective, "kg_enabled", False)),
                },
            ):
                checkpoint_meta = _with_stage_durations(dict(db_document.doc_metadata or {}))
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
                db_document.doc_metadata = checkpoint_meta
                db.commit()
                db.refresh(db_document)

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

                await run_post_completion_kg(
                    db=db,
                    db_document=db_document,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_ids=chunk_ids,
                    db_chunks=indexed.db_chunks,
                    index_options=index_options,
                    pipeline_effective=pipeline_effective,
                )

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
        except CheckpointedRetryRequiredError as e:
            logger.warning(
                "Document finalization deferred to retry boundary: tenant=%s document=%s reason=%s",
                tenant_id,
                document_id,
                str(e)[:160],
            )
            log_metrics(
                {
                    "event": "ingest.retry_boundary",
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "reason": str(e)[:160],
                }
            )
            return {"status": "failed", "reason": str(e)}
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
            meta_patch = record_ingest_gate_outcome(
                _with_stage_durations(meta_patch),
                gate="tenant_quota",
                outcome="closed",
                reason=f"tenant_quota_exceeded:{quota_key}",
                details=dict(getattr(e, "meta", None) or {}),
            )

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
            audit_ingest_gate(
                db,
                tenant_id=tenant_id,
                db_document=db_document,
                gate="tenant_quota",
                outcome="closed",
                reason=f"tenant_quota_exceeded:{quota_key}",
                details=dict(getattr(e, "meta", None) or {}),
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
        criticality: str = "best_effort",
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
                criticality=criticality,
            )
        except Exception as exc:
            if str(criticality or "").strip().lower() == "required":
                raise
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
            criticality = str(
                kwargs.pop("ingestion_run_criticality", None)
                or resolve_ingestion_run_update_criticality(db_doc, status_norm=status_norm)
            ).strip().lower()
            self._apply_status_update_fields(
                db_doc,
                status=status,
                progress=progress,
                stage=stage,
                extra_fields=kwargs,
            )

            if status_norm in {"pending", "completed", "cancelled"}:
                self._clear_failure_retry_fields(db_doc)

            if criticality == "required":
                try:
                    self._notify_ingestion_run_status(
                        db,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        status=status,
                        db_doc=db_doc,
                        criticality=criticality,
                    )
                except Exception as exc:
                    if checkpoint_stage(dict(getattr(db_doc, "doc_metadata", None) or {})) == "indexed":
                        persist_retry_boundary_failure(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            reason="ingestion_run_status_update_failed",
                            error=exc,
                        )
                    raise

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
            if criticality != "required":
                self._notify_ingestion_run_status(
                    db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    status=status,
                    db_doc=db_doc,
                    criticality=criticality,
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
            "document_questions",
            "document_questions_generation",
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
