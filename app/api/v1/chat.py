"""
Chat API.
"""

import asyncio
import uuid
from dataclasses import replace
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import (
    ChatRequest,
    ChatResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.v1 import chat_conversation_memory, chat_conversations
from app.core.config import settings
from app.core.database import get_db
from app.core.token_utils import num_tokens_from_string
from app.rag.core.logging import get_logger
from app.services.chat_bootstrap_runtime import (
    PreparedChatTurnSession,
    prepare_chat_request_runtime,
    prepare_chat_turn_session,
)
from app.services.chat_cache_runtime import (
    ChatCacheLookupInput,
    annotate_chat_cache_metrics,
    annotate_chat_singleflight_metrics,
    prepare_non_streaming_chat_cache_state,
)
from app.services.chat_execution_runtime import (
    ChatExecutionContext,
    ExecutedGraphChatOnceResult,
    execute_extractive_fallback_once,
    execute_graph_chat_once,
    execute_langchain_chat_once,
    is_model_provider_unavailable_circuit_open,
    is_model_provider_unavailable_error,
    mark_model_provider_unavailable,
    preflight_model_provider_fast,
)
from app.services.chat_persistence import ChatResponseFinalizationInput, finalize_chat_response
from app.services.chat_response_cache import (
    InflightResponseLeaderCancelledError,
    reject_inflight_chat_response,
)
from app.services.chat_runtime import (
    apply_chat_runtime_metrics_context,
    format_stream_error_message,
)
from app.services.chat_stream_orchestrator import stream_chat_sse_events
from app.services.chat_turn_persistence import auto_update_summary_background
from app.services.metrics_logger import set_metrics_context
from app.services.quota_service import ChatAssistantTokenQuota, check_chat_assistant_token_quota
from app.services.rag_runtime_limiter import (
    RetrievalAdmissionTimeoutError,
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call_with_managed_session,
)
from app.services.tenant_quota_service import TenantQpsQuotaResult, enforce_tenant_qps_quota_async

logger = get_logger("api.chat")

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


async def _run_extractive_chat_fallback(
    *,
    context: ChatExecutionContext,
    reason: str,
    runtime_metrics: dict[str, Any],
    original_error: Exception | None = None,
) -> ExecutedGraphChatOnceResult:
    return await run_blocking_retrieval_call_with_managed_session(
        lambda worker_db: execute_extractive_fallback_once(
            db=worker_db,
            tenant_id=context.tenant_id,
            account_id=context.account_id,
            request=context.request,
            doc_ids_to_use=context.doc_ids_to_use,
            history_for_llm=context.history_for_llm,
            scope_dataset_id=context.scope_dataset_id,
            dataset_id_used=context.dataset_id_used,
            effective_rag_config=context.effective_rag_config,
            reason=reason,
            original_error=original_error,
        ),
        request_db=context.db,
        runtime_metrics=runtime_metrics,
    )


async def _run_non_streaming_chat_generation(
    *,
    context: ChatExecutionContext,
    runtime_metrics: dict[str, Any],
) -> ExecutedGraphChatOnceResult:
    if context.effective_rag_config.answer_mode == "extractive":
        return await _run_extractive_chat_fallback(
            context=context,
            reason="explicit_extractive_answer_mode",
            runtime_metrics=runtime_metrics,
        )
    if is_model_provider_unavailable_circuit_open():
        return await _run_extractive_chat_fallback(
            context=context,
            reason="model_provider_circuit_open",
            runtime_metrics=runtime_metrics,
        )

    provider_available, provider_error = await preflight_model_provider_fast()
    if not provider_available:
        chat_result = await _run_extractive_chat_fallback(
            context=context,
            reason="model_provider_preflight_failed",
            runtime_metrics=runtime_metrics,
        )
        if provider_error:
            chat_result = replace(
                chat_result, metrics={**chat_result.metrics, "generation_fallback_error": provider_error}
            )
        return chat_result

    try:
        if context.effective_rag_config.use_graph:
            return await run_blocking_call_with_managed_session(
                lambda worker_db: execute_graph_chat_once(context=replace(context, db=worker_db)),
                request_db=context.db,
            )
        from app.rag.engine import get_rag_engine

        return await execute_langchain_chat_once(engine=get_rag_engine(), context=context)
    except Exception as exc:
        if not is_model_provider_unavailable_error(exc):
            raise
        mark_model_provider_unavailable()
        return await _run_extractive_chat_fallback(
            context=context,
            reason="model_provider_runtime_unavailable",
            runtime_metrics=runtime_metrics,
            original_error=exc,
        )


async def _prepare_chat_turn(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: ChatRequest,
) -> tuple[PreparedChatTurnSession, TenantQpsQuotaResult, ChatAssistantTokenQuota]:
    allow_empty_docs = settings.CHAT_ALLOW_EMPTY_DOCUMENTS
    allow_open_scope = settings.CHAT_ALLOW_OPEN_SCOPE
    tenant_qps_meta = await enforce_tenant_qps_quota_async(tenant_id=tenant_id, key="chat")
    quota_meta = await run_blocking_call_with_managed_session(
        lambda worker_db: check_chat_assistant_token_quota(worker_db, tenant_id=tenant_id), request_db=db
    )
    if quota_meta["enabled"] and quota_meta["exceeded"] and quota_meta["mode"] == "block":
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Chat quota exceeded (assistant tokens)",
                "retry_after_sec": None,
                "limit": quota_meta["limit"],
                "scope": "chat_tokens",
            },
        )
    turn_session = await run_blocking_call_with_managed_session(
        lambda worker_db: prepare_chat_turn_session(
            db=worker_db,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            allow_empty_docs=allow_empty_docs,
            allow_open_scope=allow_open_scope,
            conversation_not_found_detail=CONVERSATION_NOT_FOUND_DETAIL,
            dataset_required_detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
            document_scope_mismatch_detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL,
            empty_scope_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
        ),
        request_db=db,
    )
    return turn_session, tenant_qps_meta, quota_meta


def _reject_singleflight_leader_if_needed(
    *,
    singleflight_key: str | None,
    singleflight_leader: bool,
    error: Exception,
) -> None:
    if singleflight_key and singleflight_leader:
        reject_inflight_chat_response(singleflight_key, error)


def _singleflight_role(
    *,
    singleflight_hit: bool,
    singleflight_leader: bool,
) -> str | None:
    if singleflight_hit:
        return "follower"
    if singleflight_leader:
        return "leader"
    return None


def _schedule_summary_update(
    *,
    background_tasks: BackgroundTasks,
    request: ChatRequest,
    tenant_id: UUID,
    conversation_id: UUID,
) -> None:
    if not (
        settings.PERSISTENT_SUMMARY_MEMORY_ENABLED
        and settings.PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE
        and request.enable_summary_memory
    ):
        return
    try:
        background_tasks.add_task(auto_update_summary_background, tenant_id=tenant_id, conversation_id=conversation_id)
    except Exception as exc:
        logger.warning(
            "Conversation summary scheduling failed: tenant_id=%s conversation_id=%s error_type=%s",
            tenant_id,
            conversation_id,
            type(exc).__name__,
            exc_info=True,
        )


def _spawn_background_task(coro: Any) -> None:
    """
    Best-effort fire-and-forget task runner.

    Keep a strong reference to background tasks until completion.
    """
    try:
        task = asyncio.create_task(coro)
    except Exception as exc:
        logger.warning("Background task scheduling failed: error_type=%s", type(exc).__name__, exc_info=True)
        coro.close()
        return

    _BACKGROUND_TASKS.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _BACKGROUND_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("Background task failed: error_type=%s", type(exc).__name__)

    task.add_done_callback(_done)


_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    **DEFAULT_HTTP_EXCEPTION_RESPONSES,
    503: {"description": "Service Unavailable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
router.include_router(chat_conversation_memory.router)
router.include_router(chat_conversations.router)

CONVERSATION_NOT_FOUND_DETAIL = "Conversation not found"
DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL = "dataset_id is required when document_ids is empty"
DOC_IDS_MUST_MATCH_DATASET_DETAIL = "document_ids must all belong to the specified dataset_id"
NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL = "No accessible documents for chat retrieval"


@router.post("", response_model=ChatResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def chat(
    http_request: Request,
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Non-streaming chat endpoint.

    It mirrors the `/chat/stream` behavior, but returns a single JSON payload
    after the answer is ready.
    """
    turn_session, tenant_qps_meta, quota_meta = await _prepare_chat_turn(
        db=db, tenant_id=tenant_id, account_id=account_id, request=request
    )
    conversation_id = turn_session.conversation_id
    document_ids = turn_session.allowed_doc_ids
    request_id = http_request.state.request_id
    assistant_message_id = uuid.uuid4()
    set_metrics_context(
        request_id=request_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        account_id=account_id,
    )

    request_runtime = await run_blocking_call_with_managed_session(
        lambda worker_db: prepare_chat_request_runtime(
            db=worker_db,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            conversation_id=conversation_id,
            scope_dataset_id=turn_session.scope_dataset_id,
            document_ids=document_ids,
            long_term_messages=turn_session.long_term_messages,
            request_id=request_id,
        ),
        request_db=db,
    )
    effective_rag_config = request_runtime.effective_rag_config
    offload_metrics: dict[str, Any] = {}
    prompt_cfg = {
        "prompt_template_id": str(request_runtime.effective_prompt_template_id)
        if request_runtime.effective_prompt_template_id
        else None,
        "prompt_template_key": request_runtime.effective_prompt_template_key,
        "prompt_ab_experiment_key": request_runtime.effective_prompt_ab_experiment_key,
    }
    cache_state = await prepare_non_streaming_chat_cache_state(
        options=ChatCacheLookupInput(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=request_runtime.dataset_id_used or turn_session.scope_dataset_id,
            document_ids=document_ids,
            history=request.history,
            enable_long_term_memory=request.enable_long_term_memory,
            long_term_messages=turn_session.long_term_messages,
            enable_structured_memory=request.enable_structured_memory,
            question=request.message,
            rag_config=jsonable_encoder(effective_rag_config.model_dump()),
            prompt_config=prompt_cfg,
            structured_output=request.structured_output,
            structured_preset=request.structured_preset,
            use_graph=effective_rag_config.use_graph,
        ),
    )
    full_response = cache_state.full_response
    citations_data = cache_state.citations_data
    metrics_data = cache_state.metrics_data
    structured_data = cache_state.structured_data

    try:
        if not cache_state.cache_hit and not cache_state.singleflight_hit:
            chat_result = await _run_non_streaming_chat_generation(
                context=ChatExecutionContext(
                    db=db,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    request=request,
                    doc_ids_to_use=document_ids,
                    history_for_llm=request_runtime.history_for_llm,
                    scope_dataset_id=turn_session.scope_dataset_id,
                    dataset_id_used=request_runtime.dataset_id_used,
                    effective_rag_config=effective_rag_config,
                    effective_prompt_template_id=request_runtime.effective_prompt_template_id,
                    effective_prompt_template_key=request_runtime.effective_prompt_template_key,
                    effective_prompt_ab_experiment_key=request_runtime.effective_prompt_ab_experiment_key,
                    rag_config_template_meta=request_runtime.rag_config_template_meta,
                ),
                runtime_metrics=offload_metrics,
            )
            citations_data = chat_result.citations
            full_response = chat_result.content
            metrics_data = dict(chat_result.metrics)
            structured_data = chat_result.structured_data

        metrics_data = annotate_chat_cache_metrics(
            {**metrics_data, **offload_metrics},
            enabled=cache_state.cache_feature_enabled,
            hit=cache_state.cache_hit,
            skip_reason=None if cache_state.cache_hit else cache_state.cache_skip_reason,
        )
        metrics_data = annotate_chat_singleflight_metrics(
            metrics_data,
            enabled=bool(settings.CHAT_RESPONSE_SINGLEFLIGHT_ENABLED),
            hit=cache_state.singleflight_hit,
            role=_singleflight_role(
                singleflight_hit=cache_state.singleflight_hit,
                singleflight_leader=cache_state.singleflight_leader,
            ),
        )

        metrics_data = apply_chat_runtime_metrics_context(
            metrics_data,
            dataset_id_used=request_runtime.dataset_id_used,
            effective_prompt_template_id=request_runtime.effective_prompt_template_id,
            effective_prompt_template_key=request_runtime.effective_prompt_template_key,
            effective_prompt_ab_experiment_key=request_runtime.effective_prompt_ab_experiment_key,
            dataset_rag_defaults_applied_fields=request_runtime.dataset_rag_defaults_applied_fields,
            dataset_rag_config_template_defaults_applied_fields=(
                request_runtime.dataset_rag_config_template_defaults_applied_fields
            ),
            rag_config_template_meta=request_runtime.rag_config_template_meta,
            dataset_prompt_defaults_applied_fields=request_runtime.dataset_prompt_defaults_applied_fields,
            tenant_qps_meta=tenant_qps_meta,
            quota_meta=quota_meta,
        )

        metrics_data = await finalize_chat_response(
            options=ChatResponseFinalizationInput(
                db=db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                account_id=account_id,
                assistant_message_id=assistant_message_id,
                request_id=request_id,
                question=request.message,
                document_count=0 if document_ids is None else len(document_ids),
                full_response=full_response,
                citations=citations_data,
                metrics=metrics_data,
                structured_data=structured_data,
                dataset_id_used=request_runtime.dataset_id_used,
                cache_eligible=cache_state.cache_eligible,
                cache_hit=cache_state.cache_hit,
                cache_key=cache_state.cache_key,
                singleflight_key=cache_state.singleflight_key,
                singleflight_leader=cache_state.singleflight_leader,
                request_enable_structured_memory=request.enable_structured_memory,
                ip=http_request.client.host if http_request.client is not None else None,
                user_agent=http_request.headers.get("user-agent"),
                enable_online_eval=effective_rag_config.use_graph or cache_state.cache_hit,
                retrieval_mode_default=effective_rag_config.retrieval_mode,
            ),
        )

    except asyncio.CancelledError:
        _reject_singleflight_leader_if_needed(
            singleflight_key=cache_state.singleflight_key,
            singleflight_leader=cache_state.singleflight_leader,
            error=InflightResponseLeaderCancelledError("singleflight leader request cancelled"),
        )
        raise
    except RetrievalAdmissionTimeoutError as exc:
        _reject_singleflight_leader_if_needed(
            singleflight_key=cache_state.singleflight_key,
            singleflight_leader=cache_state.singleflight_leader,
            error=exc,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        _reject_singleflight_leader_if_needed(
            singleflight_key=cache_state.singleflight_key,
            singleflight_leader=cache_state.singleflight_leader,
            error=exc,
        )
        logger.exception("Chat error: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail=format_stream_error_message(exc)) from exc

    # Optional: auto-update persistent summary after the assistant turn (best-effort).
    _schedule_summary_update(
        background_tasks=background_tasks,
        request=request,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )

    retrieval_mode_used = metrics_data.get("retrieval_mode")
    vector_backend_used = metrics_data.get("vector_backend")
    structured_ok = bool(metrics_data.get("structured_parse_ok")) and structured_data is not None

    total_tokens = num_tokens_from_string(full_response)
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": total_tokens,
        "total_tokens": total_tokens,
        "source": "mock" if bool(settings.LLM_MOCK_ENABLED) else "estimate",
    }

    return {
        "conversation_id": conversation_id,
        "assistant_message_id": assistant_message_id,
        "request_id": request_id,
        "content": full_response,
        "citations": citations_data,
        "total_tokens": total_tokens,
        "usage": usage,
        "total_chars": len(full_response),
        "retrieval_mode": retrieval_mode_used,
        "vector_backend": vector_backend_used,
        "confidence_score": metrics_data.get("confidence_score"),
        "followup_questions": metrics_data.get("followup_questions") or [],
        "metrics": metrics_data,
        "structured": structured_ok if request.structured_output else False,
        "structured_data": structured_data,
    }


@router.post("/stream", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def stream_chat(
    http_request: Request,
    request: ChatRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Streaming chat endpoint (core flow).
    """

    turn_session, tenant_qps_meta, quota_meta = await _prepare_chat_turn(
        db=db, tenant_id=tenant_id, account_id=account_id, request=request
    )
    conversation_id = turn_session.conversation_id

    # Provide a stable assistant message id for the whole stream so clients can
    # correlate SSE events with persisted rows (and so headers can expose it).
    assistant_message_id = uuid.uuid4()

    return StreamingResponse(
        stream_chat_sse_events(
            http_request=http_request,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            conversation_id=conversation_id,
            scope_dataset_id=turn_session.scope_dataset_id,
            allowed_doc_ids=turn_session.allowed_doc_ids,
            long_term_messages=turn_session.long_term_messages,
            assistant_message_id=assistant_message_id,
            tenant_qps_meta=tenant_qps_meta,
            quota_meta=quota_meta,
            spawn_background_task=_spawn_background_task,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Conversation-ID": str(conversation_id),
            "X-Assistant-Message-ID": str(assistant_message_id),
            "Access-Control-Expose-Headers": "X-Request-ID, X-Conversation-ID, X-Assistant-Message-ID",
        },
    )
