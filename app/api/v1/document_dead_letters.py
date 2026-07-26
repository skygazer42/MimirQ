import contextlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import IngestDeadLetterList, IngestDeadLetterReplayResponse
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.ingest_dead_letter import IngestDeadLetter
from app.services.dataset_service import DatasetService
from app.services.document_access import build_dataset_read_filter, build_document_read_filter
from app.services.document_access_service import assert_document_writable_for_lifecycle
from app.services.ingest_dead_letter_service import mark_dead_letter_replayed

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
}

router = APIRouter(prefix="/dead-letters", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("", response_model=IngestDeadLetterList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_ingest_dead_letters(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
    status: Annotated[str | None, Query(max_length=20)] = "open",
    dataset_id: UUID | None = None,
    document_id: UUID | None = None,
    error_code: Annotated[str | None, Query(max_length=100)] = None,
    failed_stage: Annotated[str | None, Query(max_length=50)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict:
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = aliased(DBDocument)
    readable_dataset_ids = select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        build_dataset_read_filter(tenant_id=tenant_id, account_id=account_id),
    )

    query = (
        db.query(IngestDeadLetter)
        .outerjoin(
            document,
            and_(document.id == IngestDeadLetter.document_id, document.tenant_id == tenant_id),
        )
        .filter(IngestDeadLetter.tenant_id == tenant_id)
        .filter(
            or_(
                and_(
                    document.id.isnot(None),
                    or_(document.dataset_id.is_(None), document.dataset_id.in_(readable_dataset_ids)),
                    build_document_read_filter(
                        tenant_id=tenant_id,
                        account_id=account_id,
                        document_model=document,
                    ),
                ),
                and_(
                    IngestDeadLetter.document_id.is_(None),
                    IngestDeadLetter.dataset_id.isnot(None),
                    IngestDeadLetter.dataset_id.in_(readable_dataset_ids),
                ),
            )
        )
    )
    if status and status != "all":
        query = query.filter(IngestDeadLetter.status == status.strip().lower())
    if dataset_id is not None:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(IngestDeadLetter.dataset_id == dataset_id)
    if document_id is not None:
        query = query.filter(IngestDeadLetter.document_id == document_id)
    if error_code:
        query = query.filter(IngestDeadLetter.error_code == error_code.strip().lower())
    if failed_stage:
        query = query.filter(IngestDeadLetter.failed_stage == failed_stage.strip().lower())

    total = int(query.count())
    items = query.order_by(IngestDeadLetter.last_attempt_at.desc(), IngestDeadLetter.id.asc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.post(
    "/{dead_letter_id}/replay",
    response_model=IngestDeadLetterReplayResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def replay_ingest_dead_letter(
    dead_letter_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    DatasetService.ensure_member(db, tenant_id, account_id)
    dead_letter = (
        db.query(IngestDeadLetter)
        .filter(IngestDeadLetter.id == dead_letter_id, IngestDeadLetter.tenant_id == tenant_id)
        .first()
    )
    if dead_letter is None:
        raise HTTPException(status_code=404, detail="Dead letter not found")
    if dead_letter.document_id is None:
        raise HTTPException(status_code=409, detail="Dead letter has no reprocessable document")

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == dead_letter.document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    from app.api.v1.document_processing import retry_document_processing

    document_status = await retry_document_processing(
        document_id=dead_letter.document_id,
        background_tasks=background_tasks,
        force=str(document.status or "").strip().lower() == "completed",
        skip_if_unchanged=False,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    with contextlib.suppress(Exception):
        dead_letter = mark_dead_letter_replayed(db, dead_letter=dead_letter)

    return {
        "dead_letter_id": dead_letter_id,
        "document_id": dead_letter.document_id,
        "dead_letter_status": getattr(dead_letter, "status", "replayed"),
        "document_status": document_status,
    }
