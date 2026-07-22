
import asyncio
import contextlib
import json
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Awaitable, Callable, cast

from app.core.stream_events import StreamEmitter, bind_stream_emitter, reset_stream_emitter
from app.rag.core.logging import get_logger
from app.services.chat_execution_runtime import ChatExecutionContext
from app.services.chat_runtime import (
    ChatStreamPersistInput,
    annotate_chat_cache_metrics,
    apply_chat_runtime_metrics_context,
    store_chat_response_cache_if_needed,
)
from app.services.chat_stream_persistence import dispatch_chat_stream_persistence

logger = get_logger(__name__)


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
) -> AsyncIterator[str]:
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
    citations_data: list[Any] = []
    response_parts: list[str] = []
    metrics_data: dict[str, Any] | None = {}
    structured_data: object | None = None

    try:
        while True:
            if options.disconnect_check is not None:
                try:
                    if await options.disconnect_check():
                        disconnected = True
                        producer_task.cancel()
                        break
                except Exception as exc:
                    logger.debug("Ignoring chat stream disconnect check failure: %s", exc)

            try:
                ev = (
                    await asyncio.wait_for(q.get(), timeout=options.heartbeat_sec)
                    if options.heartbeat_sec > 0
                    else await q.get()
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if ev is None:
                break

            event = ev
            if event.get("type") == "citations":
                citations_data = event.get("data") or []

            if event.get("type") == "error":
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                message = str(data.get("message") or data.get("error") or "Chat stream error")
                raise RuntimeError(message)

            if event.get("type") == "done":
                if isinstance(event.get("data"), dict):
                    event["data"]["assistant_message_id"] = str(
                        options.persist_options.assistant_message_id
                    )
                    metrics_data = event["data"].get("metrics", {})  # type: ignore[assignment]
                    structured_data = event["data"].get("structured_data")
                else:
                    metrics_data = {}
                if isinstance(metrics_data, dict):
                    metrics_data = annotate_chat_cache_metrics(
                        metrics_data,
                        enabled=options.cache_feature_enabled,
                        hit=options.cache_hit,
                        skip_reason=None if options.cache_hit else options.cache_skip_reason,
                    )
                else:
                    metrics_data = annotate_chat_cache_metrics(
                        {},
                        enabled=options.cache_feature_enabled,
                        hit=options.cache_hit,
                        skip_reason=None if options.cache_hit else options.cache_skip_reason,
                    )
                metrics_data = apply_chat_runtime_metrics_context(
                    metrics_data if isinstance(metrics_data, dict) else {},
                    dataset_id_used=dataset_id_used,
                    dataset_rag_defaults_applied_fields=options.dataset_rag_defaults_applied_fields,
                    dataset_rag_config_template_defaults_applied_fields=options.dataset_rag_config_template_defaults_applied_fields,
                    rag_config_template_meta=rag_config_template_meta,
                    dataset_prompt_defaults_applied_fields=options.dataset_prompt_defaults_applied_fields,
                    tenant_qps_meta=options.tenant_qps_meta,
                    quota_meta=options.quota_meta,
                )
                if isinstance(event.get("data"), dict):
                    event["data"]["metrics"] = dict(metrics_data)

            if event.get("type") == "token":
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                response_parts.append(str((data or {}).get("content") or ""))

            event["request_id"] = str(request_id)
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        if not producer_task.done():
            producer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer_task

    if disconnected:
        return

    full_response = "".join(response_parts)
    if isinstance(metrics_data, dict):
        metrics_data = annotate_chat_cache_metrics(
            metrics_data,
            enabled=options.cache_feature_enabled,
            hit=options.cache_hit,
            skip_reason=None if options.cache_hit else options.cache_skip_reason,
        )
    else:
        metrics_data = annotate_chat_cache_metrics(
            {},
            enabled=options.cache_feature_enabled,
            hit=options.cache_hit,
            skip_reason=None if options.cache_hit else options.cache_skip_reason,
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

    metrics_data = apply_chat_runtime_metrics_context(
        metrics_data if isinstance(metrics_data, dict) else {},
        dataset_id_used=dataset_id_used,
        dataset_rag_defaults_applied_fields=options.dataset_rag_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=options.dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=rag_config_template_meta,
        dataset_prompt_defaults_applied_fields=options.dataset_prompt_defaults_applied_fields,
        tenant_qps_meta=options.tenant_qps_meta,
        quota_meta=options.quota_meta,
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
            top_k=effective_rag_config.top_k,
            score_threshold=effective_rag_config.score_threshold,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id_used or scope_dataset_id,
            structured_output=request.structured_output,
            retrieval_mode=effective_rag_config.retrieval_mode,
            retrieval_profile=effective_rag_config.retrieval_profile,
            retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
            must_recall=effective_rag_config.must_recall,
            must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
            must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
            intent_router=effective_rag_config.intent_router,
            intent_router_policy=effective_rag_config.intent_router_policy,
            enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
            query_aliases=effective_rag_config.query_aliases,
            query_alias_max_queries=effective_rag_config.query_alias_max_queries,
            enable_multi_query=effective_rag_config.enable_multi_query,
            multi_query_count=effective_rag_config.multi_query_count,
            multi_query_temperature=effective_rag_config.multi_query_temperature,
            multi_query_max_chars=effective_rag_config.multi_query_max_chars,
            enable_hyde=effective_rag_config.enable_hyde,
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
            max_tokens=effective_rag_config.max_tokens,
            structured_preset=request.structured_preset,
            visible_evidence_only=effective_rag_config.visible_evidence_only,
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
