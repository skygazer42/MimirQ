from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.models.chat import Conversation, Message
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event, build_chat_audit_details
from app.services.chat_memory_runtime import _touch_conversation_after_turn
from app.services.conversation_summary_service import update_conversation_summary
from app.services.structured_memory_service import extract_structured_memory_for_turn

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChatTurnPersistInput:
    tenant_id: UUID
    conversation_id: UUID
    account_id: str
    audit_action: Literal["chat.ask", "chat.stream"]
    assistant_message_id: UUID
    request_id: str
    question: str
    document_count: int
    content: str
    citations: list[Any]
    metrics: dict[str, Any]
    dataset_id_used: UUID | None
    cache_hit: bool
    ip: str | None
    user_agent: str | None
    enable_structured_memory: bool
    increment_message_count: bool = False
    touch_conversation: bool = True


def build_chat_message_metadata(
    *,
    request_id: str,
    original_question: str,
    metrics: dict[str, Any],
    citations: list[Any],
) -> dict[str, Any]:
    out = dict(metrics)
    out["request_id"] = request_id

    rewritten = str((out.get("query_for_retrieval") or "")).strip()
    question = original_question.strip()
    out["rewritten_query"] = rewritten if rewritten and rewritten != question else None

    retrieved_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        document_id = item.get("document_id")
        document_name = item.get("document_name") or item.get("source")
        chunk_id = item.get("chunk_id")
        page_number = item.get("page_number")
        key = str(document_id or document_name or chunk_id or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        retrieved_docs.append(
            {
                "document_id": str(document_id) if document_id is not None else None,
                "document_name": str(document_name) if document_name is not None else None,
                "chunk_id": str(chunk_id) if chunk_id is not None else None,
                "page_number": int(page_number) if page_number is not None else None,
            }
        )
        if len(retrieved_docs) >= 20:
            break
    out["retrieved_docs"] = retrieved_docs

    latency_keys = (
        "latency_ms",
        "elapsed_sec",
        "retrieval_elapsed_sec",
        "generation_elapsed_sec",
        "rewrite_elapsed_sec",
        "multi_query_elapsed_sec",
        "hyde_elapsed_sec",
        "decompose_elapsed_sec",
    )
    out["latency_stats"] = {key: out.get(key) for key in latency_keys if out.get(key) is not None}
    return out


async def auto_update_summary_background(*, tenant_id: UUID, conversation_id: UUID) -> None:
    try:
        from app.core.database import SessionLocal  # noqa: WPS433

        db2 = SessionLocal()
        try:
            await update_conversation_summary(db2, tenant_id=tenant_id, conversation_id=conversation_id)
        finally:
            try:
                db2.close()
            except Exception as exc:
                logger.warning(
                    "Summary update session close failed: tenant_id=%s conversation_id=%s error_type=%s",
                    tenant_id,
                    conversation_id,
                    type(exc).__name__,
                )
    except Exception as exc:
        logger.warning(
            "Conversation summary update failed: tenant_id=%s conversation_id=%s error_type=%s",
            tenant_id,
            conversation_id,
            type(exc).__name__,
        )


def _add_structured_memory_metadata(
    *,
    message_metadata: dict[str, Any],
    question: str,
    content: str,
    enabled: bool,
    log_context: str,
) -> None:
    if not enabled or not settings.STRUCTURED_MEMORY_ENABLED:
        return
    try:
        message_metadata["structured_memory"] = extract_structured_memory_for_turn(
            user_text=question,
            assistant_text=content,
            max_entities=settings.STRUCTURED_MEMORY_MAX_ENTITIES,
            max_facts=settings.STRUCTURED_MEMORY_MAX_FACTS,
        )
    except Exception as exc:
        logger.warning(
            "Structured memory extraction failed: context=%s error_type=%s",
            log_context,
            type(exc).__name__,
        )


def _increment_conversation_message_count(*, db: Session, tenant_id: UUID, conversation_id: UUID) -> None:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        .first()
    )
    if conversation is not None:
        conversation.message_count = int(conversation.message_count or 0) + 1
        conversation.updated_at = datetime.now(UTC).replace(tzinfo=None)


def persist_chat_turn_sync(
    *,
    db: Session,
    options: ChatTurnPersistInput,
) -> None:
    message_metadata = build_chat_message_metadata(
        request_id=options.request_id,
        original_question=options.question,
        metrics=options.metrics,
        citations=options.citations if isinstance(options.citations, list) else [],
    )
    _add_structured_memory_metadata(
        message_metadata=message_metadata,
        question=options.question,
        content=options.content,
        enabled=options.enable_structured_memory,
        log_context="chat turn",
    )

    assistant_message = Message(
        id=options.assistant_message_id,
        tenant_id=options.tenant_id,
        conversation_id=options.conversation_id,
        role="assistant",
        content=options.content,
        citations=options.citations,
        token_count=num_tokens_from_string(options.content),
        message_metadata=message_metadata,
    )
    db.add(assistant_message)

    audit_log_event(
        db,
        tenant_id=options.tenant_id,
        actor_id=options.account_id,
        action=options.audit_action,
        resource_type="conversation",
        resource_id=str(options.conversation_id),
        request_id=options.request_id,
        ip=options.ip,
        user_agent=options.user_agent,
        details=build_chat_audit_details(
            question=options.question,
            document_count=options.document_count,
            dataset_id=options.dataset_id_used,
            cache_hit=options.cache_hit,
        ),
    )

    if options.touch_conversation:
        _touch_conversation_after_turn(
            db=db,
            tenant_id=options.tenant_id,
            conversation_id=options.conversation_id,
        )
    if options.increment_message_count:
        _increment_conversation_message_count(
            db=db,
            tenant_id=options.tenant_id,
            conversation_id=options.conversation_id,
        )
    db.commit()
