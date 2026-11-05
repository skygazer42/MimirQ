from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import Conversation, Message
from app.rag.core.logging import get_logger
from app.rag.preprocessing.tokenization import tokenize_for_bm25

logger = get_logger("services.chat_memory_runtime")


def _retrieve_long_term_messages(
    db: Session,
    conversation_id: UUID,
    tenant_id: UUID,
    query: str,
    top_k: int = 3,
) -> list[dict]:
    """Rank matching recent conversation messages in the database without a local index."""
    if not query.strip() or top_k <= 0:
        return []
    terms = list(dict.fromkeys(token.lower() for token in tokenize_for_bm25(query) if token))[:32]
    if not terms:
        return []
    max_messages = settings.LONG_TERM_MEMORY_MAX_MESSAGES
    if max_messages <= 0:
        raise ValueError("LONG_TERM_MEMORY_MAX_MESSAGES must be positive for bounded memory retrieval")
    query_builder = (
        db.query(Message.id, Message.content, Message.role, Message.created_at)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
    )
    recent = query_builder.limit(max_messages).subquery()
    score = sum(case((recent.c.content.icontains(term, autoescape=True), 1), else_=0) for term in terms)
    rows = (
        db.query(recent.c.content, recent.c.role, recent.c.created_at)
        .filter(score > 0, func.length(func.trim(recent.c.content)) >= settings.LONG_TERM_MEMORY_MIN_LEN)
        .order_by(score.desc(), recent.c.created_at.desc(), recent.c.id.desc())
        .limit(top_k)
        .all()
    )
    return [
        {"role": role, "content": content, "from_long_term": True, "ts": created_at.isoformat() if created_at else None}
        for content, role, created_at in rows
    ]


def _retrieve_structured_memory_records(
    *,
    db: Session,
    conversation_id: UUID,
    tenant_id: UUID,
    max_messages: int,
) -> list[dict[str, Any]]:
    """
    Retrieve structured memory records stored in Message.message_metadata.

    Notes:
    - Best-effort: only assistant messages can carry records (we write them there).
    - Keeps DB reads bounded by max_messages.
    """
    lim = max(0, max_messages)
    if lim <= 0:
        return []
    rows = (
        db.query(Message.message_metadata)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc())
        .limit(lim)
        .all()
    )
    out: list[dict[str, Any]] = []
    for (meta,) in rows:
        if not isinstance(meta, dict):
            continue
        rec = meta.get("structured_memory")
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _touch_conversation_after_turn(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
) -> None:
    db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
    ).update(
        {
            "updated_at": datetime.now(UTC),
        },
        synchronize_session=False,
    )
