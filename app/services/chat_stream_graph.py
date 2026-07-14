
import asyncio
import contextlib
import threading
from dataclasses import dataclass, replace
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


async def _iterate_sync_in_worker(
    factory: Callable[[], Any],
    *,
    max_queue_size: int = 16,
) -> AsyncIterator[Any]:
    """Iterate a blocking generator without running any of it on the event loop."""

    outbox: asyncio.Queue[tuple[bool, Any]] = asyncio.Queue()
    slots = threading.BoundedSemaphore(max(1, max_queue_size))
    stop = threading.Event()
    loop = asyncio.get_running_loop()

    def put(payload: tuple[bool, Any]) -> bool:
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

    def produce() -> None:
        iterator = None
        try:
            iterator = iter(factory())
            for item in iterator:
                if not put((True, item)):
                    return
        except Exception as exc:
            put((False, exc))
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()
            put((True, _SYNC_STREAM_END))

    producer = asyncio.create_task(asyncio.to_thread(produce))
    try:
        while True:
            ok, item = await outbox.get()
            slots.release()
            if item is _SYNC_STREAM_END:
                break
            if not ok:
                raise item
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


async def stream_graph_chat_events(
    *,
    context: ChatExecutionContext,
    result_holder: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    from app.rag.core.text import parse_json_from_text
    from app.rag.pipelines.langgraph import build_rag_state, rag_workflow

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

    thread_id = str(conversation_id) if conversation_id else f"rag-{request_id}"
    runtime_context = {
        "request_id": str(request_id),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "account_id": account_id,
    }

    state = build_rag_state(
        question=request.message,
        history=history_for_llm,
        document_ids=doc_ids_to_use,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id_used or scope_dataset_id,
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
        prompt_template_id=effective_prompt_template_id,
        prompt_template_key=effective_prompt_template_key,
        prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        ab_user_key=account_id,
        db=db,
    )
    if rag_config_template_meta:
        state["rag_config_template"] = rag_config_template_meta

    try:
        import inspect

        from app.services.chat_tag_service import build_chat_tag_context_docs

        tag_kwargs: dict[str, Any] = {
            "tenant_id": tenant_id,
            "document_ids": doc_ids_to_use,
            "question": request.message,
        }
        if "must_recall_expected_source_keys" in inspect.signature(build_chat_tag_context_docs).parameters:
            tag_kwargs["must_recall_expected_source_keys"] = (
                effective_rag_config.must_recall_expected_source_keys
            )

        tag_docs, tag_meta = build_chat_tag_context_docs(db, **tag_kwargs)
        state["tag_docs"] = tag_docs
        state["tag_meta"] = tag_meta
        if bool(tag_meta.get("enabled")):
            yield {"type": "event", "data": {"message": "尝试表格查询（TAG）…"}}
    except Exception as exc:  # noqa: BLE001
        state["tag_meta"] = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    final_state: dict[str, Any] | None = None
    citations_sent = False
    answer_sent = False
    response_parts: list[str] = []
    citations_data: list[dict[str, Any]] = []

    def graph_events():
        return rag_workflow.stream(
            state,
            config=config,
            context=runtime_context,
            stream_mode=["custom", "values"],
        )

    async for mode, chunk in _iterate_sync_in_worker(graph_events):
        if mode == "custom":
            yield {"type": "graph", "data": chunk}
            continue

        if mode != "values" or not isinstance(chunk, dict):
            continue

        final_state = chunk

        if not citations_sent and "citations" in chunk:
            citations_data = chunk.get("citations") or []
            citations_sent = True
            yield {"type": "citations", "data": citations_data}

        if not answer_sent and "answer" in chunk:
            answer_text = chunk.get("answer") or ""
            chunk_size = 120
            for i in range(0, len(answer_text), chunk_size):
                token_chunk = answer_text[i : i + chunk_size]
                response_parts.append(token_chunk)
                yield {"type": "token", "data": {"content": token_chunk}}
            answer_sent = True

    graph_result = final_state or {}

    if not citations_sent:
        citations_data = graph_result.get("citations") or []
        yield {"type": "citations", "data": citations_data}

    if not answer_sent:
        answer_text = graph_result.get("answer") or ""
        chunk_size = 120
        for i in range(0, len(answer_text), chunk_size):
            token_chunk = answer_text[i : i + chunk_size]
            response_parts.append(token_chunk)
            yield {"type": "token", "data": {"content": token_chunk}}

    full_response = "".join(response_parts)
    metrics_data = graph_result.get("metrics") or {
        "retrieval_mode": effective_rag_config.retrieval_mode,
        "vector_backend": settings.VECTOR_BACKEND,
        "elapsed_sec": None,
    }
    metrics_data = dict(metrics_data or {})
    metrics_data.setdefault("model_used", graph_result.get("model_used"))
    metrics_data.setdefault("route", graph_result.get("route"))

    structured_data = None
    if request.structured_output:
        from app.rag.core.text import parse_json_from_text

        structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
        metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
        metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
        metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
        metrics_data["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
        metrics_data["structured_preset"] = request.structured_preset

    result_holder["content"] = full_response
    result_holder["citations"] = citations_data
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
