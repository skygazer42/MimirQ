from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import IngestDeadLetterList, IngestDeadLetterListQuery, IngestDeadLetterReplayResponse
from app.core.async_bridge import run_blocking_in_thread
from app.core.database import SessionLocal, get_db
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.ingest_dead_letter import IngestDeadLetter
from app.services import dataset_service
from app.services.document_access import build_dataset_read_filter, build_document_read_filter
from app.services.document_access_service import assert_document_writable_for_lifecycle
from app.services.ingest_dead_letter_service import mark_dead_letter_replayed

router = APIRouter(
    prefix="/dead-letters",
    responses={
        400: {"description": "Bad Request"},
        403: {"description": "Forbidden"},
        404: {"description": "Not Found"},
        409: {"description": "Conflict"},
    },
)


@router.get("", response_model=IngestDeadLetterList)
def list_ingest_dead_letters(
    params: Annotated[IngestDeadLetterListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> IngestDeadLetterList:
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = aliased(Document)
    readable_dataset_ids = select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        build_dataset_read_filter(tenant_id=tenant_id, account_id=account_id),
    )
    document_access_filter = and_(
        document.id.isnot(None),
        or_(document.dataset_id.is_(None), document.dataset_id.in_(readable_dataset_ids)),
        build_document_read_filter(tenant_id=tenant_id, account_id=account_id, document_model=document),
    )
    dataset_access_filter = and_(
        IngestDeadLetter.document_id.is_(None),
        IngestDeadLetter.dataset_id.isnot(None),
        IngestDeadLetter.dataset_id.in_(readable_dataset_ids),
    )
    query = (
        db.query(IngestDeadLetter)
        .outerjoin(
            document,
            and_(document.id == IngestDeadLetter.document_id, document.tenant_id == tenant_id),
        )
        .filter(IngestDeadLetter.tenant_id == tenant_id)
        .filter(or_(document_access_filter, dataset_access_filter))
    )
    if params.status and params.status != "all":
        query = query.filter(IngestDeadLetter.status == params.status.strip().lower())
    if params.dataset_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
        dataset_service.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(IngestDeadLetter.dataset_id == params.dataset_id)
    if params.document_id is not None:
        query = query.filter(IngestDeadLetter.document_id == params.document_id)
    if params.error_code:
        query = query.filter(IngestDeadLetter.error_code == params.error_code.strip().lower())
    if params.failed_stage:
        query = query.filter(IngestDeadLetter.failed_stage == params.failed_stage.strip().lower())

    total = query.count()
    items = (
        query.order_by(IngestDeadLetter.last_attempt_at.desc(), IngestDeadLetter.id.asc())
        .offset(params.skip)
        .limit(params.limit)
        .all()
    )
    return IngestDeadLetterList(total=total, items=items)


def _load_dead_letter_replay(dead_letter_id: UUID, *, tenant_id: UUID, account_id: str) -> tuple[UUID, bool]:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)
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
            db.query(Document).filter(Document.id == dead_letter.document_id, Document.tenant_id == tenant_id).first()
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        assert_document_writable_for_lifecycle(db, tenant_id=tenant_id, account_id=account_id, document=document)
        return dead_letter.document_id, document.status.strip().lower() == "completed"


def _mark_dead_letter_replayed(dead_letter_id: UUID, *, tenant_id: UUID) -> str:
    with SessionLocal() as db:
        dead_letter = (
            db.query(IngestDeadLetter)
            .filter(IngestDeadLetter.id == dead_letter_id, IngestDeadLetter.tenant_id == tenant_id)
            .first()
        )
        if dead_letter is None:
            raise HTTPException(status_code=404, detail="Dead letter not found")
        return mark_dead_letter_replayed(db, dead_letter=dead_letter).status


@router.post("/{dead_letter_id}/replay", response_model=IngestDeadLetterReplayResponse)
async def replay_ingest_dead_letter(
    dead_letter_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> IngestDeadLetterReplayResponse:
    document_id, force = await run_blocking_in_thread(
        _load_dead_letter_replay, dead_letter_id, tenant_id=tenant_id, account_id=account_id
    )
    from app.services.document_processing_operations import retry_document

    document_status = await retry_document(
        document_id=document_id,
        background_tasks=background_tasks,
        force=force,
        skip_if_unchanged=False,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    status = await run_blocking_in_thread(_mark_dead_letter_replayed, dead_letter_id, tenant_id=tenant_id)

    return IngestDeadLetterReplayResponse(
        dead_letter_id=dead_letter_id,
        document_id=document_id,
        dead_letter_status=status,
        document_status=document_status,
    )
