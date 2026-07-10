"""
Quota helpers (best-effort).

Currently supports a rolling per-tenant assistant-token quota for chat.
"""


from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import Message


def check_chat_assistant_token_quota(
    db: Session,
    *,
    tenant_id: UUID,
) -> dict[str, Any]:
    """
    Return quota status for assistant tokens in a rolling time window.

    This is designed to be:
    - best-effort: failures disable enforcement
    - cheap enough for production (single aggregate query)
    """
    enabled = bool(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_ENABLED", False))
    limit = int(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT", 0) or 0)
    window_hours = int(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS", 24) or 24)
    mode = str(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_MODE", "block") or "block").lower()

    if not enabled or limit <= 0:
        return {"enabled": False, "limit": 0, "used": 0, "window_hours": window_hours, "exceeded": False, "mode": mode}

    window_hours = max(1, window_hours)
    since = datetime.now(UTC) - timedelta(hours=window_hours)

    used = 0
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
        return {"enabled": False, "limit": limit, "used": 0, "window_hours": window_hours, "exceeded": False, "mode": mode}

    exceeded = used >= limit
    return {"enabled": True, "limit": limit, "used": used, "window_hours": window_hours, "exceeded": exceeded, "mode": mode}

