
import json
from dataclasses import replace
from typing import Any, AsyncIterator, Callable, cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.env import is_production_env
from app.rag.core.logging import get_logger
from app.services.chat_execution_runtime import (
    ChatExecutionContext,
    execute_extractive_fallback_once,
    is_model_provider_unavailable_circuit_open,
    is_model_provider_unavailable_error,
    mark_model_provider_unavailable,
    preflight_model_provider_fast,
)
from app.services.chat_runtime import (
    ChatStreamPersistInput,
    format_stream_error_message,
    prepare_stream_chat_runtime,
)
from app.services.chat_stream_common import (
    ChatStreamPersistenceContext,
    ChatStreamRuntimeContext,
    MaterializedChatStreamInput,
    stream_cached_chat_events,
    stream_materialized_chat_events,
)
from app.services.chat_stream_graph import GraphChatStreamSessionInput, stream_graph_chat_session_events
from app.services.chat_stream_langchain import LangChainChatStreamSessionInput, stream_langchain_chat_session_events
from app.services.metrics_logger import set_metrics_context
from app.services.rag_runtime_limiter import run_blocking_retrieval_call_with_managed_session

logger = get_logger("services.chat_stream_orchestrator")


async def stream_chat_sse_events(
    *,
    http_request: Any,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
    scope_dataset_id: UUID | None,
    allowed_doc_ids: list[UUID],
    long_term_messages: list[dict[str, Any]],
    assistant_message_id: UUID,
    tenant_qps_meta: dict[str, Any] | None,
    quota_meta: dict[str, Any] | None,
    spawn_background_task: Callable[[Any], None],
) -> AsyncIterator[str]:
    doc_ids_to_use = allowed_doc_ids or []
    request_id = getattr(http_request.state, "request_id", None) or uuid4().hex
    metrics_data: dict[str, Any] = {}
    structured_data: object | None = None

    set_metrics_context(
        request_id=str(request_id),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        account_id=account_id,
    )

    persist_in_background = bool(getattr(settings, "CHAT_STREAM_PERSIST_IN_BACKGROUND", False))
    client_ip = getattr(getattr(http_request, "client", None), "host", None)
    user_agent = http_request.headers.get("user-agent")
    enable_summary_memory = bool(getattr(request, "enable_summary_memory", False))
    enable_structured_memory = bool(getattr(request, "enable_structured_memory", False))

    yield ": keepalive\n\n"
    yield (
        f"data: {json.dumps({'request_id': str(request_id), 'type': 'event', 'data': {'message': '开始处理…'}}, ensure_ascii=False)}\n\n"
    )

    stream_runtime = prepare_stream_chat_runtime(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        conversation_id=conversation_id,
        scope_dataset_id=scope_dataset_id,
        document_ids=doc_ids_to_use,
        long_term_messages=long_term_messages,
        request_id=str(request_id),
    )
    effective_rag_config = stream_runtime.effective_rag_config
    dataset_id_used = stream_runtime.dataset_id_used
    dataset_rag_defaults_applied_fields = stream_runtime.dataset_rag_defaults_applied_fields
    effective_prompt_template_id = stream_runtime.effective_prompt_template_id
    effective_prompt_template_key = stream_runtime.effective_prompt_template_key
    effective_prompt_ab_experiment_key = stream_runtime.effective_prompt_ab_experiment_key
    dataset_prompt_defaults_applied_fields = stream_runtime.dataset_prompt_defaults_applied_fields
    dataset_rag_config_template_defaults_applied_fields = (
        stream_runtime.dataset_rag_config_template_defaults_applied_fields
    )
    rag_config_template_meta = stream_runtime.rag_config_template_meta
    history_for_llm = stream_runtime.history_for_llm
    cache_feature_enabled = stream_runtime.cache_feature_enabled
    cache_key = stream_runtime.cache_key
    cache_skip_reason = stream_runtime.cache_skip_reason
    cache_eligible = stream_runtime.cache_eligible
    cache_hit = stream_runtime.cache_hit
    full_response = stream_runtime.full_response
    citations_data = stream_runtime.citations_data
    metrics_data = stream_runtime.metrics_data
    structured_data = stream_runtime.structured_data

    cancel_on_disconnect = bool(getattr(settings, "CHAT_STREAM_CANCEL_ON_DISCONNECT", True))
    disconnect_check = http_request.is_disconnected if cancel_on_disconnect else None
    materialized_runtime = ChatStreamRuntimeContext(
        request_id=str(request_id),
        disconnect_check=disconnect_check,
        dataset_id_used=dataset_id_used,
        dataset_rag_defaults_applied_fields=dataset_rag_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=rag_config_template_meta,
        dataset_prompt_defaults_applied_fields=dataset_prompt_defaults_applied_fields,
        tenant_qps_meta=tenant_qps_meta,
        quota_meta=quota_meta,
        retrieval_mode_default=effective_rag_config.retrieval_mode,
        vector_backend_default=settings.VECTOR_BACKEND,
        request_structured_output=bool(request.structured_output),
        structured_data=structured_data,
        structured_preset=request.structured_preset,
    )
    execution_context = ChatExecutionContext(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        conversation_id=conversation_id,
        request_id=str(request_id),
        doc_ids_to_use=doc_ids_to_use,
        history_for_llm=history_for_llm,
        scope_dataset_id=scope_dataset_id,
        dataset_id_used=dataset_id_used,
        effective_rag_config=effective_rag_config,
        effective_prompt_template_id=effective_prompt_template_id,
        effective_prompt_template_key=effective_prompt_template_key,
        effective_prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        rag_config_template_meta=rag_config_template_meta,
    )

    if cache_hit:
        async for cached_event in stream_cached_chat_events(
            stream_input=MaterializedChatStreamInput(
                start_message="缓存命中，直接返回…",
                content=full_response,
                citations=citations_data,
                metrics=metrics_data,
            ),
            runtime=materialized_runtime,
            persistence=ChatStreamPersistenceContext(
                db=db,
                persist_in_background=persist_in_background,
                spawn_background_task=spawn_background_task,
                persist_options=ChatStreamPersistInput(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    account_id=account_id,
                    assistant_message_id=assistant_message_id,
                    request_id=str(request_id),
                    question=request.message,
                    document_count=len(doc_ids_to_use),
                    content=full_response,
                    citations=citations_data,
                    metrics=metrics_data,
                    dataset_id_used=dataset_id_used,
                    cache_hit=True,
                    cache_key=cache_key,
                    cache_eligible=False,
                    structured_data=structured_data,
                    ip=client_ip,
                    user_agent=user_agent,
                    enable_summary_memory=enable_summary_memory,
                    enable_structured_memory=enable_structured_memory,
                ),
            ),
        ):
            yield f"data: {json.dumps(cached_event, ensure_ascii=False)}\n\n"
        return

    async def _stream_extractive_fallback(
        *,
        reason: str,
        original_error: BaseException | None = None,
        provider_error: str | None = None,
    ) -> AsyncIterator[str]:
        chat_result = await run_blocking_retrieval_call_with_managed_session(
            lambda worker_db: execute_extractive_fallback_once(
                db=worker_db,
                tenant_id=tenant_id,
                account_id=account_id,
                request=request,
                doc_ids_to_use=doc_ids_to_use,
                history_for_llm=history_for_llm,
                scope_dataset_id=scope_dataset_id,
                dataset_id_used=dataset_id_used,
                effective_rag_config=effective_rag_config,
                original_error=original_error,
                reason=reason,
            ),
            request_db=db,
        )
        fallback_metrics = dict(chat_result.metrics or {})
        if provider_error:
            fallback_metrics["generation_fallback_error"] = provider_error
        fallback_metrics.setdefault("generation_fallback_used", True)
        async for fallback_event in stream_materialized_chat_events(
            stream_input=MaterializedChatStreamInput(
                start_message="模型服务不可用，已切换为引用抽取摘要…",
                content=chat_result.content,
                citations=chat_result.citations,
                metrics=fallback_metrics,
            ),
            runtime=cast(
                ChatStreamRuntimeContext,
                replace(materialized_runtime, structured_data=chat_result.structured_data),
            ),
            persistence=ChatStreamPersistenceContext(
                db=db,
                persist_in_background=persist_in_background,
                spawn_background_task=spawn_background_task,
                persist_options=ChatStreamPersistInput(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    account_id=account_id,
                    assistant_message_id=assistant_message_id,
                    request_id=str(request_id),
                    question=request.message,
                    document_count=len(doc_ids_to_use),
                    content=chat_result.content,
                    citations=chat_result.citations,
                    metrics=fallback_metrics,
                    dataset_id_used=dataset_id_used,
                    cache_hit=False,
                    cache_key=None,
                    cache_eligible=False,
                    structured_data=chat_result.structured_data,
                    ip=client_ip,
                    user_agent=user_agent,
                    enable_summary_memory=enable_summary_memory,
                    enable_structured_memory=enable_structured_memory,
                ),
            ),
        ):
            yield f"data: {json.dumps(fallback_event, ensure_ascii=False)}\n\n"

    answer_mode = str(getattr(effective_rag_config, "answer_mode", "llm") or "llm")
    if answer_mode == "extractive":
        async for fallback_chunk in _stream_extractive_fallback(reason="explicit_extractive_answer_mode"):
            yield fallback_chunk
        return

    if is_model_provider_unavailable_circuit_open():
        async for fallback_chunk in _stream_extractive_fallback(reason="model_provider_circuit_open"):
            yield fallback_chunk
        return

    provider_available, provider_error = await preflight_model_provider_fast()
    if not provider_available:
        async for fallback_chunk in _stream_extractive_fallback(
            reason="model_provider_preflight_failed",
            provider_error=provider_error,
        ):
            yield fallback_chunk
        return

    if effective_rag_config.use_graph:
        try:
            async for graph_event in stream_graph_chat_session_events(
                options=GraphChatStreamSessionInput(
                    execution=execution_context,
                    cache_feature_enabled=cache_feature_enabled,
                    cache_hit=cache_hit,
                    cache_skip_reason=cache_skip_reason,
                    cache_eligible=cache_eligible,
                    cache_key=cache_key,
                    dataset_rag_defaults_applied_fields=dataset_rag_defaults_applied_fields,
                    dataset_rag_config_template_defaults_applied_fields=dataset_rag_config_template_defaults_applied_fields,
                    dataset_prompt_defaults_applied_fields=dataset_prompt_defaults_applied_fields,
                    tenant_qps_meta=tenant_qps_meta,
                    quota_meta=quota_meta,
                    persist_in_background=persist_in_background,
                    spawn_background_task=spawn_background_task,
                    persist_options=ChatStreamPersistInput(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        account_id=account_id,
                        assistant_message_id=assistant_message_id,
                        request_id=str(request_id),
                        question=request.message,
                        document_count=len(doc_ids_to_use),
                        content="",
                        citations=[],
                        metrics={},
                        dataset_id_used=dataset_id_used,
                        cache_hit=cache_hit,
                        cache_key=cache_key,
                        cache_eligible=False,
                        structured_data=None,
                        ip=client_ip,
                        user_agent=user_agent,
                        enable_summary_memory=enable_summary_memory,
                        enable_structured_memory=enable_structured_memory,
                    ),
                ),
            ):
                yield f"data: {json.dumps(graph_event, ensure_ascii=False)}\n\n"
            return
        except Exception as exc:  # noqa: BLE001
            if is_model_provider_unavailable_error(exc):
                mark_model_provider_unavailable()
                async for fallback_chunk in _stream_extractive_fallback(
                    reason="model_provider_stream_error",
                    original_error=exc,
                ):
                    yield fallback_chunk
                return
            logger.exception("LangGraph stream error: %s", str(exc)[:200])
            error_event = {
                "type": "error",
                "data": {
                    "message": "An error occurred during chat processing",
                    "conversation_id": str(conversation_id) if conversation_id else None,
                },
                "request_id": str(request_id),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

    try:
        from app.rag.engine import get_rag_engine

        engine = get_rag_engine()
        heartbeat_sec = max(
            0.0,
            float(getattr(settings, "CHAT_STREAM_HEARTBEAT_SEC", 10.0) or 10.0),
        )
        cancel_on_disconnect = bool(getattr(settings, "CHAT_STREAM_CANCEL_ON_DISCONNECT", True))
        disconnect_check = http_request.is_disconnected if cancel_on_disconnect else None

        async for stream_chunk in stream_langchain_chat_session_events(
            engine=engine,
            options=LangChainChatStreamSessionInput(
                execution=execution_context,
                cache_feature_enabled=cache_feature_enabled,
                cache_hit=cache_hit,
                cache_skip_reason=cache_skip_reason,
                cache_eligible=cache_eligible,
                cache_key=cache_key,
                dataset_rag_defaults_applied_fields=dataset_rag_defaults_applied_fields,
                dataset_rag_config_template_defaults_applied_fields=dataset_rag_config_template_defaults_applied_fields,
                dataset_prompt_defaults_applied_fields=dataset_prompt_defaults_applied_fields,
                tenant_qps_meta=tenant_qps_meta,
                quota_meta=quota_meta,
                heartbeat_sec=heartbeat_sec,
                disconnect_check=disconnect_check,
                persist_in_background=persist_in_background,
                spawn_background_task=spawn_background_task,
                persist_options=ChatStreamPersistInput(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    account_id=account_id,
                    assistant_message_id=assistant_message_id,
                    request_id=str(request_id),
                    question=request.message,
                    document_count=len(doc_ids_to_use),
                    content="",
                    citations=[],
                    metrics={},
                    dataset_id_used=dataset_id_used,
                    cache_hit=cache_hit,
                    cache_key=cache_key,
                    cache_eligible=False,
                    structured_data=None,
                    ip=client_ip,
                    user_agent=user_agent,
                    enable_summary_memory=enable_summary_memory,
                    enable_structured_memory=enable_structured_memory,
                ),
            ),
        ):
            yield stream_chunk
    except Exception as exc:  # noqa: BLE001
        if is_model_provider_unavailable_error(exc):
            mark_model_provider_unavailable()
            async for fallback_chunk in _stream_extractive_fallback(
                reason="model_provider_stream_error",
                original_error=exc,
            ):
                yield fallback_chunk
            return
        logger.exception("Chat stream error: %s", str(exc)[:200])
        detail = format_stream_error_message(exc)
        message = "An error occurred during chat processing"
        if not is_production_env() and detail:
            message = f"{message}: {detail[:200]}"
        error_event = {
            "type": "error",
            "data": {
                "message": message,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "error_id": str(request_id),
            },
            "request_id": str(request_id),
        }
        yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
