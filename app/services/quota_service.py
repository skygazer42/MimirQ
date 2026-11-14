"""
Quota helpers (best-effort).

Currently supports a rolling per-tenant assistant-token quota for chat.
"""

from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import Message


class ChatAssistantTokenQuota(TypedDict):
    enabled: bool
    limit: int
    used: int
    window_hours: int
    exceeded: bool
    mode: str


def check_chat_assistant_token_quota(
    db: Session,
    *,
    tenant_id: UUID,
) -> ChatAssistantTokenQuota:
    """
    Return quota status for assistant tokens in a rolling time window.

    This is designed to be:
    - best-effort: failures disable enforcement
    - cheap enough for production (single aggregate query)
    """
    enabled = settings.CHAT_ASSISTANT_TOKEN_QUOTA_ENABLED
    limit = settings.CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT
    window_hours = settings.CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS or 24
    mode = (settings.CHAT_ASSISTANT_TOKEN_QUOTA_MODE or "block").lower()

    if not enabled or limit <= 0:
        return {"enabled": False, "limit": 0, "used": 0, "window_hours": window_hours, "exceeded": False, "mode": mode}

    window_hours = max(1, window_hours)
    since = datetime.now(UTC) - timedelta(hours=window_hours)

    try:
        used_raw = (
            db.query(func.coalesce(func.sum(Message.token_count), 0))
            .filter(
                Message.tenant_id == tenant_id,
                Message.role == "assistant",
                Message.created_at >= since,
            )
            .scalar()
        )
        used = int(used_raw or 0)
    except Exception:
        # Fail open.
        return {
            "enabled": False,
            "limit": limit,
            "used": 0,
            "window_hours": window_hours,
            "exceeded": False,
            "mode": mode,
        }

    exceeded = used >= limit
    return {
        "enabled": True,
        "limit": limit,
        "used": used,
        "window_hours": window_hours,
        "exceeded": exceeded,
        "mode": mode,
    }
