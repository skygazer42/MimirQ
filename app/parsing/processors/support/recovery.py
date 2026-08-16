import datetime as dt
from typing import Any, Callable
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
from app.rag.core.logging import get_logger
from app.rag.kg.extraction_job_options import (
    build_kg_extraction_job_options,
    kg_extraction_job_options_fingerprint,
)
from app.rag.kg.pipeline import extract_events
from app.rag.pipeline_plugins.registry import derive_registered_stage_plugin_ref
from app.rag.preprocessing.metadata_enrichment import build_document_metadata_enrichment
from app.services.document_index_channel_service import (
    DOCUMENT_INDEX_CHANNEL_ERROR,
    DOCUMENT_INDEX_CHANNEL_PROCESSING,
    DOCUMENT_INDEX_CHANNEL_READY,
    DOCUMENT_INDEX_CHANNEL_SKIPPED,
    transition_document_index_channel,
)
from app.services.metrics_logger import log_metrics
from app.types.pipeline import PipelineEffective

AUDIT_ACTION_DOCUMENT_INGEST_GATE = "document.ingest_gate"
logger = get_logger("parsing.document_processor")


class CheckpointedRetryRequiredError(RuntimeError):
    """Raised when finalization fails after a durable checkpoint was committed."""


def apply_pending_retry_cleanup(
    db: Session,
    *,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    indexer_factory: Callable[[Session], Any],
    parsed_content_model: type[DocumentParsedContent] = DocumentParsedContent,
    chunk_model: type[DocumentChunk] = DocumentChunk,
) -> str:
    original_meta = dict(getattr(db_document, "doc_metadata", None) or {})
    original_chunk_count = getattr(db_document, "chunk_count", None)
    original_total_characters = getattr(db_document, "total_characters", None)
    meta = dict(original_meta)
    request = meta.get("retry_cleanup")
    if request is None:
        return "applied"
    if not isinstance(request, dict) or str(request.get("version") or "") != "1":
        logger.error("Refusing unknown retry cleanup intent for document %s", document_id)
        return "invalid"

    pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
    scope = str(request.get("scope") or "").strip()
    target_key = str(request.get("doc_pipeline_key") or "").strip()
    if str(request.get("pipeline_hash") or "").strip() != pipeline_hash or scope not in {"document", "pipeline"}:
        logger.error("Refusing stale retry cleanup intent for document %s", document_id)
        return "invalid"
    if scope == "pipeline" and target_key != f"{document_id}:{pipeline_hash}":
        logger.error("Refusing invalid scoped retry cleanup intent for document %s", document_id)
        return "invalid"

    preserve_existing = scope == "pipeline"
    indexer = indexer_factory(db)
    cleanup_chunk_ids: list[UUID] = []

    if bool(request.get("force")):
        meta.pop("ingest_checkpoint", None)
        meta.pop("parsed_content_persisted", None)
        db.query(parsed_content_model).filter(
            parsed_content_model.document_id == document_id,
            parsed_content_model.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

    if preserve_existing:
        cleanup_chunk_ids = [
            chunk_id
            for (chunk_id,) in (
                db.query(chunk_model.id)
                .filter(
                    chunk_model.document_id == document_id,
                    chunk_model.tenant_id == tenant_id,
                    chunk_model.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
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
        db.query(chunk_model).filter(
            chunk_model.document_id == document_id,
            chunk_model.tenant_id == tenant_id,
            chunk_model.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
        ).delete(synchronize_session=False)
    else:
        indexer.delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
        db.query(chunk_model).filter(
            chunk_model.document_id == document_id,
            chunk_model.tenant_id == tenant_id,
        ).delete(synchronize_session=False)
        meta.pop("img_ids", None)
        db_document.chunk_count = 0
        db_document.total_characters = 0

    db_document.doc_metadata = meta

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
        meta.pop("retry_cleanup", None)
        db_document.doc_metadata = meta
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        db_document.doc_metadata = original_meta
        if original_chunk_count is not None:
            db_document.chunk_count = original_chunk_count
        if original_total_characters is not None:
            db_document.total_characters = original_total_characters
        logger.warning(
            "Failed to complete retry cleanup for document %s; keeping retry cleanup marker for a later retry: %s",
            document_id,
            str(exc)[:200],
        )
        return "deferred"

    db.refresh(db_document)
    return "applied"


def checkpoint_stage(metadata: dict[str, Any]) -> str:
    checkpoint = metadata.get("ingest_checkpoint")
    if not isinstance(checkpoint, dict):
        return ""
    return str(checkpoint.get("stage") or "").strip().lower()


def _checkpoint_matches_current_document(
    metadata: dict[str, Any],
    *,
    expected_stage: str,
) -> bool:
    checkpoint = metadata.get("ingest_checkpoint")
    if not (
        isinstance(checkpoint, dict)
        and str(checkpoint.get("version") or "") == "1"
        and str(checkpoint.get("stage") or "").strip().lower() == str(expected_stage or "").strip().lower()
    ):
        return False
    pipeline_hash = str(metadata.get("pipeline_hash") or "").strip()
    file_sha256 = str(metadata.get("file_sha256") or "").strip().lower()
    checkpoint_pipeline_hash = str(checkpoint.get("pipeline_hash") or "").strip()
    checkpoint_file_sha256 = str(checkpoint.get("file_sha256") or "").strip().lower()
    if pipeline_hash and checkpoint_pipeline_hash and pipeline_hash != checkpoint_pipeline_hash:
        return False
    if file_sha256 and checkpoint_file_sha256 and file_sha256 != checkpoint_file_sha256:
        return False
    return True


def parsed_checkpoint_is_reusable(metadata: dict[str, Any]) -> bool:
    if not _checkpoint_matches_current_document(metadata, expected_stage="parsed"):
        return False
    persisted = metadata.get("parsed_content_persisted")
    cleaned = persisted.get("cleaned") if isinstance(persisted, dict) else None
    return not (isinstance(cleaned, dict) and bool(cleaned.get("truncated")))


def indexed_checkpoint_is_reusable(metadata: dict[str, Any]) -> bool:
    return _checkpoint_matches_current_document(metadata, expected_stage="indexed")


def upsert_ingest_checkpoint(
    metadata: dict[str, Any] | None,
    *,
    stage: str,
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(metadata or {})
    checkpoint = {
        "version": "1",
        "stage": str(stage or "").strip() or "unknown",
        "source": str(source or "").strip() or "unknown",
        "file_sha256": str(out.get("file_sha256") or "").strip().lower(),
        "pipeline_hash": str(out.get("pipeline_hash") or "").strip(),
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            if value not in (None, "", [], {}):
                checkpoint[str(key)] = value
    out["ingest_checkpoint"] = checkpoint
    return out


def record_ingest_gate_outcome(
    metadata: dict[str, Any] | None,
    *,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(metadata or {})
    existing = out.get("ingest_gate_outcomes")
    gate_outcomes = dict(existing) if isinstance(existing, dict) else {}
    entry: dict[str, Any] = {
        "gate": str(gate or "").strip() or "unknown",
        "outcome": str(outcome or "").strip() or "degraded",
        "reason": str(reason or "").strip() or "unknown",
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    if isinstance(details, dict):
        for key, value in details.items():
            if value not in (None, "", [], {}):
                entry[str(key)] = value
    gate_outcomes[entry["gate"]] = entry
    out["ingest_gate_outcomes"] = gate_outcomes
    return out


def _document_questions_enabled(metadata: dict[str, Any] | None) -> bool:
    meta = dict(metadata or {})
    for key in ("document_questions_enabled", "generate_document_questions"):
        if key in meta:
            value = meta.get(key)
            if isinstance(value, bool):
                return value
            if str(value or "").strip().lower() in {"1", "true", "yes", "on"}:
                return True
            if str(value or "").strip().lower() in {"0", "false", "no", "off"}:
                return False
    return bool(getattr(settings, "DOCUMENT_QUESTIONS_ENABLED", False))


def _document_questions_count(metadata: dict[str, Any] | None) -> int:
    meta = dict(metadata or {})
    raw = meta.get("document_questions_count")
    if raw is None:
        raw = getattr(settings, "DOCUMENT_QUESTIONS_COUNT", 3)
    try:
        count = int(raw or 3)
    except Exception:
        count = 3
    return max(3, min(5, count))


def audit_ingest_gate(
    db: Session,
    *,
    tenant_id: UUID,
    db_document: DBDocument,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    from app.services.audit_log_service import audit_log_event

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=(getattr(db_document, "owner_id", None) or None),
        action=AUDIT_ACTION_DOCUMENT_INGEST_GATE,
        resource_type="document",
        resource_id=str(getattr(db_document, "id", "")),
        details={
            "gate": str(gate or "").strip() or "unknown",
            "outcome": str(outcome or "").strip() or "degraded",
            "reason": str(reason or "").strip() or "unknown",
            **(dict(details or {}) if isinstance(details, dict) else {}),
        },
    )
    db.commit()


def maybe_enrich_document_questions(
    db: Session,
    *,
    db_document: DBDocument,
    documents: list[Document] | None,
) -> None:
    if not documents:
        return
    metadata = dict(getattr(db_document, "doc_metadata", None) or {})
    if not _document_questions_enabled(metadata):
        return
    if metadata.get("document_questions"):
        return

    source_parts: list[str] = []
    remaining = 4000
    for doc in documents:
        content = str(getattr(doc, "page_content", "") or "").strip()
        if not content:
            continue
        source_parts.append(content[:remaining])
        remaining -= min(len(content), remaining)
        if remaining <= 0:
            break
    source_text = "\n\n".join(source_parts).strip()
    if not source_text:
        return

    count = _document_questions_count(metadata)
    enrichment = build_document_metadata_enrichment(
        source_text,
        metadata=metadata,
        question_count=count,
        generate_questions=True,
    )
    questions = [
        str(item).strip()
        for item in (enrichment.get("document_questions") or [])
        if isinstance(item, str) and str(item).strip()
    ]
    if not questions:
        return

    metadata.update(
        {
            "document_questions": questions[:count],
            "document_questions_generation": {
                "enabled": True,
                "mode": "heuristic",
                "count": len(questions[:count]),
            },
        }
    )
    db_document.doc_metadata = metadata
    db.commit()
    db.refresh(db_document)


async def run_post_completion_kg(
    *,
    db: Session,
    db_document: DBDocument,
    tenant_id: UUID,
    document_id: UUID,
    chunk_ids: list[UUID],
    db_chunks: list[DocumentChunk],
    index_options: Any,
    pipeline_effective: PipelineEffective,
) -> None:
    if not getattr(pipeline_effective, "kg_enabled", False):
        return

    transition_document_index_channel(
        db,
        document=db_document,
        channel="kg",
        status=DOCUMENT_INDEX_CHANNEL_PROCESSING,
        increment_attempt=True,
        commit=False,
    )

    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        try:
            from app.core.pipeline_versions import get_active_pipeline_hash
            from app.tasks.queue import enqueue_kg_extraction

            raw_pipeline_hash = (
                get_active_pipeline_hash(db_document.doc_metadata or {})
                or (db_document.doc_metadata or {}).get("pipeline_hash")
                or None
            )
            pipeline_hash = (str(raw_pipeline_hash).strip() or None) if raw_pipeline_hash is not None else None
            raw_prompt_template_id = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
            prompt_template_id = UUID(raw_prompt_template_id) if raw_prompt_template_id else None
            kg_python_plugin_ref = str(getattr(pipeline_effective, "kg_python_plugin", "") or "").strip()
            if not kg_python_plugin_ref:
                kg_python_plugin_ref = derive_registered_stage_plugin_ref(
                    str(getattr(pipeline_effective, "chunk_python_plugin", "") or "").strip(),
                    "kg",
                )
            effective_options = build_kg_extraction_job_options(
                pipeline_hash=pipeline_hash,
                prompt_template_id=prompt_template_id,
                prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                prompt_ab_experiment_key=(getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None,
                extraction_backend=(getattr(settings, "KG_EXTRACTION_BACKEND", "") or "").strip() or None,
                kg_python_plugin=kg_python_plugin_ref,
                kg_python_params=dict(getattr(pipeline_effective, "kg_python_params", {}) or {}),
                replace_existing=bool(getattr(settings, "KG_EXTRACT_REPLACE_EXISTING", True)),
                prune_orphan_entities=bool(getattr(settings, "KG_EXTRACT_PRUNE_ORPHAN_ENTITIES", True)),
                extract_relations=bool(getattr(settings, "KG_RELATION_ENABLED", False)),
                extract_skills=bool(getattr(settings, "KG_SKILL_ENABLED", False)),
            )
            options_fingerprint = kg_extraction_job_options_fingerprint(effective_options)
            pipeline_job_label = pipeline_hash or "unversioned"
            job_id = f"kg:{tenant_id}:{document_id}:{pipeline_job_label}:{options_fingerprint}"
            kg_task_id = await enqueue_kg_extraction(
                tenant_id=tenant_id,
                document_id=document_id,
                requested_by="system",
                job_id=job_id,
                pipeline_hash=pipeline_hash,
                effective_options=effective_options,
            )
            if kg_task_id:
                meta = dict(db_document.doc_metadata or {})
                meta["kg_task_id"] = kg_task_id
                db_document.doc_metadata = meta
                db.commit()
                db.refresh(db_document)
            log_metrics({"event": "ingest.kg.enqueued", "kg_task_id": kg_task_id})
        except Exception as exc:
            transition_document_index_channel(
                db,
                document=db_document,
                channel="kg",
                status=DOCUMENT_INDEX_CHANNEL_ERROR,
                error=str(exc)[:2000],
                commit=False,
            )
            return
        return

    try:
        raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
        prompt_template_id = UUID(raw_tid) if raw_tid else None
    except Exception:
        prompt_template_id = None
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
            chunks=db_chunks,
            index_options=index_options,
            prompt_template_id=prompt_template_id,
            prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
            prompt_ab_experiment_key=(getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None,
            kg_python_plugin=kg_python_plugin_ref,
            kg_python_params=kg_python_params,
        )
        log_metrics(
            {
                "event": "ingest.kg.completed",
                "event_count": len(events),
                "kg_python_plugin": kg_python_plugin_ref,
            }
        )
        transition_document_index_channel(
            db,
            document=db_document,
            channel="kg",
            status=DOCUMENT_INDEX_CHANNEL_READY,
            commit=False,
        )
        if not events:
            for channel_name in ("event_vector", "entity_vector"):
                transition_document_index_channel(
                    db,
                    document=db_document,
                    channel=channel_name,
                    status=DOCUMENT_INDEX_CHANNEL_SKIPPED,
                    commit=False,
                )
    except Exception as exc:
        transition_document_index_channel(
            db,
            document=db_document,
            channel="kg",
            status=DOCUMENT_INDEX_CHANNEL_ERROR,
            error=str(exc)[:2000],
            commit=False,
        )
        return


def resolve_ingestion_run_update_criticality(
    db_doc: DBDocument,
    *,
    status_norm: str,
) -> str:
    meta = dict(getattr(db_doc, "doc_metadata", None) or {})
    for key in ("ingestion_run_update_criticality", "ingestion_run_status_criticality"):
        raw = str(meta.get(key) or "").strip().lower()
        if raw in {"best_effort", "required"}:
            return raw
    if status_norm in {"completed", "failed", "quarantined", "cancelled"}:
        return "required"
    return "best_effort"


def persist_retry_boundary_failure(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    reason: str,
    error: Exception,
) -> None:
    db.rollback()
    db_doc = (
        db.query(DBDocument)
        .populate_existing()
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )
    if db_doc is None:
        raise CheckpointedRetryRequiredError(reason) from error

    meta = record_ingest_gate_outcome(
        dict(getattr(db_doc, "doc_metadata", None) or {}),
        gate="ingestion_run",
        outcome="closed",
        reason=reason,
        details={"error": str(error)[:200]},
    )
    meta["ingest_resume_required"] = {
        "required": True,
        "reason": str(reason or "").strip() or "retry_required",
        "checkpoint_stage": checkpoint_stage(meta),
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    db_doc.status = "failed"
    db_doc.processing_progress = 0
    db_doc.current_stage = "finalizing"
    db_doc.error_message = str(reason or "").strip() or "retry_required"
    db_doc.doc_metadata = meta
    db.commit()
    db.refresh(db_doc)
    raise CheckpointedRetryRequiredError(str(reason or "").strip() or "retry_required") from error
