"""Ingestion run manifest API.

This exposes a unified run_id view for ingestion entrypoints (upload/batch/URL/connector).
"""


import contextlib
import json
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.ingestion_run import (
    IngestionRunCompareResponse,
    IngestionRunDocumentOut,
    IngestionRunListResponse,
    IngestionRunOut,
)
from app.api.utils.response_headers import download_response_headers
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.group_permissions import DatasetGroupPermission
from app.models.ingestion_run import IngestionRun as DBIngestionRun
from app.models.tenant_group import TenantGroupMember
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import EDIT_ROLES, DatasetService
from app.services.ingestion_run_service import IngestionRunService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


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
    for d in (getattr(run, "documents", None) or []):
        if getattr(d, "document_id", None) is None:
            continue
        docs.append(
            IngestionRunDocumentOut(
                document_id=d.document_id,
                status=str(getattr(d, "status", "") or ""),
                source_ref=getattr(d, "source_ref", None),
                created_at=getattr(d, "created_at", None),
            )
        )

    return IngestionRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_id=getattr(run, "dataset_id", None),
        kind=str(getattr(run, "kind", "") or ""),
        requested_by=getattr(run, "requested_by", None),
        status=str(getattr(run, "status", "") or ""),
        config=dict(getattr(run, "config", None) or {}),
        stats=dict(getattr(run, "stats", None) or {}),
        error_message=getattr(run, "error_message", None),
        created_at=getattr(run, "created_at", None),
        started_at=getattr(run, "started_at", None),
        finished_at=getattr(run, "finished_at", None),
        documents=docs,
    )


def _load_replay_base_run(*, db: Session, run_id: UUID, tenant_id: UUID, account_id: str) -> DBIngestionRun:
    DatasetService.ensure_member(db, tenant_id, account_id)
    base = (
        db.query(DBIngestionRun)
        .options(selectinload(DBIngestionRun.documents))
        .filter(DBIngestionRun.id == run_id, DBIngestionRun.tenant_id == tenant_id)
        .first()
    )
    if not base:
        raise HTTPException(status_code=404, detail="Ingestion run not found")
    if base.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, base.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)
    return base


def _collect_replay_doc_ids(base: DBIngestionRun) -> list[UUID]:
    doc_ids: list[UUID] = []
    for document in (getattr(base, "documents", None) or []):
        document_id = getattr(document, "document_id", None)
        if document_id:
            doc_ids.append(document_id)
        if len(doc_ids) >= 2000:
            break
    if not doc_ids:
        raise HTTPException(status_code=400, detail="No documents to replay")
    return doc_ids


def _audit_replay_creation(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    new_run: DBIngestionRun,
    base: DBIngestionRun,
    doc_ids: list[UUID],
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ingestion.run.replay",
            resource_type="ingestion_run",
            resource_id=str(new_run.id),
            details={
                "base_run_id": str(base.id),
                "dataset_id": str(getattr(base, "dataset_id", None)) if getattr(base, "dataset_id", None) else None,
                "documents": int(len(doc_ids)),
            },
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()


def _attach_replay_documents(*, db: Session, tenant_id: UUID, run_id: UUID, doc_ids: list[UUID]) -> None:
    for doc_id in doc_ids[:2000]:
        try:
            IngestionRunService.add_document(
                db,
                tenant_id=tenant_id,
                run_id=run_id,
                document_id=doc_id,
                source_ref=None,
                initial_status="pending",
                doc_meta=None,
            )
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)


async def _run_replay_retries(
    *,
    tenant_id: UUID,
    account_id: str,
    new_run_id: UUID,
    doc_ids: list[UUID],
) -> None:
    from app.api.v1.documents import retry_document_processing
    from app.core.database import SessionLocal
    from app.models.document import Document as DBDocument

    db0 = SessionLocal()
    try:
        for doc_id in (doc_ids or [])[:2000]:
            try:
                doc = db0.query(DBDocument).filter(DBDocument.id == doc_id, DBDocument.tenant_id == tenant_id).first()
                if doc is not None:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                    meta0["last_ingestion_run_id"] = str(new_run_id)
                    meta0["last_ingestion_kind"] = "replay"
                    doc.doc_metadata = meta0
                    db0.commit()
                    with contextlib.suppress(Exception):
                        db0.refresh(doc)
            except Exception:
                with contextlib.suppress(Exception):
                    db0.rollback()

            bg = BackgroundTasks()
            try:
                await retry_document_processing(
                    document_id=doc_id,
                    background_tasks=bg,
                    force=True,
                    skip_if_unchanged=False,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    db=db0,
                )
            except Exception:
                with contextlib.suppress(Exception):
                    db0.rollback()
                continue
            with contextlib.suppress(Exception):
                if getattr(bg, "tasks", None):
                    await bg()
    finally:
        db0.close()


@router.get("/runs", response_model=IngestionRunListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_ingestion_runs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    dataset_id: UUID | None = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
    kind: Annotated[str | None, Query(max_length=80)] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List ingestion runs (requires dataset write permission for each returned run's dataset)."""
    member = DatasetService.ensure_member(db, tenant_id, account_id)

    q = db.query(DBIngestionRun).filter(DBIngestionRun.tenant_id == tenant_id)
    if dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)
        q = q.filter(DBIngestionRun.dataset_id == dataset_id)
    elif str(getattr(member, "role", "") or "").lower() not in EDIT_ROLES:
        return IngestionRunListResponse(total=0, items=[])
    else:
        q = q.filter(DBIngestionRun.dataset_id.in_(_writable_dataset_ids_subquery(tenant_id=tenant_id, account_id=account_id)))

    status_norm = str(status or "").strip().lower()
    if status_norm:
        q = q.filter(DBIngestionRun.status == status_norm)

    kind_norm = str(kind or "").strip()
    if kind_norm:
        q = q.filter(DBIngestionRun.kind == kind_norm)

    total = int(q.count())
    runs = (
        q.options(selectinload(DBIngestionRun.documents))
        .order_by(DBIngestionRun.created_at.desc())
        .offset(skip)
        .limit(limit)
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
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(DBIngestionRun)
        .options(selectinload(DBIngestionRun.documents))
        .filter(DBIngestionRun.id == run_id, DBIngestionRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Ingestion run not found")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

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
    run = get_ingestion_run(run_id=run_id, tenant_id=tenant_id, account_id=account_id, db=db)  # type: ignore[arg-type]

    # Best-effort audit log (PII-minimal): record export operation.
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ingestion.run.export_json",
            resource_type="ingestion_run",
            resource_id=str(run_id),
            details={
                "dataset_id": str(getattr(run, "dataset_id", None)) if getattr(run, "dataset_id", None) else None,
                "kind": str(getattr(run, "kind", "") or ""),
                "status": str(getattr(run, "status", "") or ""),
                "documents": int(len(getattr(run, "documents", None) or [])),
            },
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    content = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(run.kind or "ingestion"))[:64]
    filename = f"{safe}.run.{str(run.id)[:8]}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers=download_response_headers(filename),
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

    run = get_ingestion_run(run_id=run_id, tenant_id=tenant_id, account_id=account_id, db=db)  # type: ignore[arg-type]

    # Best-effort audit log (PII-minimal): record export operation.
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ingestion.run.export_html",
            resource_type="ingestion_run",
            resource_id=str(run_id),
            details={
                "dataset_id": str(getattr(run, "dataset_id", None)) if getattr(run, "dataset_id", None) else None,
                "kind": str(getattr(run, "kind", "") or ""),
                "status": str(getattr(run, "status", "") or ""),
                "documents": int(len(getattr(run, "documents", None) or [])),
            },
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    payload = run.model_dump(mode="json")
    title = "MimirQ · Ingestion Run Manifest"
    html = render_dataset_report_html(
        title=title,
        dataset_name=str(payload.get("kind") or "ingestion_run"),
        dataset_id=str(payload.get("id") or ""),
        generated_at=payload.get("created_at"),
        report=payload,
        redact=False,
    )
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(run.kind or "ingestion"))[:64]
    filename = f"{safe}.run.{str(run.id)[:8]}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=download_response_headers(filename),
    )


@router.get("/runs/{run_id}/compare/{other_run_id}", response_model=IngestionRunCompareResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def compare_ingestion_runs(
    run_id: UUID,
    other_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Compare two ingestion runs (same ACL as get)."""
    a = get_ingestion_run(run_id=run_id, tenant_id=tenant_id, account_id=account_id, db=db)  # type: ignore[arg-type]
    b = get_ingestion_run(run_id=other_run_id, tenant_id=tenant_id, account_id=account_id, db=db)  # type: ignore[arg-type]

    # Load ORM rows for diff (best-effort; avoid duplicate queries when possible).
    row_a = db.query(DBIngestionRun).filter(DBIngestionRun.id == run_id, DBIngestionRun.tenant_id == tenant_id).first()
    row_b = db.query(DBIngestionRun).filter(DBIngestionRun.id == other_run_id, DBIngestionRun.tenant_id == tenant_id).first()
    diff = {}
    if row_a is not None and row_b is not None:
        diff = IngestionRunService.compare_runs(run_a=row_a, run_b=row_b)

    # Best-effort audit log (PII-minimal): record compare operation.
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="ingestion.run.compare",
            resource_type="ingestion_run",
            resource_id=str(run_id),
            details={
                "other_run_id": str(other_run_id),
                "dataset_id": str(getattr(a, "dataset_id", None)) if getattr(a, "dataset_id", None) else None,
            },
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    return IngestionRunCompareResponse(run_a=a, run_b=b, diff=diff)


@router.post("/runs/{run_id}/replay", response_model=IngestionRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
    base = _load_replay_base_run(db=db, run_id=run_id, tenant_id=tenant_id, account_id=account_id)
    doc_ids = _collect_replay_doc_ids(base)

    new_run = IngestionRunService.create_run(
        db,
        tenant_id=tenant_id,
        dataset_id=getattr(base, "dataset_id", None),
        requested_by=account_id,
        kind="replay",
        config={"replay_of": str(base.id), "base_kind": str(getattr(base, "kind", "") or "")},
        expected_documents=len(doc_ids),
    )

    _audit_replay_creation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        new_run=new_run,
        base=base,
        doc_ids=doc_ids,
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
