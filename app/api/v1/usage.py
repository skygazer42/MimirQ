"""
Usage / cost endpoints (admin-only).

Focus: low-friction, DB-backed aggregates for chat token usage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.chat import Message
from app.services.dataset_service import DatasetService

router = APIRouter()

_ADMIN_ROLES = {"owner", "admin"}


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="No permission to access usage dashboards")


class ChatTokenUsageRow(BaseModel):
    dataset_id: Optional[str] = None
    assistant_messages: int
    assistant_tokens: int


class ChatTokenUsageSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    total_assistant_messages: int
    total_assistant_tokens: int
    by_dataset: List[ChatTokenUsageRow]


@router.get("/chat/tokens/summary", response_model=ChatTokenUsageSummary)
def get_chat_token_usage_summary(
    window_days: int = Query(default=1, ge=1, le=30),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Summarize assistant token usage grouped by dataset_id (when available).

    Notes:
    - dataset_id is stored in Message.message_metadata by chat endpoints when request scope maps to a single dataset.
    - For multi-dataset chats (or legacy rows), dataset_id may be null.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(timezone.utc)
    window_end = until or now
    window_start = since or (window_end - timedelta(days=int(window_days or 1)))

    # Postgres JSONB expression (used elsewhere in the codebase); safe in production deployments.
    dataset_expr = Message.message_metadata["dataset_id"].astext  # type: ignore[attr-defined]

    rows = (
        db.query(
            dataset_expr.label("dataset_id"),
            func.count(Message.id).label("messages"),
            func.coalesce(func.sum(Message.token_count), 0).label("tokens"),
        )
        .filter(
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
            Message.created_at >= window_start,
            Message.created_at <= window_end,
        )
        .group_by(dataset_expr)
        .order_by(func.coalesce(func.sum(Message.token_count), 0).desc())
        .all()
    )

    items: list[ChatTokenUsageRow] = []
    total_msgs = 0
    total_tokens = 0
    for ds_id, messages, tokens in rows:
        m = int(messages or 0)
        t = int(tokens or 0)
        total_msgs += m
        total_tokens += t
        items.append(
            ChatTokenUsageRow(
                dataset_id=str(ds_id) if ds_id is not None else None,
                assistant_messages=m,
                assistant_tokens=t,
            )
        )

    return ChatTokenUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=total_msgs,
        total_assistant_tokens=total_tokens,
        by_dataset=items,
    )

