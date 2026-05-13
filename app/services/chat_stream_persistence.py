from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.models.chat import Conversation, Message
from app.services.audit_log_service import audit_log_event, build_chat_audit_details
from app.services.chat_memory_runtime import _touch_conversation_after_turn
from app.services.chat_runtime import (
    ChatStreamPersistInput,
    _resolve_chat_stream_persist_input,
    store_chat_response_cache_if_needed,
)
from app.services.chat_turn_persistence import (
    auto_update_summary_background,
    build_chat_message_metadata,
)
from app.services.structured_memory_service import extract_structured_memory_for_turn


def dispatch_chat_stream_persistence(
    *,
    db: Session,
    persist_in_background: bool,
    spawn_background_task: Callable[[Any], None],
    options: ChatStreamPersistInput,
) -> None:
    if persist_in_background:
        with contextlib.suppress(Exception):
            spawn_background_task(
                persist_chat_stream_turn_background(
                    options=options,
                )
            )
        return

    persist_chat_stream_turn_sync(
        db=db,
        tenant_id=options.tenant_id,
        conversation_id=options.conversation_id,
        account_id=options.account_id,
        assistant_message_id=options.assistant_message_id,
        request_id=options.request_id,
        question=options.question,
        document_count=options.document_count,
        content=options.content,
        citations=options.citations,
        metrics=options.metrics,
        dataset_id_used=options.dataset_id_used,
        cache_hit=options.cache_hit,
        ip=options.ip,
        user_agent=options.user_agent,
        enable_structured_memory=options.enable_structured_memory,
    )

    should_update_summary = (
        bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
        and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
        and bool(options.enable_summary_memory)
        and bool(options.conversation_id)
    )
    if should_update_summary:
        with contextlib.suppress(Exception):
            spawn_background_task(
                auto_update_summary_background(
                    tenant_id=options.tenant_id,
                    conversation_id=options.conversation_id,
                )
            )


def persist_chat_stream_turn_sync(
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
        content=content or "",
        citations=citations if isinstance(citations, list) else [],
        token_count=num_tokens_from_string(content or ""),
        message_metadata=message_metadata,
    )
    db.add(assistant_message)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="chat.stream",
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


async def persist_chat_stream_turn_background(
    *,
    options: ChatStreamPersistInput | None = None,
    **legacy_overrides: Any,
) -> None:
    persist_input = _resolve_chat_stream_persist_input(
        options=options,
        legacy_overrides=legacy_overrides,
    )
    tenant_id = persist_input.tenant_id
    conversation_id = persist_input.conversation_id
    account_id = persist_input.account_id
    assistant_message_id = persist_input.assistant_message_id
    request_id = persist_input.request_id
    question = persist_input.question
    document_count = persist_input.document_count
    content = persist_input.content
    citations = persist_input.citations
    metrics = persist_input.metrics
    dataset_id_used = persist_input.dataset_id_used
    cache_hit = persist_input.cache_hit
    cache_key = persist_input.cache_key
    cache_eligible = persist_input.cache_eligible
    structured_data = persist_input.structured_data
    ip = persist_input.ip
    user_agent = persist_input.user_agent
    enable_summary_memory = persist_input.enable_summary_memory
    enable_structured_memory = persist_input.enable_structured_memory

    should_update_summary = (
        bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
        and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
        and bool(enable_summary_memory)
        and bool(conversation_id)
    )

    def _persist_sync() -> bool:
        try:
            from app.core.database import SessionLocal  # noqa: WPS433

            db2 = SessionLocal()
            try:
                metrics2 = dict(metrics or {})
                store_chat_response_cache_if_needed(
                    cache_eligible=cache_eligible,
                    cache_hit=cache_hit,
                    cache_key=cache_key,
                    content=content,
                    citations=citations,
                    metrics=metrics2,
                    structured_data=structured_data,
                )

                message_metadata = build_chat_message_metadata(
                    request_id=str(request_id),
                    original_question=question,
                    metrics=metrics2,
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
                    content=content or "",
                    citations=citations if isinstance(citations, list) else [],
                    token_count=num_tokens_from_string(content or ""),
                    message_metadata=message_metadata,
                )
                db2.add(assistant_message)

                audit_log_event(
                    db2,
                    tenant_id=tenant_id,
                    actor_id=account_id,
                    action="chat.stream",
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

                conversation = (
                    db2.query(Conversation)
                    .filter(
                        Conversation.id == conversation_id,
                        Conversation.tenant_id == tenant_id,
                    )
                    .first()
                )
                if conversation is not None:
                    conversation.message_count = int(conversation.message_count or 0) + 1
                    conversation.updated_at = datetime.now(UTC).replace(tzinfo=None)

                db2.commit()
            finally:
                try:
                    db2.close()
                except Exception:
                    pass

            return True
        except Exception:
            return False

    ok = await asyncio.to_thread(_persist_sync)
    if not ok:
        return

    if should_update_summary:
        with contextlib.suppress(Exception):
            await auto_update_summary_background(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )
