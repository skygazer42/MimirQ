"""Document pipeline helpers; the processing entry lives in support.process_document_flow."""

import asyncio
import base64
import datetime as dt
import hashlib
import re
import shutil
import time
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from langchain_core.documents import Document
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata
from app.parsing.processors.support.chunk_postprocess import (
    _optional_int,
)
from app.parsing.processors.support.common import (
    _PROCESSOR_CLEANUP_LOG_MESSAGE,
    MIMIRQ_PARSE_DIRNAME,
    _log_processor_fallback,
)
from app.parsing.processors.support.quality import (
    _aggregate_governance_quality,
    _clean_governance_rule_packs,
    _governance_reduction_pct,
    _is_table_segment_metadata,
    _positive_governance_counts,
)
from app.parsing.processors.support.recovery import (
    checkpoint_stage,
    persist_retry_boundary_failure,
    resolve_ingestion_run_update_criticality,
)
from app.parsing.processors.support.results import (
    ChunkPostprocessStats,
    IndexResult,
)
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.registry import derive_registered_stage_plugin_ref
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.processor import GovernanceStats
from app.services.indexer import Indexer
from app.storage.object.minio import minio_service
from app.types.indexing import IndexingOptions, IndexKind, IndexRecord
from app.types.pipeline import PipelineEffective

if TYPE_CHECKING:
    from app.rag.preprocessing.llm_tagger import LLMTaggingResult
    from app.services.table_store_service import TableAsset

logger = get_logger("parsing.document_processor")


def index_chunks(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    file_path: Path,
    default_source: str,
    chunks: list[Document],
    options: IndexingOptions,
) -> IndexResult:
    logger.info("Persisting chunks and indexes...")
    records: list[IndexRecord] = []
    for chunk in chunks:
        meta = dict(chunk.metadata or {})
        content = normalize_text(chunk.page_content, normalize_line_endings=True, remove_control_chars=True)
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

    persist_result = (
        Indexer(db)
        .upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=default_source.strip() or str(file_path.name),
            commit=False,
            options=options,
        )
        .chunk_result
    )
    if persist_result is None:
        raise RuntimeError("Chunk indexing returned no result")
    return IndexResult(
        chunk_ids=persist_result.chunk_ids,
        total_characters=persist_result.total_characters,
        db_chunks=persist_result.db_chunks,
    )


__all__ = ("INTEGRATED_PIPELINE_STRATEGIES", "chunk_integrated_file", "index_chunks", "update_document_status")


INTEGRATED_PIPELINE_STRATEGIES = {"integrated_naive", "integrated_book", "integrated_laws", "integrated_email"}


def _build_cancel_check(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    poll_interval_sec: float = 1.0,
):
    """
    Build a cached cancel-check closure.

    This is shared by:
    - document ingestion flow
    - parsing subprocess runner
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
        status = db_doc.status.lower()
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
        active_hash = meta.get("active_pipeline_hash")
        cur_hash = meta.get("pipeline_hash")
        if active_hash is not None:
            active_hash = active_hash.strip()
        if cur_hash is not None:
            cur_hash = cur_hash.strip()
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


def _status_update_cancel_blocked(db_doc: DBDocument, status: str) -> bool:
    status_norm = str(status).lower()
    current_status = db_doc.status.lower()
    if current_status == "cancelled" and status_norm != "cancelled":
        return True
    meta = db_doc.doc_metadata or {}
    return isinstance(meta, dict) and bool(meta.get("cancel_requested")) and status_norm != "cancelled"


def _clear_failure_retry_fields(db_doc: DBDocument) -> None:
    db_doc.failed_stage = None
    db_doc.error_code = None
    db_doc.next_retry_at = None


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


def _record_ingest_dead_letter_for_status(
    db: Session,
    *,
    db_doc: DBDocument,
    status_norm: str,
    stage: str,
    prev_stage: str | None,
    failed_stage_hint: Any,
    error_code_hint: Any,
) -> None:
    if status_norm not in {"failed", "quarantined"}:
        return
    try:
        from app.services.ingest_dead_letter_service import record_ingest_dead_letter

        raw_stage = next((value for value in (failed_stage_hint, prev_stage, stage) if value is not None), None)
        failed_stage = (str(raw_stage).strip() or None) if raw_stage is not None else None
        record_ingest_dead_letter(
            db,
            document=db_doc,
            failed_stage=failed_stage,
            error_code=(str(error_code_hint).strip() if error_code_hint else None),
            error_message=db_doc.error_message,
            original_payload={
                "status": status_norm,
                "stage": stage,
                "previous_stage": prev_stage,
            },
        )
    except Exception as exc:
        logger.debug("Ignoring non-critical ingest DLQ write failure: %s", exc)


def _adjust_processing_stage_metric(
    *,
    current_status: str,
    prev_stage: str | None,
    status: str,
    stage: str,
) -> None:
    try:
        from app.services.ingestion_prometheus_metrics import adjust_processing_stage_gauge

        adjust_processing_stage_gauge(
            prev_status=current_status,
            prev_stage=prev_stage,
            new_status=status,
            new_stage=stage,
        )
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


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
        from app.services import ingestion_run_service

        doc_meta = db_doc.doc_metadata
        ingestion_run_service.on_document_status_update(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            new_status=status,
            error_message=db_doc.error_message,
            doc_meta=(dict(doc_meta or {}) if isinstance(doc_meta, dict) else None),
            criticality=criticality,
        )
    except Exception as exc:
        if criticality.strip().lower() == "required":
            raise
        logger.warning(
            "Ingestion run notification failed: tenant_id=%s document_id=%s error_type=%s",
            tenant_id,
            document_id,
            type(exc).__name__,
        )


async def update_document_status(
    db: Session, tenant_id: UUID, document_id: UUID, status: str, progress: int, stage: str, **kwargs
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
        current_status = db_doc.status.lower()
        if _status_update_cancel_blocked(db_doc, status):
            return

        prev_stage = db_doc.current_stage
        status_norm = status.strip().lower()
        failed_stage_hint = kwargs.pop("failed_stage", None)
        error_code_hint = kwargs.pop("error_code", None)
        criticality = (
            str(
                kwargs.pop("ingestion_run_criticality", None)
                or resolve_ingestion_run_update_criticality(db_doc, status_norm=status_norm)
            )
            .strip()
            .lower()
        )
        if criticality not in {"best_effort", "required"}:
            raise ValueError("criticality must be required or best_effort")
        _apply_status_update_fields(
            db_doc,
            status=status,
            progress=progress,
            stage=stage,
            extra_fields=kwargs,
        )

        if status_norm in {"pending", "completed", "cancelled"}:
            _clear_failure_retry_fields(db_doc)

        if criticality == "required":
            try:
                _notify_ingestion_run_status(
                    db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    status=status,
                    db_doc=db_doc,
                    criticality=criticality,
                )
            except Exception as exc:
                if checkpoint_stage(dict(db_doc.doc_metadata or {})) == "indexed":
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
        _record_ingest_dead_letter_for_status(
            db,
            db_doc=db_doc,
            status_norm=status_norm,
            stage=stage,
            prev_stage=prev_stage,
            failed_stage_hint=failed_stage_hint,
            error_code_hint=error_code_hint,
        )
        _adjust_processing_stage_metric(
            current_status=current_status,
            prev_stage=prev_stage,
            status=status,
            stage=stage,
        )
        if criticality != "required":
            _notify_ingestion_run_status(
                db,
                tenant_id=tenant_id,
                document_id=document_id,
                status=status,
                db_doc=db_doc,
                criticality=criticality,
            )


def _record_processing_metadata(
    db: Session, tenant_id: UUID, document_id: UUID, parser_backend: str, chunk_strategy: str
):
    """Ensure document metadata records the final parser selection."""
    db_doc = (
        db.query(DBDocument)
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )

    if not db_doc:
        return

    metadata = dict(db_doc.doc_metadata or {})
    metadata["parser_backend"] = parser_backend
    metadata["chunk_strategy"] = chunk_strategy

    db_doc.doc_metadata = metadata
    db.commit()
    db.refresh(db_doc)


def _parsed_table_input_from_document(doc: Document, *, table_index: int) -> dict[str, Any] | None:
    meta = doc.metadata
    if not _is_table_segment_metadata(meta):
        return None
    markdown = doc.page_content
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


def _collect_parsed_table_inputs(documents: list[Document]) -> list[dict[str, Any]]:
    table_inputs: list[dict[str, Any]] = []
    for doc in documents or []:
        table_input = _parsed_table_input_from_document(doc, table_index=len(table_inputs))
        if table_input is None:
            continue
        table_inputs.append(table_input)
        if len(table_inputs) >= 500:
            break
    return table_inputs


def _import_table_store_assets(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    table_inputs: list[dict[str, Any]],
    pipeline_effective: PipelineEffective,
) -> list["TableAsset"] | None:
    try:
        from app.services.table_store_service import import_markdown_tables

        return import_markdown_tables(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            tables=table_inputs,
            max_rows=int(pipeline_effective.table_store_max_rows or 0),
            max_cols=int(pipeline_effective.table_store_max_cols or 0),
            sample_rows=int(pipeline_effective.table_store_sample_rows or 0),
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Parsed table import failed (ignored): %s document_id=%s", str(exc)[:200], document_id)
        return None


def _parsed_table_asset_payload(asset: "TableAsset", source_info: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "table_id": asset.table_id,
        "sheet_index": asset.sheet_index,
        "sheet_name": asset.sheet_name,
        "row_count": asset.row_count,
        "col_count": asset.col_count,
        "truncated": asset.truncated,
        "columns": list(asset.columns),
        "sample_rows": list(asset.sample_rows),
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


def _parsed_table_assets_payload(
    *,
    assets: list["TableAsset"],
    table_inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tables_payload: list[dict[str, Any]] = []
    for idx, asset in enumerate(assets or []):
        source_info = table_inputs[idx] if idx < len(table_inputs) else {}
        tables_payload.append(_parsed_table_asset_payload(asset, source_info))
    return tables_payload


def _parsed_table_store_source_ext(db_document: DBDocument) -> str | None:
    source_ext = db_document.file_type
    return f".{str(source_ext).lower().lstrip('.')}" if source_ext else None


def _apply_parsed_table_store_metadata(
    *,
    metadata: dict[str, Any],
    db_document: DBDocument,
    assets: list["TableAsset"],
    table_inputs: list[dict[str, Any]],
    pipeline_effective: PipelineEffective,
) -> dict[str, Any]:
    if not assets:
        existing = metadata.get("table_store")
        source_ext = existing.get("source_ext") if isinstance(existing, dict) else None
        if isinstance(source_ext, str) and source_ext.lower() == ".pdf":
            metadata.pop("table_store", None)
        return metadata

    exclusive_enabled = bool(pipeline_effective.table_store_sidecar_exclusive_routing)
    metadata["table_store"] = {
        "version": "1",
        "source_ext": _parsed_table_store_source_ext(db_document),
        "imported_at": dt.datetime.now(dt.UTC).isoformat(),
        "routing": {
            "kind": "tag_sidecar",
            "source": "parser_table_segments",
            "exclusive_rag_routing_enabled": exclusive_enabled,
        },
        "tables": _parsed_table_assets_payload(assets=assets, table_inputs=table_inputs),
    }
    return metadata


def _persist_parsed_table_store_metadata(
    db: Session,
    *,
    db_document: DBDocument,
    assets: list["TableAsset"],
    table_inputs: list[dict[str, Any]],
    pipeline_effective: PipelineEffective,
) -> None:
    try:
        next_meta = _apply_parsed_table_store_metadata(
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
        logger.info(
            "Failed to persist parsed table_store metadata (ignored): %s document_id=%s",
            str(exc)[:200],
            db_document.id,
        )


def _import_parsed_markdown_tables_to_store(
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
    if not bool(pipeline_effective.table_store_enabled):
        return 0

    dataset_id = db_document.dataset_id
    document_id = db_document.id
    if dataset_id is None or document_id is None:
        return 0

    table_inputs = _collect_parsed_table_inputs(documents)
    if not table_inputs:
        return 0

    assets = _import_table_store_assets(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        table_inputs=table_inputs,
        pipeline_effective=pipeline_effective,
    )
    if assets is None:
        return 0

    _persist_parsed_table_store_metadata(
        db,
        db_document=db_document,
        assets=assets,
        table_inputs=table_inputs,
        pipeline_effective=pipeline_effective,
    )
    return len(assets)


def _table_sidecar_excluded_sample(*, index: int, meta: dict[str, Any]) -> dict[str, Any]:
    page = _optional_int(meta.get("page"))
    return {
        "chunk_index": int(index),
        "page": page,
        "content_type": meta.get("content_type"),
        "doc_type_kwd": meta.get("doc_type_kwd"),
    }


def _mark_table_sidecar_routing(meta: dict[str, Any]) -> None:
    meta.setdefault("table_routing_kind", "tag_sidecar")
    meta.setdefault("table_routing_source", "parser_table_segment")


def _mark_non_table_rag_routing(meta: dict[str, Any]) -> None:
    meta.setdefault("table_routing_kind", "rag_text")
    meta.setdefault("table_routing_source", "non_table_content")
    meta.setdefault("table_rag_excluded", False)
    meta.setdefault("table_rag_exclusion_reason", None)


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
            _mark_non_table_rag_routing(meta)
            chunk.metadata = meta
        return False, False

    _mark_table_sidecar_routing(meta)
    if should_exclude:
        if len(excluded_samples) < 20:
            excluded_samples.append(_table_sidecar_excluded_sample(index=index, meta=meta))
        return True, True

    meta["table_rag_excluded"] = False
    meta["table_rag_exclusion_reason"] = None
    chunk.metadata = meta
    return True, False


def _apply_table_sidecar_exclusive_routing(
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
        is_table, excluded = _route_table_sidecar_chunk(
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

    return kept, _build_table_sidecar_audit(
        enabled=enabled,
        imported=imported,
        table_seen=table_seen,
        table_excluded=table_excluded,
        excluded_samples=excluded_samples,
    )


def _cleanup_parser_artifacts(artifact_dirs: set[str], *, tenant_id: UUID) -> None:
    if not artifact_dirs:
        return
    if bool(settings.MAGIC_PDF_KEEP_ARTIFACTS):
        return

    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)

    for raw in sorted(artifact_dirs):
        try:
            path = Path(raw).resolve(strict=False)
            if not path.exists():
                continue
            if not any(
                p in path.parts
                for p in {
                    ".magicpdf",
                    ".deepseek_ocr",
                    ".qianfan_ocr",
                    ".etl4llm",
                    ".marker",
                    ".paddlevl",
                    ".olmocr",
                    MIMIRQ_PARSE_DIRNAME,
                }
            ):
                continue
            # Safety: only delete within this tenant's upload directory.
            path.relative_to(tenant_root)
        except Exception:
            logger.warning("Skipping unsafe parser artifact cleanup: %s", str(raw)[:200])
            continue

        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception as exc:
            _log_processor_fallback("_cleanup_parser_artifacts", exc)


def _record_pipeline_effective(
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    effective: PipelineEffective,
) -> None:
    """Persist effective pipeline settings on the document metadata."""
    db_doc = (
        db.query(DBDocument)
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )

    if not db_doc:
        return

    kg_python_plugin = effective.kg_python_plugin.strip()
    if not kg_python_plugin:
        kg_python_plugin = derive_registered_stage_plugin_ref(
            effective.chunk_python_plugin.strip(),
            "kg",
        )
    kg_python_params = dict(effective.kg_python_params or {})
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
        "governance_python_plugin": effective.governance_python_plugin,
        "governance_python_params": dict(effective.governance_python_params or {}),
        "governance_llm_auto_tagging_enabled": bool(effective.governance_llm_auto_tagging_enabled),
        "governance_llm_auto_tagging_max_chars": int(effective.governance_llm_auto_tagging_max_chars or 3000),
        "governance_llm_auto_tagging_max_items": int(effective.governance_llm_auto_tagging_max_items or 16),
        "ingest_pre_poc_scanner_enabled": bool(effective.ingest_pre_poc_scanner_enabled),
        "ingest_pre_poc_quality_gate_mode": str(effective.ingest_pre_poc_quality_gate_mode or "warn"),
        "chunk_size": int(effective.chunk_size),
        "chunk_overlap": int(effective.chunk_overlap),
        "chunk_merge_small_min_chars": int(effective.chunk_merge_small_min_chars or 0),
        "chunk_strategy_params": dict(effective.chunk_strategy_params or {}),
        "chunk_python_plugin": effective.chunk_python_plugin,
        "chunk_python_params": dict(effective.chunk_python_params or {}),
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
        raw = text
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
        "original": {
            "raw_len": int(orig_raw_len),
            "stored_len": int(orig_stored_len),
            "truncated": bool(orig_is_trunc),
        },
        "cleaned": {
            "raw_len": int(clean_raw_len),
            "stored_len": int(clean_stored_len),
            "truncated": bool(clean_is_trunc),
        },
    }


def _build_governance_audit_metadata_patch(
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

    before = list((before_items if before_items is not None else []))
    after = list((after_items if after_items is not None else []))

    original_chars = sum(len(d.page_content) for d in before)
    cleaned_chars = sum(len(d.page_content) for d in after)
    patch: dict[str, Any] = {
        "governance_char_stats": {
            "original_chars": int(max(0, original_chars)),
            "cleaned_chars": int(max(0, cleaned_chars)),
            "reduction_pct": int(
                max(
                    0,
                    min(
                        100,
                        _governance_reduction_pct(
                            original_chars=original_chars,
                            cleaned_chars=cleaned_chars,
                        ),
                    ),
                )
            ),
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
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    stats: GovernanceStats,
    rule_packs: list[str] | None = None,
    audit_patch: dict[str, Any] | None = None,
) -> None:
    """Persist governance stats on the document metadata."""
    db_doc = (
        db.query(DBDocument)
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )

    if not db_doc:
        return

    metadata = dict(db_doc.doc_metadata or {})
    metadata["governance_enabled"] = True
    metadata["governance_version"] = str(stats.version or metadata.get("governance_version") or "1")
    metadata["governance_documents"] = int(stats.documents)
    metadata["governance_changed_documents"] = int(stats.changed)
    metadata["governance_rules_applied"] = int(stats.applied_rules)
    metadata["governance_dropped_documents"] = int(stats.dropped or 0)

    drop_reasons = stats.drop_reasons
    if drop_reasons:
        metadata["governance_drop_reasons"] = drop_reasons
    pii_hits = stats.pii_hits
    if pii_hits:
        metadata["governance_pii_hits"] = pii_hits
    secrets_hits = stats.secrets_hits
    if secrets_hits:
        metadata["governance_secrets_hits"] = secrets_hits

    # Persist richer "effects" counters for dataset-level governance audit (best-effort).
    metadata.update(_positive_governance_counts(stats))

    languages = stats.languages
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


def _add_limited_string_values(target: set[str], values: Any, *, max_len: int) -> None:
    if not isinstance(values, list):
        return
    for item in values:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value:
            target.add(value[:max_len])


def _update_governance_frontmatter_and_title(state: dict[str, Any], meta: dict[str, Any]) -> None:
    if state["frontmatter"] is None:
        frontmatter = meta.get("document_frontmatter")
        if isinstance(frontmatter, dict) and frontmatter:
            state["frontmatter"] = frontmatter

    if state["title"] is None:
        raw_title = meta.get("document_title")
        if isinstance(raw_title, str) and raw_title.strip():
            state["title"] = raw_title.strip()[:200]


def _update_governance_keyword_provider(state: dict[str, Any], meta: dict[str, Any]) -> None:
    if state["keywords_provider"] is not None:
        return
    raw_provider = meta.get("document_keywords_provider")
    if isinstance(raw_provider, str) and raw_provider.strip():
        state["keywords_provider"] = raw_provider.strip()[:50]


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


def _update_governance_enrichment_state(state: dict[str, Any], meta: dict[str, Any]) -> None:
    _update_governance_frontmatter_and_title(state, meta)
    _add_limited_string_values(state["tags"], meta.get("document_tags"), max_len=64)
    _add_limited_string_values(
        state["keywords"],
        meta.get("document_keywords"),
        max_len=64,
    )
    _update_governance_keyword_provider(state, meta)
    _update_governance_language_state(state, meta)


def _build_governance_enrichment_payload(state: dict[str, Any]) -> dict[str, object]:
    enrichment: dict[str, object] = {}
    if state["title"]:
        enrichment["title"] = state["title"]
    if state["tags"]:
        enrichment["tags"] = sorted(state["tags"])
    lang_counts = state["lang_counts"]
    if lang_counts:
        language = min(lang_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        enrichment["language"] = language
        if state["conf_n"] > 0:
            enrichment["language_confidence"] = round(state["conf_sum"] / state["conf_n"], 3)
    if state["keywords"]:
        enrichment["keywords"] = sorted(state["keywords"])
        enrichment["keywords_provider"] = state["keywords_provider"] or "auto"
    if state["frontmatter"]:
        enrichment["frontmatter"] = state["frontmatter"]
    return enrichment


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
        _update_governance_enrichment_state(state, doc.metadata)
    return _build_governance_enrichment_payload(state)


def _llm_auto_tagging_source_text(items: list[Document], *, max_chars: int) -> str:
    text_parts: list[str] = []
    remaining = max_chars
    for item in items:
        content = item.page_content.strip()
        if not content:
            continue
        text_parts.append(content[:remaining])
        remaining -= min(len(content), remaining)
        if remaining <= 0:
            break
    return "\n\n".join(text_parts).strip()


def _collect_llm_auto_tagging_values(
    result: "LLMTaggingResult", *, max_items: int
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    tag_values: list[str] = []
    keyword_values: list[str] = []
    structured_tags: list[dict[str, Any]] = []
    for tag in result.document_tags[:max_items]:
        value = tag.value.strip()
        if not value:
            continue
        tag_type = tag.type.strip()
        if tag_type == "keyword":
            keyword_values.append(value)
        else:
            tag_values.append(value)
        structured_tags.append(tag.model_dump())
    return tag_values, keyword_values, structured_tags


def _apply_llm_auto_tagging_metadata(
    first: Document,
    *,
    result: "LLMTaggingResult",
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
    summary = result.summary.strip() if result.summary is not None else ""
    if summary:
        meta["document_llm_auto_summary"] = summary[:1000]
    meta["document_llm_auto_tagging"] = {
        "enabled": True,
        "used": True,
        "provider": result.provider,
        "tag_count": len(meta["document_tags"]),
        "keyword_count": len(meta.get("document_keywords") or []),
    }
    first.metadata = meta
    return dict(meta["document_llm_auto_tagging"])


async def _apply_llm_auto_tagging(
    items: list[Document] | None,
    *,
    pipeline_effective: PipelineEffective,
) -> dict[str, Any] | None:
    if not items or not bool(pipeline_effective.governance_llm_auto_tagging_enabled):
        return None
    max_chars = max(200, int(pipeline_effective.governance_llm_auto_tagging_max_chars or 3000))
    max_items = max(1, int(pipeline_effective.governance_llm_auto_tagging_max_items or 16))
    source_text = _llm_auto_tagging_source_text(items, max_chars=max_chars)
    if not source_text:
        return {"enabled": True, "used": False, "reason": "empty_text"}

    try:
        from app.rag.preprocessing.llm_tagger import extract_llm_tags

        result = await extract_llm_tags(text=source_text, max_chars=max_chars, max_items=max_items)
    except Exception as exc:  # noqa: BLE001
        _log_processor_fallback("_apply_llm_auto_tagging", exc)
        return {"enabled": True, "used": False, "error": str(exc)[:160]}

    tag_values, keyword_values, structured_tags = _collect_llm_auto_tagging_values(
        result,
        max_items=max_items,
    )
    if not tag_values and not keyword_values and not structured_tags:
        return {"enabled": True, "used": False, "provider": result.provider}

    return _apply_llm_auto_tagging_metadata(
        items[0],
        result=result,
        tag_values=tag_values,
        keyword_values=keyword_values,
        structured_tags=structured_tags,
        max_items=max_items,
    )


def _record_governance_enrichment_metadata(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    items: list[Document] | None,
) -> None:
    if not items:
        return

    db_doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not db_doc:
        return

    enrichment = _collect_governance_enrichment_payload(items)
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
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    selected_counts: dict[str, int],
) -> None:
    """Persist auto-chunk selection stats on the document metadata."""
    db_doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
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
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    stats: ChunkPostprocessStats,
) -> None:
    """Persist chunk postprocessing stats (dedup/truncation) on the document metadata."""
    db_doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not db_doc:
        return

    metadata = dict(db_doc.doc_metadata or {})
    metadata["chunk_postprocess"] = {
        "merge_small_enabled": stats.merge_small_enabled,
        "merge_small_min_chars": stats.merge_small_min_chars,
        "merge_small_before": stats.merge_small_before,
        "merge_small_after": stats.merge_small_after,
        "merge_small_reduced": stats.merge_small_reduced,
        "dedup_enabled": stats.dedup_enabled,
        "dedup_dropped": stats.dedup_dropped,
        "max_chunks_per_document": stats.max_chunks_per_document,
        "max_chunks_strategy": stats.max_chunks_strategy.strip() or "head",
        "truncated": bool(stats.truncated_dropped > 0),
        "truncated_from": stats.truncated_from,
        "truncated_to": stats.truncated_to,
        "truncated_dropped": stats.truncated_dropped,
        "truncated_asset_total": stats.truncated_asset_total,
        "truncated_asset_kept": stats.truncated_asset_kept,
    }
    db_doc.doc_metadata = metadata
    db.commit()
    db.refresh(db_doc)


def _chunk_coverage_range(chunk: Document) -> tuple[int, int] | None:
    meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
    start = _optional_int(meta.get("start_char"))
    if start is None:
        return None
    end = _optional_int(meta.get("end_char"))
    if end is None:
        end = start + len(chunk.page_content)
    if end <= start:
        return None
    return start, end


def _chunk_coverage_ranges(chunks: list[Document]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for chunk in chunks:
        text_range = _chunk_coverage_range(chunk)
        if text_range is not None:
            ranges.append(text_range)
    return ranges


def _chunk_quality_gate_inputs(
    *,
    stats: dict[str, Any] | None,
    coverage: dict[str, float | int] | None,
) -> dict[str, float | int]:
    def int_metric(source: dict[str, Any] | None, key: str) -> int:
        return int((source if source is not None else {}).get(key) or 0) if isinstance(source, dict) else 0

    def float_metric(source: dict[str, Any] | None, key: str) -> float:
        return float((source if source is not None else {}).get(key) or 0.0) if isinstance(source, dict) else 0.0

    return {
        "count": int_metric(stats, "count"),
        "short_count": int_metric(stats, "short_count"),
        "duplicate_count": int_metric(stats, "duplicate_count"),
        "covered_chars": int_metric(coverage, "covered_chars"),
        "coverage_ratio": float_metric(coverage, "coverage_ratio"),
        "overlap_waste_ratio": float_metric(coverage, "overlap_waste_ratio"),
        "gap_count": int_metric(coverage, "gap_count"),
    }


def _compute_chunk_quality_gate_metadata(
    *,
    metadata: dict[str, Any],
    stats: dict[str, Any] | None,
    coverage: dict[str, float | int] | None,
    chunks_count: int,
    total_chars: int,
) -> tuple[dict[str, object] | None, list[str], list[dict[str, object]]]:
    from app.services.chunk_quality_gate import compute_chunk_quality_gate

    try:
        effective = metadata.get("pipeline_effective") if isinstance(metadata.get("pipeline_effective"), dict) else {}
        gate_raw, recs_raw, patches_raw = compute_chunk_quality_gate(
            stats=_chunk_quality_gate_inputs(stats=stats, coverage=coverage),
            total_chunks=int(chunks_count),
            total_characters=total_chars,
            chunk_size=int(effective.get("chunk_size") or 0),
            chunk_overlap=int(effective.get("chunk_overlap") or 0),
            original_text_included=False,
            original_text_truncated=False,
            original_text_max_chars=0,
        )
        gate = gate_raw if isinstance(gate_raw, dict) else None
        recs = [str(x) for x in (recs_raw or []) if x.strip()]
        patches = [p for p in (patches_raw or []) if isinstance(p, dict)]
        return gate, recs, patches
    except Exception as exc:
        _log_processor_fallback("_record_chunking_stats_metadata", exc)
        return None, [], []


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

    db_doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not db_doc:
        return

    from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges
    from app.services.chunking_stats_utils import (
        compute_chunking_stats_from_texts,
        compute_chunking_stats_from_texts_tokens,
    )

    stats = compute_chunking_stats_from_texts(
        ((c.page_content) for c in chunks),
        short_threshold=int(short_threshold or 0),
    )
    token_stats = compute_chunking_stats_from_texts_tokens(((c.page_content) for c in chunks))

    # Best-effort chunk coverage metrics (requires offsets).
    ranges = _chunk_coverage_ranges(chunks)
    total_chars = int((total_characters if total_characters is not None else 0)) or int(
        getattr(db_doc, "total_characters", 0) or 0
    )
    coverage: dict[str, float | int] | None = None
    if ranges and total_chars > 0:
        coverage = compute_chunk_coverage_metrics_from_ranges(
            ranges,
            total_characters=total_chars,
        )

    metadata = dict(db_doc.doc_metadata or {})
    # Quality gate (heuristics; same as preview but best-effort here).
    gate, recs, patches = _compute_chunk_quality_gate_metadata(
        metadata=metadata,
        stats=stats,
        coverage=coverage,
        chunks_count=len(chunks),
        total_chars=total_chars,
    )
    _apply_chunking_stats_metadata(
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


def _record_document_image_ids(db: Session, tenant_id: UUID, document_id: UUID, img_ids: set[str]):
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

    db_doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
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


def _extract_img_id_from_content(content: str) -> str | None:
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
    img_id = m.group(1).strip()
    return img_id if img_id else None


def _inline_image_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    return (
        re.compile(
            r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
            flags=re.IGNORECASE,
        ),
        re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE),
    )


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


def _resolve_inline_image_base_dir(origin_path: Path | None) -> Path | None:
    if origin_path is None:
        return None
    resolved_origin = origin_path.resolve(strict=False)
    base_dir = resolved_origin if resolved_origin.is_dir() else resolved_origin.parent
    return base_dir.resolve(strict=False)


def _inline_image_ref_skipped(ref: str) -> bool:
    return urlparse(ref).scheme in {"http", "https"} or "/api/v1/documents/image-url/" in ref


def _inline_file_url_path(ref: str) -> str | None:
    parsed = urlparse(ref)
    if str(parsed.scheme).lower() != "file":
        return None
    netloc = str(parsed.netloc).strip().lower()
    if netloc and netloc not in {"localhost", "127.0.0.1"}:
        return None
    resolved_ref = unquote(str(parsed.path))
    if not resolved_ref:
        return None
    if re.match(r"^/[a-zA-Z]:/", resolved_ref):
        return resolved_ref[1:]
    return resolved_ref


def _inline_local_ref_path_text(ref: str) -> str | None:
    if ref.lower().startswith("file://"):
        return _inline_file_url_path(ref)
    return unquote(ref)


def _resolve_inline_path_candidate(path_text: str, *, base_dir_resolved: Path) -> Path | None:
    path_obj = Path(path_text)
    if not path_obj.is_absolute():
        path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
    else:
        path_obj = path_obj.resolve(strict=False)
    try:
        path_obj.relative_to(base_dir_resolved)
    except Exception as exc:
        _log_processor_fallback("_upload_inline_images_to_minio", exc)
        return None
    return path_obj


def _decode_inline_data_uri(ref: str, *, max_image_bytes: int) -> bytes | None:
    header, b64_part = ref.split(",", 1)
    if "base64" not in header:
        return None
    b64_part = re.sub(r"\s+", "", b64_part)
    if len(b64_part) > int(max_image_bytes * 4 / 3) + 32:
        return None
    return base64.b64decode(b64_part)


def _resolve_inline_local_image_path(ref: str, *, base_dir_resolved: Path | None) -> Path | None:
    if not base_dir_resolved:
        return None
    path_text = _inline_local_ref_path_text(ref)
    if not path_text:
        return None
    return _resolve_inline_path_candidate(path_text, base_dir_resolved=base_dir_resolved)


def _read_inline_image_ref(
    ref: str,
    *,
    base_dir_resolved: Path | None,
    max_image_bytes: int,
) -> bytes | None:
    if ref.startswith("data:image"):
        return _decode_inline_data_uri(ref, max_image_bytes=max_image_bytes)
    path_obj = _resolve_inline_local_image_path(ref, base_dir_resolved=base_dir_resolved)
    if path_obj is None or not path_obj.exists() or not path_obj.is_file():
        return None
    try:
        if path_obj.stat().st_size > max_image_bytes:
            return None
    except Exception as exc:
        _log_processor_fallback("_upload_inline_images_to_minio", exc)
        return None
    return path_obj.read_bytes()


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


def _rewrite_inline_image_refs(
    markdown_text: str,
    *,
    replacements: dict[str, str],
    patterns: tuple[re.Pattern[str], re.Pattern[str]],
) -> str:
    if not replacements:
        return markdown_text

    def replace_match(match: re.Match) -> str:
        raw = match.group(1)
        new = replacements.get(raw.strip())
        if not new:
            return match.group(0)
        return match.group(0).replace(raw, new, 1)

    md_pat, html_pat = patterns
    markdown_text = md_pat.sub(replace_match, markdown_text)
    return html_pat.sub(replace_match, markdown_text)


def _upload_inline_image_ref_to_minio(
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
    if _inline_image_ref_skipped(ref):
        return None, None, idx
    try:
        binary = _read_inline_image_ref(
            ref,
            base_dir_resolved=base_dir_resolved,
            max_image_bytes=max_image_bytes,
        )
        if binary is None or len(binary) > max_image_bytes:
            return None, None, idx

        image_bytes = _jpeg_bytes_from_binary(binary)
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


def _collect_limited_inline_upload_refs(
    markdown_text: str,
) -> tuple[tuple[re.Pattern[str], re.Pattern[str]], list[str]] | None:
    lowered = markdown_text.lower()
    if "data:image" not in lowered and "![" not in lowered and "<img" not in lowered:
        return None
    patterns = _inline_image_patterns()
    found = _collect_inline_image_refs(markdown_text, patterns)
    if not found:
        return None
    max_inline_images = max(0, int(settings.MAX_INLINE_IMAGES or 0))
    if max_inline_images and len(found) > max_inline_images:
        found = found[:max_inline_images]
    return patterns, found


def _collect_inline_image_upload_replacements(
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
        url, new_img_id, idx = _upload_inline_image_ref_to_minio(
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

    refs = _collect_limited_inline_upload_refs(markdown_text)
    if refs is None:
        return markdown_text, [], start_index
    patterns, found = refs

    base_dir_resolved = _resolve_inline_image_base_dir(origin_path)
    max_image_bytes = int(settings.MAX_INLINE_IMAGE_BYTES or 10_000_000)
    max_image_bytes = max(1_000_000, max_image_bytes)
    replacements, new_ids, idx = _collect_inline_image_upload_replacements(
        found,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        cache=cache,
        start_index=start_index,
        base_dir_resolved=base_dir_resolved,
        max_image_bytes=max_image_bytes,
    )

    return (
        _rewrite_inline_image_refs(markdown_text, replacements=replacements, patterns=patterns),
        new_ids,
        idx,
    )


def chunk_integrated_file(file_path: Path, strategy: str):
    """
    Use integrated presets (naive/book/laws/email) to parse and chunk directly.
    Returns a list of LangChain Documents.
    """
    from langchain_core.documents import Document

    from app.third_party.integrated_pipeline import chunk_file

    chunks_dict = chunk_file(file_path, strategy=strategy)  # type: ignore[arg-type]

    documents = []
    for item in chunks_dict:
        text = item.get("content_with_weight")
        if text is None or text == "":
            text = item.get("text")
        if text is None or text == "":
            continue
        meta = {
            k: v for k, v in item.items() if k not in {"content_with_weight", "text", "content_ltks", "content_sm_ltks"}
        }
        documents.append(Document(page_content=text, metadata=meta))

    return documents


def _existing_metadata_image_id(metadata: dict[str, Any]) -> str | None:
    img_id = metadata.get("img_id")
    if isinstance(img_id, str) and img_id.strip():
        return img_id
    return None


def _metadata_image_keys() -> tuple[str, ...]:
    return ("image_base64", "image", "img_base64", "img", "image_data")


def _metadata_doc_type_is_image(metadata: dict[str, Any]) -> bool:
    doc_type = metadata.get("doc_type_kwd")
    return isinstance(doc_type, str) and doc_type.lower() == "image"


def _drop_minio_disabled_image_metadata(metadata: dict[str, Any]) -> None:
    metadata.pop("image", None)


def _metadata_embedded_image(metadata: dict[str, Any]) -> tuple[Any | None, str | None]:
    value = metadata.get("image")
    if value is None:
        return None, None
    if _metadata_doc_type_is_image(metadata):
        return value, "image"
    metadata.pop("image", None)
    return None, None


def _metadata_image_path_candidate(raw_path: str, *, tenant_id: str) -> Path | None:
    try:
        upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
        tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
        candidate = Path(raw_path.strip()).resolve(strict=False)
        candidate.relative_to(tenant_root)
    except Exception as exc:
        _log_processor_fallback("_extract_and_upload_image_to_minio", exc)
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _safe_unlink_processor_path(path: Path) -> None:
    try:
        path.unlink()
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


def _metadata_image_path_payload(
    metadata: dict[str, Any],
    *,
    tenant_id: str,
) -> tuple[Path | None, bytes | None, str | None]:
    raw_path = metadata.get("image_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, None, None
    if not _metadata_doc_type_is_image(metadata):
        metadata.pop("image_path", None)
        return None, None, None

    candidate = _metadata_image_path_candidate(raw_path, tenant_id=tenant_id)
    if candidate is None:
        metadata.pop("image_path", None)
        return None, None, None
    max_bytes = settings.MINIO_IMAGE_MAX_BYTES
    try:
        if max_bytes > 0 and candidate.stat().st_size > max_bytes:
            metadata.pop("image_path", None)
            _safe_unlink_processor_path(candidate)
            return None, None, None
        return candidate, candidate.read_bytes(), "image_path"
    except OSError as exc:
        _log_processor_fallback("_extract_and_upload_image_to_minio", exc)
        metadata.pop("image_path", None)
        return None, None, None


def _metadata_base64_image(metadata: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, str | None]:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value, key
    return None, None


def _strip_data_uri_payload(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.startswith("data:"):
        return value
    parts = value.split(",", 1)
    return parts[1] if len(parts) == 2 else value


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


def _metadata_image_bytes(*, raw_image: Any | None, b64_data: str | None) -> bytes:
    if raw_image is not None:
        if isinstance(raw_image, bytes):
            return _jpeg_bytes_from_binary(raw_image)
        return _jpeg_bytes_from_pil_image(raw_image)
    return _jpeg_bytes_from_binary(base64.b64decode((b64_data if b64_data is not None else "")))


def _close_metadata_raw_image(raw_image: Any | None) -> None:
    if raw_image is None or isinstance(raw_image, bytes) or not hasattr(raw_image, "close"):
        return
    try:
        raw_image.close()
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


def _cleanup_uploaded_metadata_image_fields(
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
        _safe_unlink_processor_path(image_path)


def _upload_extracted_metadata_image(
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
        _cleanup_uploaded_metadata_image_fields(
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
    existing_img_id = _existing_metadata_image_id(metadata)
    if existing_img_id is not None:
        return existing_img_id

    if not settings.MINIO_ENABLED:
        _drop_minio_disabled_image_metadata(metadata)
        return None

    possible_keys = _metadata_image_keys()
    raw_image, found_key = _metadata_embedded_image(metadata)

    image_path: Path | None = None
    if raw_image is None:
        image_path, raw_image, path_key = _metadata_image_path_payload(metadata, tenant_id=tenant_id)
        found_key = path_key or found_key

    b64_data = None
    if raw_image is None:
        b64_data, found_key = _metadata_base64_image(metadata, possible_keys)

    if raw_image is None and not b64_data:
        return None

    b64_data = _strip_data_uri_payload(b64_data)

    try:
        image_bytes = _metadata_image_bytes(raw_image=raw_image, b64_data=b64_data)
    except Exception as exc:
        logger.warning("Image conversion failed (skip upload): %s", exc)
        if found_key == "image":
            metadata.pop("image", None)
        return None
    finally:
        _close_metadata_raw_image(raw_image)

    return _upload_extracted_metadata_image(
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
