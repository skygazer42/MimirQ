"""
Document processing service - core processing flow.
"""
import asyncio
import base64
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
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
from app.parsing.artifact_stats import POSITION_TAG_RE, compute_parsing_artifact_stats  # noqa: F401
from app.parsing.enrich.chart_to_data import add_chart_data_blocks  # noqa: F401
from app.parsing.enrich.formula_ocr import add_formula_latex_blocks  # noqa: F401
from app.parsing.enrich.image_caption import add_image_captions  # noqa: F401
from app.parsing.enrich.image_code import add_image_code_blocks  # noqa: F401
from app.parsing.enrich.vlm_image_caption import add_vlm_image_captions  # noqa: F401
from app.parsing.errors import ParsingError  # noqa: F401
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
from app.parsing.processors.support.process_document_flow import (
    handle_asyncio_cancelled,
    handle_document_cancelled,
    handle_process_document_failure,
    handle_retry_boundary_failure,
    handle_tenant_quota_exceeded,
    run_process_document_body,
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
    checkpoint_stage,
    indexed_checkpoint_is_reusable,
    parsed_checkpoint_is_reusable,
    persist_retry_boundary_failure,
    resolve_ingestion_run_update_criticality,
)
from app.parsing.processors.support.recovery import (
    maybe_enrich_document_questions as _maybe_enrich_document_questions,
)
from app.parsing.processors.support.recovery import (
    run_post_completion_kg as _run_post_completion_kg,
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
from app.parsing.routing import route_pdf_backend, should_attempt_pdf_fallback  # noqa: F401
from app.parsing.subprocess_runner import SubprocessCancelled, run_parser_subprocess  # noqa: F401
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
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.processor import GovernanceStats, governance_processor  # noqa: F401
from app.rag.preprocessing.rules import build_governance_rules
from app.services.indexer import Indexer
from app.services.metrics_logger import log_metrics as _log_metrics
from app.services.metrics_logger import metrics_span as _metrics_span
from app.services.parse_cache import (
    ParseCacheEntry as RemoteParseCacheEntry,  # noqa: F401
)
from app.services.parse_cache import (
    build_parse_cache_key as build_remote_parse_cache_key,  # noqa: F401
)
from app.services.parse_cache import (
    parse_cache_service,  # noqa: F401
)
from app.services.pipeline_config import build_indexing_options as _build_indexing_options
from app.services.pipeline_config import resolve_pipeline_effective as _resolve_pipeline_effective
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
metrics_span = _metrics_span
log_metrics = _log_metrics
resolve_pipeline_effective = _resolve_pipeline_effective
build_indexing_options = _build_indexing_options
maybe_enrich_document_questions = _maybe_enrich_document_questions
run_post_completion_kg = _run_post_completion_kg


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

        runtime_state: dict[str, Any] = {"preprocessed_temp_path": None, "parse_state": None}
        try:
            return await run_process_document_body(
                self,
                db=db,
                file_path=file_path,
                document_id=document_id,
                tenant_id=tenant_id,
                parser_backend=parser_backend,
                chunk_strategy=chunk_strategy,
                runtime_state=runtime_state,
                parsing_stage_factory=ParsingStage,
                inline_asset_stage_factory=InlineAssetStage,
                normalize_stage_factory=NormalizeStage,
                governance_stage_factory=GovernanceStage,
                chunking_stage_factory=ChunkingStage,
                chunk_dedup_stage_factory=ChunkDedupStage,
                chunk_asset_stage_factory=ChunkAssetStage,
                index_stage_factory=IndexStage,
            )

        except DocumentCancelledError as e:
            return await handle_document_cancelled(
                self,
                db=db,
                db_document=runtime_state.get("db_document"),
                tenant_id=tenant_id,
                document_id=document_id,
                error=e,
                with_stage_durations=runtime_state.get("with_stage_durations", lambda meta: dict(meta or {})),
            )
        except asyncio.CancelledError:
            await handle_asyncio_cancelled(
                self,
                db=db,
                db_document=runtime_state.get("db_document"),
                tenant_id=tenant_id,
                document_id=document_id,
                with_stage_durations=runtime_state.get("with_stage_durations", lambda meta: dict(meta or {})),
            )
            raise
        except CheckpointedRetryRequiredError as e:
            return handle_retry_boundary_failure(tenant_id=tenant_id, document_id=document_id, error=e)
        except TenantQuotaExceededError as e:
            return await handle_tenant_quota_exceeded(
                self,
                db=db,
                db_document=runtime_state.get("db_document"),
                tenant_id=tenant_id,
                document_id=document_id,
                error=e,
                with_stage_durations=runtime_state.get("with_stage_durations", lambda meta: dict(meta or {})),
                resolved_backend=(runtime_state.get("parse_state").resolved_backend if runtime_state.get("parse_state") is not None else None),
                resolved_chunk_strategy=(
                    runtime_state.get("parse_state").resolved_chunk_strategy if runtime_state.get("parse_state") is not None else None
                ),
            )
        except Exception as e:
            await handle_process_document_failure(
                self,
                db=db,
                db_document=runtime_state.get("db_document"),
                tenant_id=tenant_id,
                document_id=document_id,
                error=e,
                with_stage_durations=runtime_state.get("with_stage_durations", lambda meta: dict(meta or {})),
            )
            raise
        finally:
            preprocessed_temp_path = runtime_state.get("preprocessed_temp_path")
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

    @staticmethod
    def _llm_auto_tagging_source_text(items: list[Document], *, max_chars: int) -> str:
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
        return "\n\n".join(text_parts).strip()

    @staticmethod
    def _collect_llm_auto_tagging_values(result: Any, *, max_items: int) -> tuple[list[str], list[str], list[dict[str, Any]]]:
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
        return tag_values, keyword_values, structured_tags

    @staticmethod
    def _apply_llm_auto_tagging_metadata(
        first: Document,
        *,
        result: Any,
        tag_values: list[str],
        keyword_values: list[str],
        structured_tags: list[dict[str, Any]],
        max_items: int,
    ) -> dict[str, Any]:
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
        source_text = self._llm_auto_tagging_source_text(items, max_chars=max_chars)
        if not source_text:
            return {"enabled": True, "used": False, "reason": "empty_text"}

        try:
            from app.rag.preprocessing.llm_tagger import extract_llm_tags

            result = await extract_llm_tags(text=source_text, max_chars=max_chars, max_items=max_items)
        except Exception as exc:  # noqa: BLE001
            _log_processor_fallback('_apply_llm_auto_tagging', exc)
            return {"enabled": True, "used": False, "error": str(exc)[:160]}

        tag_values, keyword_values, structured_tags = self._collect_llm_auto_tagging_values(
            result,
            max_items=max_items,
        )
        if not tag_values and not keyword_values and not structured_tags:
            return {"enabled": True, "used": False, "provider": getattr(result, "provider", "llm")}

        return self._apply_llm_auto_tagging_metadata(
            items[0],
            result=result,
            tag_values=tag_values,
            keyword_values=keyword_values,
            structured_tags=structured_tags,
            max_items=max_items,
        )

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
