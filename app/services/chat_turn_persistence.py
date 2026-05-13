from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.models.chat import Message
from app.services.audit_log_service import audit_log_event, build_chat_audit_details
from app.services.chat_memory_runtime import _touch_conversation_after_turn
from app.services.conversation_summary_service import update_conversation_summary
from app.services.structured_memory_service import extract_structured_memory_for_turn


def build_chat_message_metadata(
    *,
    request_id: str,
    original_question: str | None,
    metrics: dict[str, Any] | None,
    citations: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    out["request_id"] = str(request_id)

    rewritten = str((out.get("query_for_retrieval") or "")).strip()
    question = str(original_question or "").strip()
    out["rewritten_query"] = rewritten if rewritten and rewritten != question else None

    retrieved_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in citations or []:
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
            except Exception:
                pass
    except Exception:
        return


def persist_chat_turn_sync(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    account_id: str,
    assistant_message_id: UUID,
    request_id: str,
    question: str,
    document_count: int,
    content: str,
    citations: list,
    metrics: dict,
    dataset_id_used: UUID | None,
    cache_hit: bool,
    ip: str | None,
    user_agent: str | None,
    enable_structured_memory: bool,
) -> None:
    message_metadata = build_chat_message_metadata(
        request_id=str(request_id),
        original_question=question,
        metrics=metrics,
        citations=citations if isinstance(citations, list) else [],
    )
    if enable_structured_memory and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False)):
        try:
            message_metadata["structured_memory"] = extract_structured_memory_for_turn(
                user_text=str(question or ""),
                assistant_text=str(content or ""),
                max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
            )
        except Exception:
            pass

    assistant_message = Message(
        id=assistant_message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        citations=citations,
        token_count=num_tokens_from_string(content or ""),
        message_metadata=message_metadata,
    )
    db.add(assistant_message)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="chat.ask",
        resource_type="conversation",
        resource_id=str(conversation_id),
        request_id=str(request_id),
        ip=ip,
        user_agent=user_agent,
        details=build_chat_audit_details(
            question=question,
            document_count=int(document_count or 0),
            dataset_id=dataset_id_used,
            cache_hit=cache_hit,
        ),
    )

    _touch_conversation_after_turn(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    db.commit()
