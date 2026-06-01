"""
Persistent conversation summary memory.

This is used as a compact, durable memory layer that can be injected into prompts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import Message
from app.models.conversation_summary import ConversationSummary
from app.rag.core.logging import get_logger
from app.rag.engine import get_rag_engine
from app.rag.memory.short_term import summarize_messages

logger = get_logger(__name__)


def get_conversation_summary(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> str | None:
    row = (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.conversation_id == conversation_id,
        )
        .first()
    )
    if not row:
        return None
    text = (row.summary or "").strip()
    return text or None


def clear_conversation_summary(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> None:
    row = (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.conversation_id == conversation_id,
        )
        .first()
    )
    if not row:
        return
    db.delete(row)
    db.commit()


async def update_conversation_summary(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    max_summary_tokens: int | None = None,
    lookback_messages: int | None = None,
) -> str:
    """
    Recompute and persist the conversation summary from the latest messages.

    This is intended to be called on-demand (API) or optionally after chat turns.
    """
    max_summary_tokens = int(
        max_summary_tokens
        or getattr(settings, "PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS", 500)
        or 500
    )
    lookback_messages = int(
        lookback_messages
        or getattr(settings, "PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES", 20)
        or 20
    )
    max_summary_tokens = max(50, max_summary_tokens)
    lookback_messages = max(2, min(200, lookback_messages))

    rows = (
        db.query(Message.role, Message.content, Message.created_at)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
        )
        .order_by(Message.created_at.desc())
        .limit(lookback_messages)
        .all()
    )
    # Reverse to chronological order for summarization.
    rows = list(reversed(rows))

    msgs = [{"role": str(role or ""), "content": str(content or "")} for role, content, _ts in rows]

    engine = get_rag_engine()
    llm = engine.models.get("fast") or engine.models.get("default") or engine.models.get("heavy")

    summary = await summarize_messages(msgs, llm=llm, max_summary_tokens=max_summary_tokens)
    summary = (summary or "").strip()
    if not summary:
        summary = "(empty summary)"

    row = (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.conversation_id == conversation_id,
        )
        .first()
    )
    if not row:
        row = ConversationSummary(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            summary=summary,
            last_message_count=len(rows),
        )
        db.add(row)
    else:
        row.summary = summary
        row.last_message_count = len(rows)

    # Best-effort timestamps for non-Postgres backends.
    try:
        row.updated_at = datetime.now(UTC)
    except Exception as exc:
        logger.debug("Ignoring conversation summary timestamp update failure: %s", exc)

    db.commit()
    return summary
