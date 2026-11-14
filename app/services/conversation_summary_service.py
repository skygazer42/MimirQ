"""
Persistent conversation summary memory.

This is used as a compact, durable memory layer that can be injected into prompts.
"""

from datetime import UTC, datetime
from uuid import UUID

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import Message
from app.models.conversation_summary import ConversationSummary
from app.rag.core.logging import get_logger
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session

logger = get_logger(__name__)


async def _summarize_messages(
    messages: list[dict[str, str]],
    llm: BaseLanguageModel | None,
    max_summary_tokens: int = 500,
) -> str:
    if not messages:
        return ""

    conversation = "\n".join(f"{message['role']}: {message['content']}" for message in messages)
    if llm is None:
        logger.debug("No LLM provided for summarization, using truncation fallback")
        truncated = conversation[: max_summary_tokens * 4]
        if len(conversation) > len(truncated):
            truncated += "..."
        return f"[Previous conversation summary]\n{truncated}"

    prompt = f"""Summarize the following conversation concisely, preserving key information:

{conversation}

Summary (be concise, focus on key facts and decisions):"""
    try:
        response = await llm.ainvoke(prompt)
    except Exception as exc:
        logger.warning("LLM summarization failed: %s", exc)
        return f"[Previous conversation]\n{conversation[: max_summary_tokens * 4]}..."

    # Chat models return messages; the configured development model returns text.
    summary = response.content if isinstance(response, BaseMessage) else response
    return f"[Conversation summary]\n{summary}"


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
    if row is None:
        return None
    return row.summary


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
    if row is None:
        return
    db.delete(row)
    db.commit()


def _load_summary_messages(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    lookback_messages: int,
) -> list[dict[str, str]]:
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
    return [{"role": role, "content": content} for role, content, _ts in reversed(rows)]


def _save_conversation_summary(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    summary: str,
    message_count: int,
) -> None:
    values = {"summary": summary, "last_message_count": message_count, "updated_at": datetime.now(UTC)}
    statement = insert(ConversationSummary).values(tenant_id=tenant_id, conversation_id=conversation_id, **values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[ConversationSummary.tenant_id, ConversationSummary.conversation_id],
            set_=values,
        )
    )
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
    max_summary_tokens = int(max_summary_tokens or settings.PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS or 500)
    lookback_messages = int(lookback_messages or settings.PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES or 20)
    max_summary_tokens = max(50, max_summary_tokens)
    lookback_messages = max(2, min(200, lookback_messages))

    messages = await run_blocking_call_with_managed_session(
        lambda worker_db: _load_summary_messages(
            worker_db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            lookback_messages=lookback_messages,
        ),
        request_db=db,
    )

    from app.rag.engine import get_rag_engine

    engine = get_rag_engine()
    llm = engine.models.get("fast") or engine.models.get("default") or engine.models.get("heavy")
    summary = await _summarize_messages(messages, llm=llm, max_summary_tokens=max_summary_tokens)
    summary = summary.strip()
    if not summary:
        summary = "(empty summary)"

    await run_blocking_call_with_managed_session(
        lambda worker_db: _save_conversation_summary(
            worker_db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            summary=summary,
            message_count=len(messages),
        ),
        request_db=db,
    )
    return summary
