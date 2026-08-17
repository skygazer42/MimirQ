"""KG extraction option/enqueue helpers for the KG API routes.

Split out of ``app.rag.kg.api.routes`` (see ``app.rag.kg.api.routes_support``).
The extraction routes themselves stay in the routes module. Function-local
(deferred) imports are preserved verbatim.
"""

import contextlib
import uuid
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.errors import ConfigError
from app.rag.kg.api.routes_support.common import (
    KG_EXTRACTION_ALREADY_QUEUED_DETAIL,
    KG_PIPELINE_CHUNKS_NOT_FOUND_DETAIL,
)
from app.rag.kg.api.routes_support.projection import _chunk_matches_pipeline, _doc_pipeline_hash
from app.rag.kg.api.routes_support.schemas import KGExtractionEffectiveOptions, KGExtractionOptions
from app.rag.kg.extraction_job_options import (
    build_kg_extraction_job_options,
    kg_extraction_job_options_fingerprint,
)
from app.rag.kg.pipeline import extract_events
from app.rag.kg.schemas import KGExtractResponse
from app.rag.pipeline_plugins.registry import derive_registered_stage_plugin_ref
from app.services.dataset_service import DatasetService


def _get_extraction_document(db: Session, *, tenant_id: UUID, document_id: UUID, account_id: str) -> DBDocument:
    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    return document


def _document_chunks_for_extraction(db: Session, *, tenant_id: UUID, document_id: UUID) -> list[DocumentChunk]:
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id, DocumentChunk.tenant_id == tenant_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="Document has no chunks yet. Process the document first.")
    return chunks


def _selected_extraction_pipeline_hash(document: DBDocument, options: KGExtractionOptions) -> str | None:
    explicit = options.pipeline_hash.strip() if isinstance(options.pipeline_hash, str) else ""
    return explicit or _doc_pipeline_hash(getattr(document, "doc_metadata", None) or {})


def _scope_chunks_to_pipeline(
    chunks: list[DocumentChunk], *, document_id: UUID, pipeline_hash: str | None
) -> list[DocumentChunk]:
    if not pipeline_hash:
        return chunks
    scoped = [
        chunk
        for chunk in chunks
        if _chunk_matches_pipeline(chunk, document_id=document_id, pipeline_hash=pipeline_hash)
    ]
    if not scoped:
        raise HTTPException(status_code=409, detail=KG_PIPELINE_CHUNKS_NOT_FOUND_DETAIL)
    return scoped


def _default_prompt_template_id() -> UUID | None:
    raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
    if not raw_tid:
        return None
    with contextlib.suppress(Exception):
        return UUID(raw_tid)
    return None


def _document_kg_python_plugin(document: DBDocument) -> tuple[str | None, dict[str, Any]]:
    meta = getattr(document, "doc_metadata", None)
    meta_dict = meta if isinstance(meta, dict) else {}
    effective = meta_dict.get("pipeline_effective") if isinstance(meta_dict.get("pipeline_effective"), dict) else {}
    explicit = str(effective.get("kg_python_plugin") or "").strip()
    params = effective.get("kg_python_params") if isinstance(effective.get("kg_python_params"), dict) else {}
    if explicit:
        return explicit, dict(params)
    chunk_ref = str(effective.get("chunk_python_plugin") or "").strip()
    kg_ref = derive_registered_stage_plugin_ref(chunk_ref, "kg")
    return (kg_ref or None), dict(params)


def _effective_kg_extraction_options(
    document: DBDocument, options: KGExtractionOptions
) -> KGExtractionEffectiveOptions:
    kg_python_plugin, kg_python_params = _document_kg_python_plugin(document)
    return KGExtractionEffectiveOptions(
        pipeline_hash=_selected_extraction_pipeline_hash(document, options),
        prompt_template_id=options.prompt_template_id or _default_prompt_template_id(),
        prompt_template_key=(
            (options.prompt_template_key or "").strip()
            or (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip()
            or None
        ),
        prompt_ab_experiment_key=(
            (options.prompt_ab_experiment_key or "").strip()
            or (getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip()
            or None
        ),
        kg_python_plugin=kg_python_plugin,
        kg_python_params=kg_python_params,
        replace_existing=bool(
            settings.KG_EXTRACT_REPLACE_EXISTING if options.replace_existing is None else options.replace_existing
        ),
        prune_orphan_entities=bool(
            settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES
            if options.prune_orphan_entities is None
            else options.prune_orphan_entities
        ),
        extract_relations=options.extract_relations if isinstance(options.extract_relations, bool) else None,
        extract_skills=options.extract_skills if isinstance(options.extract_skills, bool) else None,
        extraction_backend=(
            str(options.extraction_backend).strip() if isinstance(options.extraction_backend, str) else None
        ),
    )


def _extraction_audit_details(
    *,
    async_mode: bool,
    effective: KGExtractionEffectiveOptions,
    chunk_count: int | None = None,
    event_count: int | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "async": async_mode,
        "pipeline_hash": effective.pipeline_hash,
        "replace_existing": bool(effective.replace_existing),
        "prune_orphan_entities": bool(effective.prune_orphan_entities),
        "extract_relations": effective.extract_relations,
        "extract_skills": effective.extract_skills,
        "kg_python_plugin": effective.kg_python_plugin,
    }
    if task_id is not None:
        details["task_id"] = str(task_id)
    if chunk_count is not None:
        details["chunk_count"] = int(chunk_count)
    if event_count is not None:
        details["event_count"] = int(event_count)
    return details


def _audit_kg_extraction(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    action: str,
    details: dict[str, Any],
) -> None:
    try:
        from app.models.audit_log import AuditLog

        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action=action,
                resource_type="document",
                resource_id=str(document_id),
                details=details,
            )
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()


async def _enqueue_kg_extraction_response(
    *,
    db: Session,
    document: DBDocument,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    chunks: list[DocumentChunk],
    response: Response,
    effective: KGExtractionEffectiveOptions,
) -> KGExtractResponse:
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        raise HTTPException(status_code=400, detail="Task queue is disabled (TASK_QUEUE_ENABLED=false)")
    try:
        from app.tasks.queue import enqueue_kg_extraction

        raw_pipeline_hash = effective.pipeline_hash or (document.doc_metadata or {}).get("pipeline_hash") or None
        pipeline_hash_for_job = (str(raw_pipeline_hash).strip() or None) if raw_pipeline_hash is not None else None
        pipeline_job_label = pipeline_hash_for_job or "unversioned"
        frozen_extract_relations = (
            effective.extract_relations
            if isinstance(effective.extract_relations, bool)
            else bool(getattr(settings, "KG_RELATION_ENABLED", False))
        )
        frozen_extract_skills = (
            effective.extract_skills
            if isinstance(effective.extract_skills, bool)
            else bool(getattr(settings, "KG_SKILL_ENABLED", False))
        )
        effective_options = build_kg_extraction_job_options(
            pipeline_hash=pipeline_hash_for_job,
            prompt_template_id=effective.prompt_template_id,
            prompt_template_key=effective.prompt_template_key,
            prompt_ab_experiment_key=effective.prompt_ab_experiment_key,
            extraction_backend=(
                effective.extraction_backend or (getattr(settings, "KG_EXTRACTION_BACKEND", "") or "").strip() or None
            ),
            kg_python_plugin=effective.kg_python_plugin,
            kg_python_params=effective.kg_python_params,
            replace_existing=effective.replace_existing,
            prune_orphan_entities=effective.prune_orphan_entities,
            extract_relations=frozen_extract_relations,
            extract_skills=frozen_extract_skills,
        )
        options_fingerprint = kg_extraction_job_options_fingerprint(effective_options)
        task_id = await enqueue_kg_extraction(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=account_id,
            job_id=f"kg:{tenant_id}:{document_id}:{pipeline_job_label}:{options_fingerprint}",
            pipeline_hash=pipeline_hash_for_job,
            replace_existing=effective.replace_existing,
            prune_orphan_entities=effective.prune_orphan_entities,
            extract_relations=effective.extract_relations,
            extract_skills=effective.extract_skills,
            effective_options=effective_options,
        )
        if task_id is None:
            raise HTTPException(status_code=409, detail=KG_EXTRACTION_ALREADY_QUEUED_DETAIL)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Failed to enqueue KG extraction: {str(exc)[:200]}") from exc

    if task_id:
        meta = dict(document.doc_metadata or {})
        meta["kg_task_id"] = task_id
        document.doc_metadata = meta
        db.commit()
        db.refresh(document)
    _audit_kg_extraction(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        action="kg.document.extract.enqueue",
        details=_extraction_audit_details(async_mode=True, effective=effective, task_id=task_id),
    )
    response.status_code = 202
    if task_id:
        response.headers["X-Task-Id"] = str(task_id)
    return KGExtractResponse(document_id=document_id, chunk_count=len(chunks), event_count=0)


async def _run_sync_kg_extraction(
    *,
    chunks: list[DocumentChunk],
    tenant_id: UUID,
    account_id: str,
    effective: KGExtractionEffectiveOptions,
) -> list[Any]:
    try:
        return await extract_events(
            [chunk.id for chunk in chunks],
            tenant_id=tenant_id,
            chunks=chunks,
            prompt_template_id=effective.prompt_template_id,
            prompt_template_key=effective.prompt_template_key,
            prompt_ab_experiment_key=effective.prompt_ab_experiment_key,
            ab_user_key=account_id,
            extract_relations=effective.extract_relations,
            extract_skills=effective.extract_skills,
            extraction_backend=effective.extraction_backend,
            kg_python_plugin=effective.kg_python_plugin,
            kg_python_params=effective.kg_python_params,
            replace_existing=effective.replace_existing,
            prune_orphan_entities=effective.prune_orphan_entities,
        )
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"KG extraction failed: {str(exc)[:200]}") from exc
