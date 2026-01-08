"""
User feedback API (evaluation loop).
Currently provides minimal loop capability:
- Submit rating/reason/expected answer for assistant messages
- List queries (isolated by tenant)
"""


from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.chat import Message
from app.models.feedback import MessageFeedback
from app.api.schemas.feedback import MessageFeedbackCreateRequest, MessageFeedbackList, MessageFeedbackOut
from app.services.dataset_service import DatasetService

router = APIRouter(tags=["Feedback"])


@router.post("/messages", response_model=MessageFeedbackOut, status_code=status.HTTP_201_CREATED)
async def upsert_message_feedback(
    request: MessageFeedbackCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Submit feedback for an assistant message (idempotent: resubmit will update)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    msg = (
        db.query(Message)
        .filter(Message.id == request.message_id, Message.tenant_id == tenant_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if (msg.role or "").lower() != "assistant":
        raise HTTPException(status_code=400, detail="Only assistant messages can be rated")

    row = (
        db.query(MessageFeedback)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            MessageFeedback.message_id == msg.id,
            MessageFeedback.account_id == account_id,
        )
        .first()
    )
    if row:
        row.rating = request.rating
        row.reason = request.reason
        row.tags = request.tags
        row.expected_answer = request.expected_answer
        row.extra = request.extra
        db.commit()
        db.refresh(row)
        return row

    row = MessageFeedback(
        tenant_id=tenant_id,
        conversation_id=msg.conversation_id,
        message_id=msg.id,
        account_id=account_id,
        rating=request.rating,
        reason=request.reason,
        tags=request.tags,
        expected_answer=request.expected_answer,
        extra=request.extra,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/messages", response_model=MessageFeedbackList)
async def list_message_feedback(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Query feedback list (returns all items in current tenant by default)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(MessageFeedback).filter(MessageFeedback.tenant_id == tenant_id)
    if conversation_id:
        query = query.filter(MessageFeedback.conversation_id == conversation_id)
    if message_id:
        query = query.filter(MessageFeedback.message_id == message_id)
    if min_rating is not None:
        query = query.filter(MessageFeedback.rating >= int(min_rating))
    if max_rating is not None:
        query = query.filter(MessageFeedback.rating <= int(max_rating))

    total = query.count()
    rows = (
        query.order_by(MessageFeedback.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": rows}
