import asyncio
import contextlib
import logging
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Awaitable, Callable

from app.infrastructure.runtime.stream_events import StreamEmitter, bind_stream_emitter, reset_stream_emitter
from app.services.chat.cache_flow import annotate_chat_cache_metrics, store_chat_response_cache_if_needed
from app.services.chat.execution import ChatExecutionContext
from app.services.chat.response_formatting import apply_chat_runtime_metrics_context
from app.services.chat.stream_persistence import ChatStreamPersistInput, dispatch_chat_stream_persistence
from app.services.retrieval.defaults import retrieval_options

logger = logging.getLogger("app.services.chat_stream_langchain")


@dataclass
class _StreamSessionState:
    citations_data: list[Any]
    response_parts: list[str]
    metrics_data: dict[str, Any] | None
    structured_data: object | None
    completed: bool = False


def _annotate_cache_metrics(options: "LangChainChatStreamSessionInput", metrics_data: Any) -> dict[str, Any]:
    if isinstance(metrics_data, dict):
        base_metrics = metrics_data
    else:
        base_metrics = {}
    return annotate_chat_cache_metrics(
        base_metrics,
        enabled=options.cache_feature_enabled,
        hit=options.cache_hit,
        skip_reason=None if options.cache_hit else options.cache_skip_reason,
    )


def _apply_metrics_context(
    options: "LangChainChatStreamSessionInput",
    *,
    dataset_id_used: Any,
    rag_config_template_meta: dict[str, Any] | None,
    metrics_data: dict[str, Any],
) -> dict[str, Any]:
    return apply_chat_runtime_metrics_context(
        metrics_data,
        dataset_id_used=dataset_id_used,
        dataset_rag_defaults_applied_fields=options.dataset_rag_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=options.dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=rag_config_template_meta,
        dataset_prompt_defaults_applied_fields=options.dataset_prompt_defaults_applied_fields,
        tenant_qps_meta=options.tenant_qps_meta,
        quota_meta=options.quota_meta,
    )


async def _next_stream_event(
    queue: "asyncio.Queue[dict | None]",
    *,
    heartbeat_sec: float,
) -> dict | None:
    if heartbeat_sec > 0:
        return await asyncio.wait_for(queue.get(), timeout=heartbeat_sec)
    return await queue.get()


async def _disconnect_requested(options: "LangChainChatStreamSessionInput") -> bool:
    if options.disconnect_check is None:
        return False
    try:
        return await options.disconnect_check()
    except Exception as exc:
        logger.debug("Ignoring chat stream disconnect check failure: %s", exc)
        return False


def _handle_stream_event(
    event: dict,
    *,
    options: "LangChainChatStreamSessionInput",
    dataset_id_used: Any,
    rag_config_template_meta: dict[str, Any] | None,
    request_id: Any,
    state: _StreamSessionState,
) -> dict:
    event_type = event.get("type")
    if event_type == "citations":
        state.citations_data = event.get("data") or []
    elif event_type == "error":
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        message = str(data.get("message") or data.get("error") or "Chat stream error")
        raise RuntimeError(message)
    elif event_type == "done":
        if isinstance(event.get("data"), dict):
            event["data"]["assistant_message_id"] = str(options.persist_options.assistant_message_id)
            state.metrics_data = event["data"].get("metrics", {})
            state.structured_data = event["data"].get("structured_data")
        else:
            state.metrics_data = {}
        state.metrics_data = _annotate_cache_metrics(options, state.metrics_data)
        state.metrics_data = _apply_metrics_context(
            options,
            dataset_id_used=dataset_id_used,
            rag_config_template_meta=rag_config_template_meta,
            metrics_data=state.metrics_data,
        )
        if isinstance(event.get("data"), dict):
            event["data"]["metrics"] = dict(state.metrics_data)
            state.completed = True
    elif event_type == "token":
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        state.response_parts.append(data["content"])
    event["request_id"] = str(request_id)
    return event


def _finalize_stream_session(
    *,
    db: Any,
    options: "LangChainChatStreamSessionInput",
    dataset_id_used: Any,
    rag_config_template_meta: dict[str, Any] | None,
    state: _StreamSessionState,
) -> None:
    full_response = "".join(state.response_parts)
    metrics_data = _annotate_cache_metrics(options, state.metrics_data)

    store_chat_response_cache_if_needed(
        cache_eligible=options.cache_eligible,
        cache_hit=options.cache_hit,
        cache_key=options.cache_key,
        content=full_response,
        citations=state.citations_data,
        metrics=metrics_data,
        structured_data=state.structured_data,
    )

    metrics_data = _apply_metrics_context(
        options,
        dataset_id_used=dataset_id_used,
        rag_config_template_meta=rag_config_template_meta,
        metrics_data=metrics_data,
    )

    dispatch_chat_stream_persistence(
        db=db,
        persist_in_background=options.persist_in_background,
        spawn_background_task=options.spawn_background_task,
        options=replace(
            options.persist_options,
            content=full_response,
            citations=state.citations_data,
            metrics=metrics_data,
            structured_data=state.structured_data,
        ),
    )


@dataclass(frozen=True)
class LangChainChatStreamSessionInput:
    execution: ChatExecutionContext
    cache_feature_enabled: bool
    cache_hit: bool
    cache_skip_reason: str | None
    cache_eligible: bool
    cache_key: str | None
    dataset_rag_defaults_applied_fields: list[str] | None
    dataset_rag_config_template_defaults_applied_fields: list[str] | None
    dataset_prompt_defaults_applied_fields: list[str] | None
    tenant_qps_meta: dict[str, Any] | None
    quota_meta: dict[str, Any] | None
    heartbeat_sec: float
    disconnect_check: Callable[[], Awaitable[bool]] | None
    persist_in_background: bool
    spawn_background_task: Callable[[Any], None]
    persist_options: ChatStreamPersistInput


async def stream_langchain_chat_session_events(
    *,
    engine: Any,
    options: LangChainChatStreamSessionInput,
) -> AsyncIterator[dict[str, Any]]:
    context = options.execution
    db = context.db
    request_id = context.request_id
    dataset_id_used = context.dataset_id_used
    rag_config_template_meta = context.rag_config_template_meta

    q: asyncio.Queue[dict | None] = asyncio.Queue()
    producer_task = asyncio.create_task(
        produce_langchain_stream_events(
            engine=engine,
            queue=q,
            context=context,
        )
    )
    disconnected = False
    state = _StreamSessionState(citations_data=[], response_parts=[], metrics_data={}, structured_data=None)

    try:
        while True:
            if await _disconnect_requested(options):
                disconnected = True
                producer_task.cancel()
                break

            try:
                ev = await _next_stream_event(q, heartbeat_sec=options.heartbeat_sec)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "data": {}}
                continue

            if ev is None:
                break

            event = _handle_stream_event(
                ev,
                options=options,
                dataset_id_used=dataset_id_used,
                rag_config_template_meta=rag_config_template_meta,
                request_id=request_id,
                state=state,
            )
            yield event
    finally:
        if not producer_task.done():
            producer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer_task

    if disconnected:
        return
    if not state.completed:
        raise RuntimeError("Chat stream ended before completion")

    _finalize_stream_session(
        db=db,
        options=options,
        dataset_id_used=dataset_id_used,
        rag_config_template_meta=rag_config_template_meta,
        state=state,
    )


async def produce_langchain_stream_events(
    *,
    engine: Any,
    queue: "asyncio.Queue[dict | None]",
    context: ChatExecutionContext,
) -> None:
    db = context.db
    tenant_id = context.tenant_id
    account_id = context.account_id
    request = context.request
    conversation_id = context.conversation_id
    request_id = context.request_id
    doc_ids_to_use = context.doc_ids_to_use
    history_for_llm = context.history_for_llm
    scope_dataset_id = context.scope_dataset_id
    dataset_id_used = context.dataset_id_used
    effective_rag_config = context.effective_rag_config
    effective_prompt_template_id = context.effective_prompt_template_id
    effective_prompt_template_key = context.effective_prompt_template_key
    effective_prompt_ab_experiment_key = context.effective_prompt_ab_experiment_key
    rag_config_template_meta = context.rag_config_template_meta

    stream_emitter_token = bind_stream_emitter(StreamEmitter(queue=queue, loop=asyncio.get_running_loop()))
    try:
        async for ev in engine.stream_chat(
            question=request.message,
            history=history_for_llm,
            conversation_id=conversation_id,
            document_ids=doc_ids_to_use,
            metadata_filter=effective_rag_config.metadata_filter,
            **retrieval_options(effective_rag_config),
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id_used or scope_dataset_id,
            structured_output=request.structured_output,
            retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
            must_recall=effective_rag_config.must_recall,
            must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
            must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
            max_tokens=effective_rag_config.max_tokens,
            structured_preset=request.structured_preset,
            prompt_template_id=effective_prompt_template_id,
            prompt_template_key=effective_prompt_template_key,
            prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
            rag_config_template=rag_config_template_meta,
            ab_user_key=account_id,
            db=db,
            request_id=str(request_id),
        ):
            await queue.put(ev)
    finally:
        reset_stream_emitter(stream_emitter_token)
        await queue.put(None)
