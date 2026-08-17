
import asyncio
import contextlib
import threading
from dataclasses import dataclass, field, replace
from typing import Any, AsyncIterator, Callable, cast

from app.core.config import settings
from app.services.chat_execution_runtime import ChatExecutionContext
from app.services.chat_runtime import (
    ChatStreamPersistInput,
    annotate_chat_cache_metrics,
    apply_chat_runtime_metrics_context,
    store_chat_response_cache_if_needed,
)
from app.services.chat_stream_common import (
    build_chat_stream_done_event,
    log_chat_stream_completion_metrics,
)
from app.services.chat_stream_persistence import dispatch_chat_stream_persistence

_SYNC_STREAM_END = object()


def _put_sync_stream_payload(
    *,
    payload: tuple[bool, Any],
    stop: threading.Event,
    slots: threading.BoundedSemaphore,
    loop: asyncio.AbstractEventLoop,
    outbox: asyncio.Queue[tuple[bool, Any]],
) -> bool:
    while not stop.is_set():
        if not slots.acquire(timeout=0.1):
            continue
        try:
            loop.call_soon_threadsafe(outbox.put_nowait, payload)
        except RuntimeError:
            slots.release()
            return False
        return True
    return False


def _close_sync_iterator(iterator: Any) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _run_sync_stream_producer(
    factory: Callable[[], Any],
    *,
    stop: threading.Event,
    slots: threading.BoundedSemaphore,
    loop: asyncio.AbstractEventLoop,
    outbox: asyncio.Queue[tuple[bool, Any]],
) -> None:
    iterator = None
    try:
        iterator = iter(factory())
        for item in iterator:
            if not _put_sync_stream_payload(
                payload=(True, item),
                stop=stop,
                slots=slots,
                loop=loop,
                outbox=outbox,
            ):
                return
    except Exception as exc:
        _put_sync_stream_payload(
            payload=(False, exc),
            stop=stop,
            slots=slots,
            loop=loop,
            outbox=outbox,
        )
    finally:
        _close_sync_iterator(iterator)
        _put_sync_stream_payload(
            payload=(True, _SYNC_STREAM_END),
            stop=stop,
            slots=slots,
            loop=loop,
            outbox=outbox,
        )


async def _iterate_sync_worker_outbox(
    *,
    outbox: asyncio.Queue[tuple[bool, Any]],
    slots: threading.BoundedSemaphore,
) -> AsyncIterator[Any]:
    while True:
        ok, item = await outbox.get()
        slots.release()
        if item is _SYNC_STREAM_END:
            return
        if not ok:
            raise item
        yield item


async def _iterate_sync_in_worker(
    factory: Callable[[], Any],
    *,
    max_queue_size: int = 16,
    stop_event: threading.Event | None = None,
) -> AsyncIterator[Any]:
    """Iterate a blocking generator without running any of it on the event loop."""

    outbox: asyncio.Queue[tuple[bool, Any]] = asyncio.Queue()
    slots = threading.BoundedSemaphore(max(1, max_queue_size))
    stop = stop_event or threading.Event()
    loop = asyncio.get_running_loop()
    producer = asyncio.create_task(
        asyncio.to_thread(
            _run_sync_stream_producer,
            factory,
            stop=stop,
            slots=slots,
            loop=loop,
            outbox=outbox,
        )
    )
    try:
        async for item in _iterate_sync_worker_outbox(outbox=outbox, slots=slots):
            yield item
        await producer
    finally:
        stop.set()
        if not producer.done():
            producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer


@dataclass(frozen=True)
class GraphChatStreamSessionInput:
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
    persist_in_background: bool
    spawn_background_task: Callable[[Any], None]
    persist_options: ChatStreamPersistInput


@dataclass
class _GraphStreamAccumulator:
    final_state: dict[str, Any] | None = None
    citations_sent: bool = False
    answer_sent: bool = False
    response_parts: list[str] = field(default_factory=list)
    citations_data: list[dict[str, Any]] = field(default_factory=list)


def _build_graph_runtime_context(
    *,
    context: ChatExecutionContext,
    cancel_event: threading.Event,
) -> dict[str, Any]:
    return {
        "request_id": str(context.request_id),
        "conversation_id": str(context.conversation_id) if context.conversation_id else None,
        "tenant_id": str(context.tenant_id) if context.tenant_id else None,
        "account_id": context.account_id,
        "cancel_event": cancel_event,
    }


def _build_graph_stream_state(
    *,
    context: ChatExecutionContext,
) -> dict[str, Any]:
    from app.rag.pipelines.langgraph import build_rag_state

    request = context.request
    effective_rag_config = context.effective_rag_config
    state = build_rag_state(
        question=request.message,
        history=context.history_for_llm,
        document_ids=context.doc_ids_to_use,
        tenant_id=context.tenant_id,
        account_id=context.account_id,
        dataset_id=context.dataset_id_used or context.scope_dataset_id,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
        must_recall=effective_rag_config.must_recall,
        must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
        must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
        intent_router=effective_rag_config.intent_router,
        intent_router_policy=effective_rag_config.intent_router_policy,
        industry_rules_enabled=effective_rag_config.industry_rules_enabled,
        industry_rules_rulesets=effective_rag_config.industry_rules_rulesets,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        enable_hyde=effective_rag_config.enable_hyde,
        enable_query_decomposition=effective_rag_config.enable_query_decomposition,
        enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
        hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
        hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
        hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
        hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
        hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
        hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        sparse_retrieval_enabled=effective_rag_config.sparse_retrieval_enabled,
        sparse_retrieval_provider=effective_rag_config.sparse_retrieval_provider,
        metadata_filter=effective_rag_config.metadata_filter,
        max_tokens=effective_rag_config.max_tokens,
        structured_output=request.structured_output,
        structured_preset=request.structured_preset,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        prompt_template_id=context.effective_prompt_template_id,
        prompt_template_key=context.effective_prompt_template_key,
        prompt_ab_experiment_key=context.effective_prompt_ab_experiment_key,
        ab_user_key=context.account_id,
        db=context.db,
    )
    if context.rag_config_template_meta:
        state["rag_config_template"] = context.rag_config_template_meta
    return state


def _build_graph_stream_config(*, conversation_id: Any, request_id: str) -> dict[str, Any]:
    thread_id = str(conversation_id) if conversation_id else f"rag-{request_id}"
    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}


def _maybe_attach_tag_context(
    *,
    state: dict[str, Any],
    db: Any,
    tenant_id: Any,
    doc_ids_to_use: list[Any],
    question: str,
    effective_rag_config: Any,
) -> str | None:
    import inspect

    from app.services.chat_tag_service import build_chat_tag_context_docs

    tag_kwargs: dict[str, Any] = {
        "tenant_id": tenant_id,
        "document_ids": doc_ids_to_use,
        "question": question,
    }
    if "must_recall_expected_source_keys" in inspect.signature(build_chat_tag_context_docs).parameters:
        tag_kwargs["must_recall_expected_source_keys"] = effective_rag_config.must_recall_expected_source_keys

    try:
        tag_docs, tag_meta = build_chat_tag_context_docs(db, **tag_kwargs)
        state["tag_docs"] = tag_docs
        state["tag_meta"] = tag_meta
        if bool(tag_meta.get("enabled")):
            return "尝试表格查询（TAG）…"
    except Exception as exc:  # noqa: BLE001
        state["tag_meta"] = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}
    return None


def _answer_token_events(answer_text: str, response_parts: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i in range(0, len(answer_text), 120):
        token_chunk = answer_text[i : i + 120]
        response_parts.append(token_chunk)
        events.append({"type": "token", "data": {"content": token_chunk}})
    return events


def _consume_graph_value_chunk(
    *,
    chunk: dict[str, Any],
    citations_sent: bool,
    answer_sent: bool,
    response_parts: list[str],
) -> tuple[list[dict[str, Any]], bool, bool, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    citations_data: list[dict[str, Any]] = []
    if not citations_sent and "citations" in chunk:
        citations_data = chunk.get("citations") or []
        citations_sent = True
        events.append({"type": "citations", "data": citations_data})
    if not answer_sent and "answer" in chunk:
        events.extend(_answer_token_events(chunk.get("answer") or "", response_parts))
        answer_sent = True
    return events, citations_sent, answer_sent, citations_data


def _graph_metrics_payload(
    *,
    graph_result: dict[str, Any],
    effective_rag_config: Any,
) -> dict[str, Any]:
    metrics_data = graph_result.get("metrics") or {
        "retrieval_mode": effective_rag_config.retrieval_mode,
        "vector_backend": settings.VECTOR_BACKEND,
        "elapsed_sec": None,
    }
    metrics_data = dict(metrics_data or {})
    metrics_data.setdefault("model_used", graph_result.get("model_used"))
    metrics_data.setdefault("route", graph_result.get("route"))
    return metrics_data


def _parse_structured_graph_output(
    *,
    request: Any,
    full_response: str,
    metrics_data: dict[str, Any],
) -> object | None:
    if not request.structured_output:
        return None

    from app.rag.core.text import parse_json_from_text

    structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
    metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
    metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
    metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
    metrics_data["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
    metrics_data["structured_preset"] = request.structured_preset
    return structured_data


async def _stream_graph_workflow_events(
    *,
    graph_events: Callable[[], Any],
    graph_cancel_event: threading.Event,
    stream_state: _GraphStreamAccumulator,
) -> AsyncIterator[dict[str, Any]]:
    async for mode, chunk in _iterate_sync_in_worker(
        graph_events,
        stop_event=graph_cancel_event,
    ):
        if mode == "custom":
            yield {"type": "graph", "data": chunk}
            continue
        if mode != "values" or not isinstance(chunk, dict):
            continue

        stream_state.final_state = chunk
        events, stream_state.citations_sent, stream_state.answer_sent, citations_chunk = _consume_graph_value_chunk(
            chunk=chunk,
            citations_sent=stream_state.citations_sent,
            answer_sent=stream_state.answer_sent,
            response_parts=stream_state.response_parts,
        )
        if citations_chunk:
            stream_state.citations_data = citations_chunk
        for event in events:
            yield event


async def stream_graph_chat_events(
    *,
    context: ChatExecutionContext,
    result_holder: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    from app.rag.pipelines.langgraph import rag_workflow

    db = context.db
    tenant_id = context.tenant_id
    request = context.request
    conversation_id = context.conversation_id
    request_id = context.request_id
    doc_ids_to_use = context.doc_ids_to_use
    effective_rag_config = context.effective_rag_config

    graph_cancel_event = threading.Event()
    runtime_context = _build_graph_runtime_context(context=context, cancel_event=graph_cancel_event)
    state = _build_graph_stream_state(context=context)
    tag_message = _maybe_attach_tag_context(
        state=state,
        db=db,
        tenant_id=tenant_id,
        doc_ids_to_use=doc_ids_to_use,
        question=request.message,
        effective_rag_config=effective_rag_config,
    )
    if tag_message:
        yield {"type": "event", "data": {"message": tag_message}}

    config = _build_graph_stream_config(conversation_id=conversation_id, request_id=request_id)
    stream_state = _GraphStreamAccumulator()

    db.rollback()
    state.pop("db", None)

    def graph_events():
        return rag_workflow.stream(
            state,
            config=config,
            context=runtime_context,
            stream_mode=["custom", "values"],
        )

    async for event in _stream_graph_workflow_events(
        graph_events=graph_events,
        graph_cancel_event=graph_cancel_event,
        stream_state=stream_state,
    ):
        yield event

    graph_result = stream_state.final_state or {}

    if not stream_state.citations_sent:
        stream_state.citations_data = graph_result.get("citations") or []
        yield {"type": "citations", "data": stream_state.citations_data}

    if not stream_state.answer_sent:
        for event in _answer_token_events(graph_result.get("answer") or "", stream_state.response_parts):
            yield event

    full_response = "".join(stream_state.response_parts)
    metrics_data = _graph_metrics_payload(
        graph_result=graph_result,
        effective_rag_config=effective_rag_config,
    )
    structured_data = _parse_structured_graph_output(
        request=request,
        full_response=full_response,
        metrics_data=metrics_data,
    )

    result_holder["content"] = full_response
    result_holder["citations"] = stream_state.citations_data
    result_holder["metrics"] = metrics_data
    result_holder["structured_data"] = structured_data


async def stream_graph_chat_session_events(
    *,
    options: GraphChatStreamSessionInput,
) -> AsyncIterator[dict[str, Any]]:
    context = options.execution
    db = context.db
    tenant_id = context.tenant_id
    conversation_id = context.conversation_id
    request_id = context.request_id
    dataset_id_used = context.dataset_id_used
    effective_rag_config = context.effective_rag_config
    rag_config_template_meta = context.rag_config_template_meta

    graph_stream_state: dict[str, Any] = {}
    async for graph_event in stream_graph_chat_events(
        context=context,
        result_holder=graph_stream_state,
    ):
        graph_event["request_id"] = str(request_id)
        yield graph_event

    citations_data = list(graph_stream_state.get("citations") or [])
    full_response = str(graph_stream_state.get("content") or "")
    metrics_data = dict(graph_stream_state.get("metrics") or {})
    structured_data = graph_stream_state.get("structured_data")

    metrics_data = annotate_chat_cache_metrics(
        metrics_data,
        enabled=options.cache_feature_enabled,
        hit=options.cache_hit,
        skip_reason=None if options.cache_hit else options.cache_skip_reason,
    )
    metrics_data = apply_chat_runtime_metrics_context(
        metrics_data,
        dataset_id_used=dataset_id_used,
        dataset_rag_defaults_applied_fields=options.dataset_rag_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=options.dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=rag_config_template_meta,
        dataset_prompt_defaults_applied_fields=options.dataset_prompt_defaults_applied_fields,
        tenant_qps_meta=options.tenant_qps_meta,
        quota_meta=options.quota_meta,
    )

    yield build_chat_stream_done_event(
        request_id=str(request_id),
        assistant_message_id=options.persist_options.assistant_message_id,
        conversation_id=conversation_id,
        content=full_response,
        citations=citations_data,
        metrics=metrics_data,
        retrieval_mode_default=effective_rag_config.retrieval_mode,
        vector_backend_default=settings.VECTOR_BACKEND,
        structured=bool(metrics_data.get("structured_parse_ok"))
        and structured_data is not None,
        structured_data=structured_data,
    )

    store_chat_response_cache_if_needed(
        cache_eligible=options.cache_eligible,
        cache_hit=options.cache_hit,
        cache_key=options.cache_key,
        content=full_response,
        citations=citations_data,
        metrics=metrics_data,
        structured_data=structured_data,
    )

    log_chat_stream_completion_metrics(
        request_id=str(request_id),
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        metrics=metrics_data,
        retrieval_mode_default=effective_rag_config.retrieval_mode,
        vector_backend_default=settings.VECTOR_BACKEND,
    )

    dispatch_chat_stream_persistence(
        db=db,
        persist_in_background=options.persist_in_background,
        spawn_background_task=options.spawn_background_task,
        options=cast(
            ChatStreamPersistInput,
            replace(
                options.persist_options,
                content=full_response,
                citations=citations_data,
                metrics=metrics_data,
                structured_data=structured_data,
            ),
        ),
    )
