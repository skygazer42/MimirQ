"""
Chat API.
"""

import asyncio
import contextlib
import uuid
from dataclasses import replace
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import (
    ChatRequest,
    ChatResponse,
)
from app.api.v1 import chat_conversation_memory, chat_conversations
from app.core.config import settings
from app.core.database import get_db
from app.core.token_utils import num_tokens_from_string
from app.rag.core.logging import get_logger
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_AUTO as CONVERSATION_TITLE_SOURCE_AUTO,
)
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_MANUAL as CONVERSATION_TITLE_SOURCE_MANUAL,
)
from app.services.chat_conversation_titles import (
    apply_auto_conversation_title as _apply_auto_conversation_title,
)
from app.services.chat_execution_runtime import (
    ChatExecutionContext as _ChatExecutionContext,
)
from app.services.chat_execution_runtime import (
    execute_extractive_fallback_once as _execute_extractive_fallback_once,
)
from app.services.chat_execution_runtime import (
    execute_graph_chat_once as _execute_graph_chat_once,
)
from app.services.chat_execution_runtime import (
    execute_langchain_chat_once as _execute_langchain_chat_once,
)
from app.services.chat_execution_runtime import (
    is_model_provider_unavailable_circuit_open as _is_model_provider_unavailable_circuit_open,
)
from app.services.chat_execution_runtime import (
    is_model_provider_unavailable_error as _is_model_provider_unavailable_error,
)
from app.services.chat_execution_runtime import (
    mark_model_provider_unavailable as _mark_model_provider_unavailable,
)
from app.services.chat_execution_runtime import (
    preflight_model_provider_fast as _preflight_model_provider_fast,
)
from app.services.chat_persistence import (
    ChatResponseFinalizationInput as _ChatResponseFinalizationInput,
)
from app.services.chat_persistence import (
    finalize_chat_response_sync as _finalize_chat_response_sync,
)
from app.services.chat_response_cache import (
    InflightResponseLeaderCancelledError,
    reject_inflight_chat_response,
)
from app.services.chat_runtime import (
    ChatCacheLookupInput as _ChatCacheLookupInput,
)
from app.services.chat_runtime import (
    annotate_chat_cache_metrics as _annotate_chat_cache_metrics,
)
from app.services.chat_runtime import (
    annotate_chat_singleflight_metrics as _annotate_chat_singleflight_metrics,
)
from app.services.chat_runtime import (
    apply_chat_runtime_metrics_context as _apply_chat_runtime_metrics_context,
)
from app.services.chat_runtime import (
    format_stream_error_message as _format_stream_error_message,
)
from app.services.chat_runtime import (
    prepare_chat_cache_lookup as _prepare_chat_cache_lookup_impl,
)
from app.services.chat_runtime import (
    prepare_chat_request_runtime as _prepare_chat_request_runtime,
)
from app.services.chat_runtime import (
    prepare_chat_turn_session as _prepare_chat_turn_session,
)
from app.services.chat_runtime import (
    prepare_non_streaming_chat_cache_state as _prepare_non_streaming_chat_cache_state,
)
from app.services.chat_stream_orchestrator import (
    stream_chat_sse_events as _stream_chat_sse_events,
)
from app.services.chat_turn_persistence import (
    auto_update_summary_background as _auto_update_summary_background,
)
from app.services.metrics_logger import set_metrics_context
from app.services.quota_service import check_chat_assistant_token_quota
from app.services.rag_runtime_limiter import (
    RetrievalAdmissionTimeoutError,
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call_with_managed_session,
)

logger = get_logger("api.chat")

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

ChatCacheLookupInput = _ChatCacheLookupInput
_prepare_chat_cache_lookup = _prepare_chat_cache_lookup_impl
_apply_auto_conversation_title = _apply_auto_conversation_title


async def _offload_extractive_fallback(
    *,
    request_db: Session,
    runtime_metrics: dict[str, Any],
    **kwargs: Any,
) -> Any:
    return await run_blocking_retrieval_call_with_managed_session(
        lambda worker_db: _execute_extractive_fallback_once(db=worker_db, **kwargs),
        request_db=request_db,
        runtime_metrics=runtime_metrics,
    )


async def _offload_graph_chat(
    *,
    request_db: Session,
    context: _ChatExecutionContext,
) -> Any:
    return await run_blocking_call_with_managed_session(
        lambda worker_db: _execute_graph_chat_once(
            context=replace(context, db=worker_db),
        ),
        request_db=request_db,
    )


def _build_extractive_fallback_kwargs(
    *,
    tenant_id: UUID,
    account_id: str,
    request: ChatRequest,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_rag_config: Any,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "account_id": account_id,
        "request": request,
        "doc_ids_to_use": doc_ids_to_use,
        "history_for_llm": history_for_llm,
        "scope_dataset_id": scope_dataset_id,
        "dataset_id_used": dataset_id_used,
        "effective_rag_config": effective_rag_config,
    }


async def _run_extractive_chat_fallback(
    *,
    request_db: Session,
    fallback_kwargs: dict[str, Any],
    reason: str,
    runtime_metrics: dict[str, Any],
    original_error: Exception | None = None,
) -> Any:
    kwargs = dict(fallback_kwargs)
    kwargs["reason"] = reason
    if original_error is not None:
        kwargs["original_error"] = original_error
    return await _offload_extractive_fallback(
        request_db=request_db,
        runtime_metrics=runtime_metrics,
        **kwargs,
    )


def _attach_generation_fallback_error(chat_result: Any, provider_error: str | None) -> Any:
    if not provider_error:
        return chat_result
    metrics_data = dict(chat_result.metrics or {})
    metrics_data["generation_fallback_error"] = provider_error
    return type(chat_result)(
        content=chat_result.content,
        citations=chat_result.citations,
        metrics=metrics_data,
        structured_data=chat_result.structured_data,
    )


def _build_chat_execution_context(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: ChatRequest,
    conversation_id: UUID,
    request_id: str,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_rag_config: Any,
    effective_prompt_template_id: UUID | None,
    effective_prompt_template_key: str | None,
    effective_prompt_ab_experiment_key: str | None,
    rag_config_template_meta: dict[str, Any] | None,
) -> _ChatExecutionContext:
    return _ChatExecutionContext(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        conversation_id=conversation_id,
        request_id=request_id,
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


async def _execute_provider_chat_once(
    *,
    db: Session,
    fallback_kwargs: dict[str, Any],
    runtime_metrics: dict[str, Any],
    conversation_id: UUID,
    request_id: str,
    effective_rag_config: Any,
    tenant_id: UUID,
    account_id: str,
    request: ChatRequest,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_prompt_template_id: UUID | None,
    effective_prompt_template_key: str | None,
    effective_prompt_ab_experiment_key: str | None,
    rag_config_template_meta: dict[str, Any] | None,
) -> Any:
    provider_available, provider_error = await _preflight_model_provider_fast()
    if not provider_available:
        chat_result = await _run_extractive_chat_fallback(
            request_db=db,
            fallback_kwargs=fallback_kwargs,
            reason="model_provider_preflight_failed",
            runtime_metrics=runtime_metrics,
        )
        return _attach_generation_fallback_error(chat_result, provider_error)

    execution_context = _build_chat_execution_context(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        conversation_id=conversation_id,
        request_id=request_id,
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
    try:
        if effective_rag_config.use_graph:
            return await _offload_graph_chat(
                request_db=db,
                context=execution_context,
            )
        from app.rag.engine import get_rag_engine

        engine = get_rag_engine()
        return await _execute_langchain_chat_once(
            engine=engine,
            context=execution_context,
        )
    except Exception as exc:
        if not _is_model_provider_unavailable_error(exc):
            raise
        _mark_model_provider_unavailable()
        return await _run_extractive_chat_fallback(
            request_db=db,
            fallback_kwargs=fallback_kwargs,
            reason="model_provider_runtime_unavailable",
            runtime_metrics=runtime_metrics,
            original_error=exc,
        )


async def _run_non_streaming_chat_generation(
    *,
    db: Session,
    conversation_id: UUID,
    request_id: str,
    tenant_id: UUID,
    account_id: str,
    request: ChatRequest,
    doc_ids_to_use: list[UUID],
    history_for_llm: list[dict[str, Any]],
    scope_dataset_id: UUID | None,
    dataset_id_used: UUID | None,
    effective_rag_config: Any,
    effective_prompt_template_id: UUID | None,
    effective_prompt_template_key: str | None,
    effective_prompt_ab_experiment_key: str | None,
    rag_config_template_meta: dict[str, Any] | None,
    runtime_metrics: dict[str, Any],
) -> Any:
    fallback_kwargs = _build_extractive_fallback_kwargs(
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        doc_ids_to_use=doc_ids_to_use,
        history_for_llm=history_for_llm,
        scope_dataset_id=scope_dataset_id,
        dataset_id_used=dataset_id_used,
        effective_rag_config=effective_rag_config,
    )
    if getattr(effective_rag_config, "answer_mode", "llm") == "extractive":
        return await _run_extractive_chat_fallback(
            request_db=db,
            fallback_kwargs=fallback_kwargs,
            reason="explicit_extractive_answer_mode",
            runtime_metrics=runtime_metrics,
        )
    if _is_model_provider_unavailable_circuit_open():
        return await _run_extractive_chat_fallback(
            request_db=db,
            fallback_kwargs=fallback_kwargs,
            reason="model_provider_circuit_open",
            runtime_metrics=runtime_metrics,
        )
    return await _execute_provider_chat_once(
        db=db,
        fallback_kwargs=fallback_kwargs,
        runtime_metrics=runtime_metrics,
        conversation_id=conversation_id,
        request_id=request_id,
        effective_rag_config=effective_rag_config,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        doc_ids_to_use=doc_ids_to_use,
        history_for_llm=history_for_llm,
        scope_dataset_id=scope_dataset_id,
        dataset_id_used=dataset_id_used,
        effective_prompt_template_id=effective_prompt_template_id,
        effective_prompt_template_key=effective_prompt_template_key,
        effective_prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        rag_config_template_meta=rag_config_template_meta,
    )


def _raise_chat_quota_exceeded_if_needed(quota_meta: dict[str, Any]) -> None:
    if not quota_meta.get("enabled"):
        return
    if not quota_meta.get("exceeded"):
        return
    if quota_meta.get("mode") != "block":
        return
    raise HTTPException(
        status_code=429,
        detail={
            "message": "Chat quota exceeded (assistant tokens)",
            "retry_after_sec": None,
            "limit": int(quota_meta.get("limit") or 0),
            "scope": "chat_tokens",
        },
    )


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


def _maybe_schedule_summary_update(
    *,
    background_tasks: BackgroundTasks,
    request: ChatRequest,
    tenant_id: UUID,
    conversation_id: UUID | None,
) -> None:
    if not bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False)):
        return
    if not bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False)):
        return
    if not bool(getattr(request, "enable_summary_memory", False)):
        return
    if not conversation_id:
        return
    with contextlib.suppress(Exception):
        background_tasks.add_task(_auto_update_summary_background, tenant_id=tenant_id, conversation_id=conversation_id)


def _spawn_background_task(coro: Any) -> None:
    """
    Best-effort fire-and-forget task runner.

    Keep a strong reference to background tasks until completion.
    """
    try:
        task = asyncio.create_task(coro)
    except Exception:
        with contextlib.suppress(Exception):
            coro.close()
        return

    _BACKGROUND_TASKS.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _BACKGROUND_TASKS.discard(t)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            exc = t.exception()
            if exc is not None:
                logger.warning("Background task failed: %s", str(exc)[:200])

    task.add_done_callback(_done)


_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
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
    conversation_id = request.conversation_id
    citations_data: list = []
    full_response = ""
    allowed_doc_ids: list[UUID] = []
    long_term_messages: list[dict] = []
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))
    allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))

    # Best-effort per-tenant aggregate QPS limiter.
    from app.services.tenant_quota_service import enforce_tenant_qps_quota_async

    tenant_qps_meta = await enforce_tenant_qps_quota_async(tenant_id=tenant_id, key="chat")

    quota_meta = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    _raise_chat_quota_exceeded_if_needed(quota_meta)

    turn_session = _prepare_chat_turn_session(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        allow_empty_docs=allow_empty_docs,
        allow_open_scope=allow_open_scope,
        conversation_not_found_detail=CONVERSATION_NOT_FOUND_DETAIL,
        dataset_required_detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
        document_scope_mismatch_detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL,
        empty_scope_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
    )
    conversation_id = turn_session.conversation_id
    scope_dataset_id = turn_session.scope_dataset_id
    allowed_doc_ids = turn_session.allowed_doc_ids
    long_term_messages = turn_session.long_term_messages

    request_id = getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
    assistant_message_id = uuid.uuid4()
    set_metrics_context(
        request_id=str(request_id),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        account_id=account_id,
    )

    doc_ids_to_use = allowed_doc_ids or []
    request_runtime = _prepare_chat_request_runtime(
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
    effective_rag_config = request_runtime.effective_rag_config
    dataset_id_used = request_runtime.dataset_id_used
    dataset_rag_defaults_applied_fields = request_runtime.dataset_rag_defaults_applied_fields
    effective_prompt_template_id = request_runtime.effective_prompt_template_id
    effective_prompt_template_key = request_runtime.effective_prompt_template_key
    effective_prompt_ab_experiment_key = request_runtime.effective_prompt_ab_experiment_key
    dataset_prompt_defaults_applied_fields = request_runtime.dataset_prompt_defaults_applied_fields
    dataset_rag_config_template_defaults_applied_fields = (
        request_runtime.dataset_rag_config_template_defaults_applied_fields
    )
    rag_config_template_meta = request_runtime.rag_config_template_meta
    history_for_llm = request_runtime.history_for_llm

    metrics_data: dict = {}
    offload_metrics: dict[str, Any] = {}
    structured_data = None

    # Optional chat response cache (best-effort).
    cache_key: str | None = None
    cache_hit = False
    singleflight_hit = False
    singleflight_leader = False
    singleflight_key: str | None = None
    cache_scope_dataset_id = dataset_id_used or scope_dataset_id
    rag_cfg = jsonable_encoder(effective_rag_config.model_dump())
    prompt_cfg = {
        "prompt_template_id": str(effective_prompt_template_id) if effective_prompt_template_id else None,
        "prompt_template_key": (effective_prompt_template_key or None),
        "prompt_ab_experiment_key": (effective_prompt_ab_experiment_key or None),
    }
    cache_state = await _prepare_non_streaming_chat_cache_state(
        options=_ChatCacheLookupInput(
            db=db,
            tenant_id=tenant_id,
            account_id=str(account_id or ""),
            dataset_id=cache_scope_dataset_id,
            document_ids=doc_ids_to_use,
            history=request.history,
            enable_long_term_memory=bool(request.enable_long_term_memory),
            long_term_messages=long_term_messages,
            enable_structured_memory=bool(getattr(request, "enable_structured_memory", False)),
            question=request.message,
            rag_config=rag_cfg,
            prompt_config=prompt_cfg,
            structured_output=bool(request.structured_output),
            structured_preset=request.structured_preset,
            use_graph=bool(effective_rag_config.use_graph),
        ),
    )
    cache_feature_enabled = cache_state.cache_feature_enabled
    cache_key = cache_state.cache_key
    cache_skip_reason = cache_state.cache_skip_reason
    cache_eligible = cache_state.cache_eligible
    cache_hit = cache_state.cache_hit
    singleflight_hit = cache_state.singleflight_hit
    singleflight_leader = cache_state.singleflight_leader
    singleflight_key = cache_state.singleflight_key
    full_response = cache_state.full_response
    citations_data = cache_state.citations_data
    metrics_data = cache_state.metrics_data
    structured_data = cache_state.structured_data

    try:
        if not cache_hit and not singleflight_hit:
            chat_result = await _run_non_streaming_chat_generation(
                db=db,
                conversation_id=conversation_id,
                request_id=str(request_id),
                tenant_id=tenant_id,
                account_id=account_id,
                request=request,
                doc_ids_to_use=doc_ids_to_use,
                history_for_llm=history_for_llm,
                scope_dataset_id=scope_dataset_id,
                dataset_id_used=dataset_id_used,
                effective_rag_config=effective_rag_config,
                effective_prompt_template_id=effective_prompt_template_id,
                effective_prompt_template_key=effective_prompt_template_key,
                effective_prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
                rag_config_template_meta=rag_config_template_meta,
                runtime_metrics=offload_metrics,
            )
            if chat_result is not None:
                citations_data = chat_result.citations
                full_response = chat_result.content
                metrics_data = dict(chat_result.metrics or {})
                structured_data = chat_result.structured_data

        if offload_metrics:
            metrics_data = {**metrics_data, **offload_metrics}
        metrics_data = _annotate_chat_cache_metrics(
            metrics_data,
            enabled=cache_feature_enabled,
            hit=cache_hit,
            skip_reason=None if cache_hit else cache_skip_reason,
        )
        metrics_data = _annotate_chat_singleflight_metrics(
            metrics_data,
            enabled=bool(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False)),
            hit=singleflight_hit,
            role=_singleflight_role(
                singleflight_hit=singleflight_hit,
                singleflight_leader=singleflight_leader,
            ),
        )

        metrics_data = _apply_chat_runtime_metrics_context(
            metrics_data,
            dataset_id_used=dataset_id_used,
            effective_prompt_template_id=effective_prompt_template_id,
            effective_prompt_template_key=effective_prompt_template_key,
            effective_prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
            dataset_rag_defaults_applied_fields=dataset_rag_defaults_applied_fields,
            dataset_rag_config_template_defaults_applied_fields=dataset_rag_config_template_defaults_applied_fields,
            rag_config_template_meta=rag_config_template_meta,
            dataset_prompt_defaults_applied_fields=dataset_prompt_defaults_applied_fields,
            tenant_qps_meta=tenant_qps_meta,
            quota_meta=quota_meta,
        )

        metrics_data = _finalize_chat_response_sync(
            options=_ChatResponseFinalizationInput(
                db=db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                account_id=account_id,
                assistant_message_id=assistant_message_id,
                request_id=str(request_id),
                question=request.message,
                document_count=len(doc_ids_to_use),
                full_response=full_response,
                citations=citations_data,
                metrics=metrics_data,
                structured_data=structured_data,
                dataset_id_used=dataset_id_used,
                cache_eligible=cache_eligible,
                cache_hit=cache_hit,
                cache_key=cache_key,
                singleflight_key=singleflight_key,
                singleflight_leader=singleflight_leader,
                request_enable_structured_memory=bool(getattr(request, "enable_structured_memory", False)),
                ip=getattr(getattr(http_request, "client", None), "host", None),
                user_agent=http_request.headers.get("user-agent"),
                enable_online_eval=bool(effective_rag_config.use_graph) or bool(cache_hit),
                retrieval_mode_default=effective_rag_config.retrieval_mode,
            ),
        )

    except asyncio.CancelledError:
        _reject_singleflight_leader_if_needed(
            singleflight_key=singleflight_key,
            singleflight_leader=singleflight_leader,
            error=InflightResponseLeaderCancelledError("singleflight leader request cancelled"),
        )
        raise
    except RetrievalAdmissionTimeoutError as exc:
        _reject_singleflight_leader_if_needed(
            singleflight_key=singleflight_key,
            singleflight_leader=singleflight_leader,
            error=exc,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        _reject_singleflight_leader_if_needed(
            singleflight_key=singleflight_key,
            singleflight_leader=singleflight_leader,
            error=exc,
        )
        logger.exception("Chat error: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail=_format_stream_error_message(exc)) from exc

    if conversation_id is None:
        raise HTTPException(status_code=500, detail="Conversation id missing")

    # Optional: auto-update persistent summary after the assistant turn (best-effort).
    _maybe_schedule_summary_update(
        background_tasks=background_tasks,
        request=request,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )

    retrieval_mode_used = metrics_data.get("retrieval_mode") or effective_rag_config.retrieval_mode
    vector_backend_used = metrics_data.get("vector_backend") or settings.VECTOR_BACKEND
    structured_ok = bool(metrics_data.get("structured_parse_ok")) and structured_data is not None

    total_tokens = num_tokens_from_string(full_response or "")
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": total_tokens,
        "total_tokens": total_tokens,
        "source": "mock" if bool(getattr(settings, "LLM_MOCK_ENABLED", False)) else "estimate",
    }

    return {
        "conversation_id": conversation_id,
        "assistant_message_id": assistant_message_id,
        "request_id": str(request_id),
        "content": full_response,
        "citations": citations_data,
        "total_tokens": total_tokens,
        "usage": usage,
        "total_chars": len(full_response or ""),
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

    long_term_messages: list[dict] = []
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))
    allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))

    # Best-effort per-tenant aggregate QPS limiter.
    from app.services.tenant_quota_service import enforce_tenant_qps_quota_async

    tenant_qps_meta = await enforce_tenant_qps_quota_async(tenant_id=tenant_id, key="chat")

    quota_meta = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    if quota_meta.get("enabled") and quota_meta.get("exceeded") and quota_meta.get("mode") == "block":
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Chat quota exceeded (assistant tokens)",
                "retry_after_sec": None,
                "limit": int(quota_meta.get("limit") or 0),
                "scope": "chat_tokens",
            },
        )

    turn_session = _prepare_chat_turn_session(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        allow_empty_docs=allow_empty_docs,
        allow_open_scope=allow_open_scope,
        conversation_not_found_detail=CONVERSATION_NOT_FOUND_DETAIL,
        dataset_required_detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
        document_scope_mismatch_detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL,
        empty_scope_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
    )
    conversation_id = turn_session.conversation_id
    scope_dataset_id = turn_session.scope_dataset_id
    allowed_doc_ids = turn_session.allowed_doc_ids
    long_term_messages = turn_session.long_term_messages

    # Provide a stable assistant message id for the whole stream so clients can
    # correlate SSE events with persisted rows (and so headers can expose it).
    assistant_message_id = uuid.uuid4()

    return StreamingResponse(
        _stream_chat_sse_events(
            http_request=http_request,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            conversation_id=conversation_id,
            scope_dataset_id=scope_dataset_id,
            allowed_doc_ids=allowed_doc_ids,
            long_term_messages=long_term_messages,
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
            "X-Conversation-ID": str(conversation_id) if conversation_id else "",
            "X-Assistant-Message-ID": str(assistant_message_id),
            "Access-Control-Expose-Headers": "X-Request-ID, X-Conversation-ID, X-Assistant-Message-ID",
        },
    )
