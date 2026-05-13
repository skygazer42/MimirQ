from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass(frozen=True)
class ExecutedGraphChatOnceResult:
    content: str
    citations: list[dict[str, Any]]
    metrics: dict[str, Any]
    structured_data: object | None


def execute_graph_chat_once(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
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
) -> ExecutedGraphChatOnceResult:
    from app.rag.core.text import parse_json_from_text
    from app.rag.pipelines.langgraph import build_rag_state, rag_workflow

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
        metadata_filter=effective_rag_config.metadata_filter,
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

    multimodal_meta: dict[str, Any] = {"enabled": True, "modality": "text", "reasons": []}
    injected_docs: list[Any] = []

    tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
    image_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}

    try:
        from app.rag.policy.modality_router import classify_query_modality

        modality, reasons = classify_query_modality(request.message)
        multimodal_meta["modality"] = modality
        multimodal_meta["reasons"] = reasons
    except Exception as exc:  # noqa: BLE001
        multimodal_meta["enabled"] = False
        multimodal_meta["modality"] = "text"
        multimodal_meta["reasons"] = [f"router_exception:{str(exc)[:80]}"]
        modality = "text"

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
        if tag_docs:
            injected_docs.extend(tag_docs)
    except Exception as exc:  # noqa: BLE001
        tag_meta = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

    try:
        if str(modality or "text").lower().strip() == "image":
            from app.services.chat_image_service import build_chat_image_context_docs

            ds_for_images = dataset_id_used or scope_dataset_id
            if ds_for_images is not None:
                image_docs, image_meta = build_chat_image_context_docs(
                    db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_id=ds_for_images,
                    question=request.message,
                    top_k=6,
                )
                if image_docs:
                    injected_docs.extend(image_docs)
            else:
                image_meta = {"enabled": False, "used": False, "reason": "missing_dataset_id"}
    except Exception as exc:  # noqa: BLE001
        image_meta = {"enabled": False, "used": False, "reason": f"image_exception:{str(exc)[:120]}"}

    if injected_docs:
        state["tag_docs"] = injected_docs

    state["tag_meta"] = tag_meta
    state["image_meta"] = image_meta
    state["multimodal_router"] = multimodal_meta

    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    graph_result = rag_workflow.invoke(state, config=config, context=runtime_context) or {}

    citations_data = graph_result.get("citations") or []
    full_response = graph_result.get("answer") or ""
    metrics_data = dict(graph_result.get("metrics") or {})
    metrics_data.setdefault("multimodal_router", multimodal_meta)
    metrics_data.setdefault("tag", tag_meta)
    metrics_data.setdefault("image", image_meta)

    structured_data = None
    if request.structured_output:
        structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
        metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
        metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
        metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
        metrics_data["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
        metrics_data["structured_preset"] = request.structured_preset

    return ExecutedGraphChatOnceResult(
        content=full_response,
        citations=list(citations_data or []),
        metrics=metrics_data,
        structured_data=structured_data,
    )


async def execute_langchain_chat_once(
    *,
    engine: Any,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
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
) -> ExecutedGraphChatOnceResult:
    citations_data: list[Any] = []
    full_response_parts: list[str] = []
    done_data: dict[str, Any] = {}

    async for event in engine.stream_chat(
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
        etype = event.get("type")
        if etype == "citations":
            citations_data = event.get("data") or []
        elif etype == "token":
            data = event.get("data") or {}
            full_response_parts.append(str(data.get("content") or ""))
        elif etype == "done":
            done_data = event.get("data") or {}

    full_response = "".join(full_response_parts) if full_response_parts else ""
    metrics_data = dict(done_data.get("metrics") or {}) if isinstance(done_data, dict) else {}
    structured_data = done_data.get("structured_data") if isinstance(done_data, dict) else None

    return ExecutedGraphChatOnceResult(
        content=full_response,
        citations=list(citations_data or []),
        metrics=metrics_data,
        structured_data=structured_data,
    )
