
import contextlib
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Awaitable, Callable, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.token_utils import num_tokens_from_string
from app.services.chat_runtime import (
    ChatStreamPersistInput,
    apply_chat_runtime_metrics_context,
)
from app.services.chat_stream_persistence import dispatch_chat_stream_persistence
from app.services.metrics_logger import log_metrics


@dataclass(frozen=True)
class MaterializedChatStreamInput:
    start_message: str
    content: str
    citations: list[dict[str, Any]] | list | None
    metrics: dict[str, Any]


@dataclass(frozen=True)
class ChatStreamRuntimeContext:
    request_id: str
    disconnect_check: Callable[[], Awaitable[bool]] | None
    dataset_id_used: UUID | None
    dataset_rag_defaults_applied_fields: list[str] | None = None
    dataset_rag_config_template_defaults_applied_fields: list[str] | None = None
    rag_config_template_meta: dict[str, Any] | None = None
    dataset_prompt_defaults_applied_fields: list[str] | None = None
    tenant_qps_meta: dict[str, Any] | None = None
    quota_meta: dict[str, Any] | None = None
    retrieval_mode_default: str | None = None
    vector_backend_default: str | None = None
    request_structured_output: bool = False
    structured_data: object | None = None
    structured_preset: str | None = None


@dataclass(frozen=True)
class ChatStreamPersistenceContext:
    db: Session
    persist_in_background: bool
    spawn_background_task: Callable[[Any], None]
    persist_options: ChatStreamPersistInput


def build_chat_stream_done_event(
    *,
    request_id: str,
    assistant_message_id: UUID,
    conversation_id: UUID | None,
    content: str,
    citations: list[dict[str, Any]] | list | None,
    metrics: dict[str, Any],
    retrieval_mode_default: str | None,
    vector_backend_default: str | None,
    structured: bool,
    structured_data: object | None,
    structured_preset: str | None = None,
) -> dict[str, Any]:
    retrieval_mode_used = metrics.get("retrieval_mode") or retrieval_mode_default
    vector_backend_used = metrics.get("vector_backend") or vector_backend_default
    return {
        "type": "done",
        "data": {
            "assistant_message_id": str(assistant_message_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "total_tokens": num_tokens_from_string(content or ""),
            "total_chars": len(content or ""),
            "citations_count": len(citations if isinstance(citations, list) else []),
            "model_used": metrics.get("model_used"),
            "route": metrics.get("route"),
            "retrieval_mode": retrieval_mode_used,
            "vector_backend": vector_backend_used,
            "confidence_score": metrics.get("confidence_score"),
            "followup_questions": metrics.get("followup_questions") or [],
            "metrics": metrics,
            "structured": structured,
            "structured_data": structured_data,
            "structured_preset": structured_preset,
        },
        "request_id": str(request_id),
    }


def log_chat_stream_completion_metrics(
    *,
    request_id: str,
    conversation_id: UUID | None,
    tenant_id: UUID | None,
    metrics: dict[str, Any],
    retrieval_mode_default: str | None,
    vector_backend_default: str | None,
) -> None:
    retrieval_mode_used = metrics.get("retrieval_mode") or retrieval_mode_default
    vector_backend_used = metrics.get("vector_backend") or vector_backend_default
    log_metrics(
        {
            "event": "rag_done",
            "conversation_id": str(conversation_id) if conversation_id else None,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "vector_backend": vector_backend_used,
            "retrieval_mode": retrieval_mode_used,
            "route": metrics.get("route"),
            "model_used": metrics.get("model_used"),
            "metrics": metrics,
            "request_id": str(request_id),
        }
    )


async def stream_materialized_chat_events(
    *,
    stream_input: MaterializedChatStreamInput,
    runtime: ChatStreamRuntimeContext,
    persistence: ChatStreamPersistenceContext,
) -> AsyncIterator[dict[str, Any]]:
    disconnect_check = runtime.disconnect_check
    if disconnect_check is not None:
        with contextlib.suppress(Exception):
            if await disconnect_check():
                return

    citations_list = stream_input.citations if isinstance(stream_input.citations, list) else []
    yield {"request_id": str(runtime.request_id), "type": "event", "data": {"message": stream_input.start_message}}
    yield {"request_id": str(runtime.request_id), "type": "citations", "data": citations_list}

    answer_text = stream_input.content or ""
    chunk_size = 120
    for i in range(0, len(answer_text), chunk_size):
        if disconnect_check is not None and i % (chunk_size * 50) == 0:
            with contextlib.suppress(Exception):
                if await disconnect_check():
                    return
        token_chunk = answer_text[i : i + chunk_size]
        yield {
            "request_id": str(runtime.request_id),
            "type": "token",
            "data": {"content": token_chunk},
        }

    final_metrics = apply_chat_runtime_metrics_context(
        stream_input.metrics,
        dataset_id_used=runtime.dataset_id_used,
        dataset_rag_defaults_applied_fields=runtime.dataset_rag_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=runtime.dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=runtime.rag_config_template_meta,
        dataset_prompt_defaults_applied_fields=runtime.dataset_prompt_defaults_applied_fields,
        tenant_qps_meta=runtime.tenant_qps_meta,
        quota_meta=runtime.quota_meta,
    )

    yield build_chat_stream_done_event(
        request_id=str(runtime.request_id),
        assistant_message_id=persistence.persist_options.assistant_message_id,
        conversation_id=persistence.persist_options.conversation_id,
        content=answer_text,
        citations=citations_list,
        metrics=final_metrics,
        retrieval_mode_default=runtime.retrieval_mode_default,
        vector_backend_default=runtime.vector_backend_default,
        structured=bool(runtime.structured_data is not None) if runtime.request_structured_output else False,
        structured_data=runtime.structured_data,
        structured_preset=runtime.structured_preset,
    )

    log_chat_stream_completion_metrics(
        request_id=str(runtime.request_id),
        conversation_id=persistence.persist_options.conversation_id,
        tenant_id=persistence.persist_options.tenant_id,
        metrics=final_metrics,
        retrieval_mode_default=runtime.retrieval_mode_default,
        vector_backend_default=runtime.vector_backend_default,
    )

    dispatch_chat_stream_persistence(
        db=persistence.db,
        persist_in_background=persistence.persist_in_background,
        spawn_background_task=persistence.spawn_background_task,
        options=cast(
            ChatStreamPersistInput,
            replace(
                persistence.persist_options,
                content=answer_text,
                citations=citations_list,
                metrics=final_metrics,
                structured_data=runtime.structured_data,
            ),
        ),
    )


async def stream_cached_chat_events(
    *,
    stream_input: MaterializedChatStreamInput,
    runtime: ChatStreamRuntimeContext,
    persistence: ChatStreamPersistenceContext,
) -> AsyncIterator[dict[str, Any]]:
    async for event in stream_materialized_chat_events(
        stream_input=cast(
            MaterializedChatStreamInput,
            replace(stream_input, start_message="缓存命中，直接返回…"),
        ),
        runtime=runtime,
        persistence=persistence,
    ):
        yield event
