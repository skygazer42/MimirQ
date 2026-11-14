"""Ingestion run manifest API.

This exposes a unified run_id view for ingestion entrypoints (upload/batch/URL/connector).
"""

import json
import re
from collections.abc import Mapping
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.sources import (
    IngestionRunCompareResponse,
    IngestionRunDocumentOut,
    IngestionRunListQuery,
    IngestionRunListResponse,
    IngestionRunOut,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.utils import file_response_headers
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.group_permissions import DatasetGroupPermission
from app.models.ingestion_run import IngestionRun as DBIngestionRun
from app.models.tenant_group import TenantGroupMember
from app.rag.core.logging import get_logger
from app.services import dataset_service, ingestion_run_service
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import EDIT_ROLES

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)


def _commit_ingestion_run_audit(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    action: str,
    run_id: UUID,
    details: Mapping[str, object],
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=action,
            resource_type="ingestion_run",
            resource_id=str(run_id),
            details=dict(details),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Ingestion-run operation committed but audit logging failed: action=%s run_id=%s",
            action,
            run_id,
            exc_info=True,
        )


def _writable_dataset_ids_subquery(*, tenant_id: UUID, account_id: str):
    member_group_ids_subq = select(TenantGroupMember.group_id).where(
        TenantGroupMember.tenant_id == tenant_id,
        TenantGroupMember.user_id == account_id,
    )

    partial_member_exists = exists().where(
        DatasetPermission.tenant_id == tenant_id,
        DatasetPermission.dataset_id == Dataset.id,
        DatasetPermission.account_id == account_id,
    )
    partial_group_exists = exists().where(
        DatasetGroupPermission.tenant_id == tenant_id,
        DatasetGroupPermission.dataset_id == Dataset.id,
        DatasetGroupPermission.group_id.in_(member_group_ids_subq),
    )

    return select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        or_(
            Dataset.owner_id == account_id,
            Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            and_(
                Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                or_(partial_member_exists, partial_group_exists),
            ),
        ),
    )


def _run_out(run: DBIngestionRun) -> IngestionRunOut:
    docs: list[IngestionRunDocumentOut] = []
    for document in run.documents:
        if document.document_id is None:
            continue
        docs.append(
            IngestionRunDocumentOut(
                document_id=document.document_id,
                status=document.status,
                source_ref=document.source_ref,
                created_at=document.created_at,
            )
        )

    return IngestionRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        kind=run.kind,
        requested_by=run.requested_by,
        status=run.status,
        config=dict(run.config or {}),
        stats=dict(run.stats or {}),
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        documents=docs,
    )


def _load_ingestion_run(*, db: Session, run_id: UUID, tenant_id: UUID, account_id: str) -> DBIngestionRun:
    dataset_service.ensure_member(db, tenant_id, account_id)
    run = (
        db.query(DBIngestionRun)
        .options(selectinload(DBIngestionRun.documents))
        .filter(DBIngestionRun.id == run_id, DBIngestionRun.tenant_id == tenant_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion run not found")
    if run.dataset_id is not None:
        ds = dataset_service.get_dataset(db, tenant_id, run.dataset_id)
        dataset_service.assert_dataset_writable(db, ds, account_id)
    return run


def _collect_replay_doc_ids(base: DBIngestionRun) -> list[UUID]:
    doc_ids: list[UUID] = []
    for document in base.documents:
        document_id = document.document_id
        if document_id is not None:
            doc_ids.append(document_id)
        if len(doc_ids) >= 2000:
            break
    if not doc_ids:
        raise HTTPException(status_code=400, detail="No documents to replay")
    return doc_ids


def _attach_replay_documents(*, db: Session, tenant_id: UUID, run_id: UUID, doc_ids: list[UUID]) -> None:
    for doc_id in doc_ids:
        ingestion_run_service.add_document(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            document_id=doc_id,
            source_ref=None,
            initial_status="pending",
            doc_meta=None,
        )


async def _run_replay_retries(
    *,
    tenant_id: UUID,
    account_id: str,
    new_run_id: UUID,
    doc_ids: list[UUID],
) -> None:
    from app.core.database import SessionLocal
    from app.models.document import Document as DBDocument
    from app.services.document_processing_operations import retry_document

    db0 = SessionLocal()
    try:
        for doc_id in doc_ids:
            try:
                doc = db0.query(DBDocument).filter(DBDocument.id == doc_id, DBDocument.tenant_id == tenant_id).first()
                if doc is not None:
                    meta0 = dict(doc.doc_metadata or {})
                    meta0["last_ingestion_run_id"] = str(new_run_id)
                    meta0["last_ingestion_kind"] = "replay"
                    doc.doc_metadata = meta0
                    db0.commit()
            except Exception:
                logger.warning(
                    "Replay document metadata update failed: run_id=%s document_id=%s",
                    new_run_id,
                    doc_id,
                    exc_info=True,
                )
                db0.rollback()

            bg = BackgroundTasks()
            try:
                await retry_document(
                    document_id=doc_id,
                    background_tasks=bg,
                    force=True,
                    skip_if_unchanged=False,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    db=db0,
                )
                await bg()
            except Exception:
                logger.warning(
                    "Replay document retry failed: run_id=%s document_id=%s",
                    new_run_id,
                    doc_id,
                    exc_info=True,
                )
                db0.rollback()
    finally:
        db0.close()


@router.get("/runs", response_model=IngestionRunListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_ingestion_runs(
    params: Annotated[IngestionRunListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List ingestion runs (requires dataset write permission for each returned run's dataset)."""
    member = dataset_service.ensure_member(db, tenant_id, account_id)

    q = db.query(DBIngestionRun).filter(DBIngestionRun.tenant_id == tenant_id)
    if params.dataset_id is not None:
        ds = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
        dataset_service.assert_dataset_writable(db, ds, account_id)
        q = q.filter(DBIngestionRun.dataset_id == params.dataset_id)
    elif member.role.lower() not in EDIT_ROLES:
        return IngestionRunListResponse(total=0, items=[])
    else:
        q = q.filter(
            DBIngestionRun.dataset_id.in_(_writable_dataset_ids_subquery(tenant_id=tenant_id, account_id=account_id))
        )

    status_norm = params.status.strip().lower() if params.status is not None else None
    if status_norm:
        q = q.filter(DBIngestionRun.status == status_norm)

    kind_norm = params.kind.strip() if params.kind is not None else None
    if kind_norm:
        q = q.filter(DBIngestionRun.kind == kind_norm)

    total = int(q.count())
    runs = (
        q.options(selectinload(DBIngestionRun.documents))
        .order_by(DBIngestionRun.created_at.desc())
        .offset(params.skip)
        .limit(params.limit)
        .all()
    )

    return IngestionRunListResponse(total=total, items=[_run_out(r) for r in runs])


@router.get("/runs/{run_id}", response_model=IngestionRunOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_ingestion_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get ingestion run detail (requires dataset write permission)."""
    run = _load_ingestion_run(db=db, run_id=run_id, tenant_id=tenant_id, account_id=account_id)
    return _run_out(run)


@router.get("/runs/{run_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_ingestion_run_json(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export ingestion run manifest as JSON (offline-friendly)."""
    run = _run_out(_load_ingestion_run(db=db, run_id=run_id, tenant_id=tenant_id, account_id=account_id))

    # Best-effort audit log (PII-minimal): record export operation.
    _commit_ingestion_run_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="ingestion.run.export_json",
        run_id=run_id,
        details={
            "dataset_id": str(run.dataset_id) if run.dataset_id else None,
            "kind": run.kind,
            "status": run.status,
            "documents": len(run.documents),
        },
    )

    content = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(run.kind or "ingestion"))[:64]
    filename = f"{safe}.run.{str(run.id)[:8]}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers=file_response_headers(filename),
    )


@router.get("/runs/{run_id}/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_ingestion_run_html(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export ingestion run manifest as a single HTML file (best-effort)."""
    # Keep this simple: reuse dataset report HTML style (raw JSON + KPIs).
    from app.services.report_html import render_dataset_report_html

    run = _run_out(_load_ingestion_run(db=db, run_id=run_id, tenant_id=tenant_id, account_id=account_id))

    # Best-effort audit log (PII-minimal): record export operation.
    _commit_ingestion_run_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="ingestion.run.export_html",
        run_id=run_id,
        details={
            "dataset_id": str(run.dataset_id) if run.dataset_id else None,
            "kind": run.kind,
            "status": run.status,
            "documents": len(run.documents),
        },
    )

    payload = run.model_dump(mode="json")
    title = "MimirQ · Ingestion Run Manifest"
    html = render_dataset_report_html(
        title=title,
        dataset_name=run.kind or "ingestion_run",
        dataset_id=str(payload["id"]),
        generated_at=payload["created_at"],
        report=payload,
        redact=False,
    )
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(run.kind or "ingestion"))[:64]
    filename = f"{safe}.run.{str(run.id)[:8]}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=file_response_headers(filename),
    )


@router.get(
    "/runs/{run_id}/compare/{other_run_id}",
    response_model=IngestionRunCompareResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def compare_ingestion_runs(
    run_id: UUID,
    other_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Compare two ingestion runs (same ACL as get)."""
    row_a = _load_ingestion_run(db=db, run_id=run_id, tenant_id=tenant_id, account_id=account_id)
    a = _run_out(row_a)
    row_b = _load_ingestion_run(db=db, run_id=other_run_id, tenant_id=tenant_id, account_id=account_id)
    b = _run_out(row_b)
    diff = ingestion_run_service.compare_runs(run_a=row_a, run_b=row_b)

    # Best-effort audit log (PII-minimal): record compare operation.
    _commit_ingestion_run_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="ingestion.run.compare",
        run_id=run_id,
        details={
            "other_run_id": str(other_run_id),
            "dataset_id": str(a.dataset_id) if a.dataset_id else None,
        },
    )

    return IngestionRunCompareResponse(run_a=a, run_b=b, diff=diff)


@router.post(
    "/runs/{run_id}/replay",
    response_model=IngestionRunOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def replay_ingestion_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Best-effort "replay": create a new run that reprocesses the same document ids.

    Notes:
    - Uses existing /documents/{id}/retry logic (force=true) to kick off processing.
    - Does not re-download connector sources; it reprocesses existing stored files.
    """
    base = _load_ingestion_run(db=db, run_id=run_id, tenant_id=tenant_id, account_id=account_id)
    doc_ids = _collect_replay_doc_ids(base)

    new_run = ingestion_run_service.create_run(
        db,
        tenant_id=tenant_id,
        dataset_id=base.dataset_id,
        requested_by=account_id,
        kind="replay",
        config={"replay_of": str(base.id), "base_kind": base.kind},
        expected_documents=len(doc_ids),
    )

    _commit_ingestion_run_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="ingestion.run.replay",
        run_id=new_run.id,
        details={
            "base_run_id": str(base.id),
            "dataset_id": str(base.dataset_id) if base.dataset_id else None,
            "documents": len(doc_ids),
        },
    )
    _attach_replay_documents(db=db, tenant_id=tenant_id, run_id=new_run.id, doc_ids=doc_ids)
    background_tasks.add_task(
        _run_replay_retries,
        tenant_id=tenant_id,
        account_id=account_id,
        new_run_id=new_run.id,
        doc_ids=doc_ids,
    )

    return _run_out(new_run)
