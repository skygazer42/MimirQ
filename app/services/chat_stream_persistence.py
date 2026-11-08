import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.chat_cache_runtime import store_chat_response_cache_if_needed
from app.services.chat_turn_persistence import (
    ChatTurnPersistInput,
    auto_update_summary_background,
    persist_chat_turn_sync,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChatStreamPersistInput:
    tenant_id: UUID
    conversation_id: UUID
    account_id: str
    assistant_message_id: UUID
    request_id: str
    question: str
    document_count: int
    content: str
    citations: list[Any]
    metrics: dict[str, Any]
    dataset_id_used: UUID | None
    cache_hit: bool
    cache_key: str | None
    cache_eligible: bool
    structured_data: object | None
    ip: str | None
    user_agent: str | None
    enable_summary_memory: bool
    enable_structured_memory: bool


def _chat_turn_persist_input(
    *,
    options: ChatStreamPersistInput,
    metrics: dict[str, Any],
    increment_message_count: bool,
    touch_conversation: bool = True,
) -> ChatTurnPersistInput:
    return ChatTurnPersistInput(
        tenant_id=options.tenant_id,
        conversation_id=options.conversation_id,
        account_id=options.account_id,
        audit_action="chat.stream",
        assistant_message_id=options.assistant_message_id,
        request_id=options.request_id,
        question=options.question,
        document_count=options.document_count,
        content=options.content,
        citations=options.citations,
        metrics=metrics,
        dataset_id_used=options.dataset_id_used,
        cache_hit=options.cache_hit,
        ip=options.ip,
        user_agent=options.user_agent,
        enable_structured_memory=options.enable_structured_memory,
        increment_message_count=increment_message_count,
        touch_conversation=touch_conversation,
    )


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
        options=options,
    )

    should_update_summary = (
        settings.PERSISTENT_SUMMARY_MEMORY_ENABLED
        and settings.PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE
        and options.enable_summary_memory
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
    options: ChatStreamPersistInput,
) -> None:
    persist_chat_turn_sync(
        db=db,
        options=_chat_turn_persist_input(
            options=options,
            metrics=options.metrics,
            increment_message_count=False,
        ),
    )


async def persist_chat_stream_turn_background(
    *,
    options: ChatStreamPersistInput,
) -> None:
    should_update_summary = (
        settings.PERSISTENT_SUMMARY_MEMORY_ENABLED
        and settings.PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE
        and options.enable_summary_memory
    )

    def _persist_sync() -> bool:
        try:
            from app.core.database import SessionLocal  # noqa: WPS433

            db2 = SessionLocal()
            try:
                metrics2 = dict(options.metrics)
                store_chat_response_cache_if_needed(
                    cache_eligible=options.cache_eligible,
                    cache_hit=options.cache_hit,
                    cache_key=options.cache_key,
                    content=options.content,
                    citations=options.citations,
                    metrics=metrics2,
                    structured_data=options.structured_data,
                )
                persist_chat_turn_sync(
                    db=db2,
                    options=_chat_turn_persist_input(
                        options=options,
                        metrics=metrics2,
                        increment_message_count=True,
                        touch_conversation=False,
                    ),
                )
            finally:
                try:
                    db2.close()
                except Exception as exc:
                    logger.debug("Ignoring background chat persistence session close failure: %s", exc)

            return True
        except Exception:
            return False

    ok = await asyncio.to_thread(_persist_sync)
    if not ok:
        return

    if should_update_summary:
        with contextlib.suppress(Exception):
            await auto_update_summary_background(
                tenant_id=options.tenant_id,
                conversation_id=options.conversation_id,
            )
