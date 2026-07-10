
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.documents import Document
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
    """
    Simple long-term memory recall using BM25 over past messages.
    Used to enrich history context only; it does not modify storage.
    """
    max_messages = int(getattr(settings, "LONG_TERM_MEMORY_MAX_MESSAGES", 200) or 0)
    query_builder = (
        db.query(Message.content, Message.role, Message.created_at)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.created_at.desc())
    )
    if max_messages > 0:
        query_builder = query_builder.limit(max_messages)

    rows = query_builder.all()
    if not rows:
        return []

    rows = list(reversed(rows))

    docs: list[Document] = []
    for content, role, created_at in rows:
        if not content or len(content.strip()) < settings.LONG_TERM_MEMORY_MIN_LEN:
            continue
        docs.append(
            Document(
                page_content=content,
                metadata={
                    "role": role,
                    "created_at": created_at.isoformat() if created_at else None,
                },
            )
        )

    if not docs:
        return []

    retriever = BM25Retriever.from_documents(
        docs,
        preprocess_func=tokenize_for_bm25,
        k=top_k,
    )
    selected = retriever.invoke(query)

    enriched_history = []
    for doc in selected:
        enriched_history.append(
            {
                "role": doc.metadata.get("role", "assistant"),
                "content": doc.page_content,
                "from_long_term": True,
                "ts": doc.metadata.get("created_at"),
            }
        )
    return enriched_history


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
    lim = max(0, int(max_messages or 0))
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
    conversation_id: UUID | None,
) -> None:
    if conversation_id is None:
        return
    if not hasattr(db, "query"):
        return
    db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
    ).update(
        {
            "updated_at": datetime.now(UTC),
        },
        synchronize_session=False,
    )
