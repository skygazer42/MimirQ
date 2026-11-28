"""
RAG configuration projection and dataset defaults.

We treat dataset defaults as *fallbacks*:
- If a request explicitly provided a rag_config field, we keep it.
- Otherwise, apply the dataset's override (if any).
"""

from collections.abc import Iterable
from typing import Any

from app.api.schemas.conversations import ChatRAGConfig
from app.api.schemas.datasets import DatasetRAGDefaults
from app.infrastructure.model_policy import reject_retired_retrieval_options
from app.services.retrieval.template_apply import apply_rag_config_patch


def retrieval_options(rag_config: ChatRAGConfig) -> dict[str, Any]:
    """Project the shared options accepted by graph and chat retrieval entrypoints."""
    return {
        "top_k": rag_config.top_k,
        "score_threshold": rag_config.score_threshold,
        "retrieval_mode": rag_config.retrieval_mode,
        "retrieval_profile": rag_config.retrieval_profile,
        "intent_router": rag_config.intent_router,
        "intent_router_policy": rag_config.intent_router_policy,
        "enable_query_alias_expansion": rag_config.enable_query_alias_expansion,
        "query_aliases": rag_config.query_aliases,
        "query_alias_max_queries": rag_config.query_alias_max_queries,
        "enable_multi_query": rag_config.enable_multi_query,
        "multi_query_count": rag_config.multi_query_count,
        "multi_query_temperature": rag_config.multi_query_temperature,
        "multi_query_max_chars": rag_config.multi_query_max_chars,
        "enable_hyde": rag_config.enable_hyde,
        "lexical_db_hybrid_fallback_only": rag_config.lexical_db_hybrid_fallback_only,
        "lexical_db_hybrid_metadata_exact_fallback_enabled": rag_config.lexical_db_hybrid_metadata_exact_fallback_enabled,
        "metadata_exact_db_fallback_enabled": rag_config.metadata_exact_db_fallback_enabled,
        "enable_hierarchy_recall": rag_config.enable_hierarchy_recall,
        "hierarchy_family_collapse": rag_config.hierarchy_family_collapse,
        "hierarchy_family_aggregation": rag_config.hierarchy_family_aggregation,
        "hierarchy_tree_dedup": rag_config.hierarchy_tree_dedup,
        "hierarchy_parent_depth": rag_config.hierarchy_parent_depth,
        "hierarchy_sibling_window": rag_config.hierarchy_sibling_window,
        "hierarchy_overfetch_factor": rag_config.hierarchy_overfetch_factor,
        "alpha": rag_config.alpha,
        "fusion_strategy": rag_config.fusion_strategy,
        "fusion_budgets": rag_config.fusion_budgets,
        "fusion_min_scores": rag_config.fusion_min_scores,
        "fusion_weights": rag_config.fusion_weights,
        "enable_weight_rerank": rag_config.enable_weight_rerank,
        "vector_weight": rag_config.vector_weight,
        "keyword_weight": rag_config.keyword_weight,
        "mmr_lambda": rag_config.mmr_lambda,
        "enable_reranker": rag_config.enable_reranker,
        "reranker_provider": rag_config.reranker_provider,
        "reranker_top_n": rag_config.reranker_top_n,
        "visible_evidence_only": rag_config.visible_evidence_only,
    }


def merge_rag_config_with_dataset_defaults(
    *,
    rag_config: ChatRAGConfig,
    request_fields_set: Iterable[str] | None,
    raw_dataset_defaults: Any,
) -> tuple[ChatRAGConfig, list[str]]:
    """
    Merge dataset-level defaults into an existing ChatRAGConfig.

    Args:
        rag_config: The request RAG config (already validated).
        request_fields_set: Fields explicitly provided by the request body. If rag_config was omitted
            entirely, pass an empty iterable.
        raw_dataset_defaults: The dataset metadata value (dict) or DatasetRAGDefaults or None.

    Returns:
        (effective_rag_config, applied_field_names)
    """
    provided = set(request_fields_set or [])

    if raw_dataset_defaults is None:
        return rag_config, []

    if isinstance(raw_dataset_defaults, DatasetRAGDefaults):
        defaults = raw_dataset_defaults
    elif isinstance(raw_dataset_defaults, dict):
        reject_retired_retrieval_options(raw_dataset_defaults)
        defaults = DatasetRAGDefaults(
            **{key: value for key, value in raw_dataset_defaults.items() if key not in provided}
        )
    else:
        raise TypeError("dataset RAG defaults must be an object")

    overrides = defaults.model_dump(exclude_none=True)
    contract_mode = overrides.get("retrieval_contract_mode")
    if (
        contract_mode is not None
        and contract_mode.strip().lower() == "evidence_strict"
        and "visible_evidence_only" not in overrides
    ):
        overrides["visible_evidence_only"] = True
    if not overrides:
        return rag_config, []

    return apply_rag_config_patch(rag_config=rag_config, patch=overrides, request_fields_set=provided)
