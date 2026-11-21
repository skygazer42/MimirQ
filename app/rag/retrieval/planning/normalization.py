"""Pure query-contract normalization helpers for retrieval orchestration."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.query.routing import guess_retrieval_mode
from app.rag.retrieval.configuration.contract import RetrievalContractPolicy, resolve_retrieval_contract_policy
from app.rag.retrieval.configuration.profiles import (
    RetrievalProfileOptions,
    apply_retrieval_profile_overrides,
    is_recall_first_profile,
    normalize_retrieval_mode,
)


@dataclass(frozen=True)
class QueryContractDefaults:
    retrieval_top_k: int
    similarity_threshold: float
    enable_reranker: bool
    reranker_provider: str
    reranker_top_n: int
    retrieval_contract_mode: str
    hard_fallback_enabled_setting: bool
    hard_fallback_mode_setting: str
    hard_fallback_top_k_setting: int
    visible_evidence_only_setting: bool
    evidence_span_strict_setting: bool
    retrieval_fusion_strategy: str
    retrieval_mmr_lambda: float


@dataclass(frozen=True)
class HierarchyContractSettings:
    enabled: bool
    family_collapse: bool
    family_aggregation: str
    tree_dedup: bool
    parent_depth: int
    sibling_window: int
    overfetch_factor: int


@dataclass(frozen=True)
class QueryContractNormalizationInput:
    state: Mapping[str, Any]
    query_for_retrieval: str
    hierarchy: HierarchyContractSettings
    defaults: QueryContractDefaults


@dataclass(frozen=True)
class QueryContractNormalizationOutput:
    request_retrieval_mode: str
    retrieval_mode_routed: bool
    profile_applied: RetrievalProfileOptions
    profile_norm: str | None
    hierarchy: HierarchyContractSettings
    retriever_update: dict[str, Any]
    state_updates: dict[str, Any]
    retrieval_contract_policy: RetrievalContractPolicy
    retrieval_contract_mode: str
    contract_deterministic_recall: bool


def _requested_top_k(state: Mapping[str, Any], defaults: QueryContractDefaults) -> int:
    return int(state.get("top_k", defaults.retrieval_top_k) or defaults.retrieval_top_k)


def _requested_score_threshold(state: Mapping[str, Any], defaults: QueryContractDefaults) -> float:
    raw = state.get("score_threshold", defaults.similarity_threshold)
    if raw is None:
        return float(defaults.similarity_threshold)
    return float(raw)


def _resolve_request_retrieval_mode(*, state: Mapping[str, Any], query_for_retrieval: str) -> tuple[str, bool]:
    effective_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    request_retrieval_mode = normalize_retrieval_mode(effective_retrieval_mode)
    if request_retrieval_mode == "auto":
        return guess_retrieval_mode(query_for_retrieval), True
    return request_retrieval_mode, False


def _apply_hierarchy_profile_overrides(
    hierarchy: HierarchyContractSettings,
    profile_applied: RetrievalProfileOptions,
) -> HierarchyContractSettings:
    fields = (
        ("enable_hierarchy_recall", "enabled"),
        ("hierarchy_family_collapse", "family_collapse"),
        ("hierarchy_family_aggregation", "family_aggregation"),
        ("hierarchy_tree_dedup", "tree_dedup"),
        ("hierarchy_parent_depth", "parent_depth"),
        ("hierarchy_sibling_window", "sibling_window"),
        ("hierarchy_overfetch_factor", "overfetch_factor"),
    )
    updates = {field: profile_applied[key] for key, field in fields if key in profile_applied}
    if not updates:
        return hierarchy
    return replace(hierarchy, **updates)


def _state_updates_from_profile(profile_applied: RetrievalProfileOptions) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if profile_applied["retrieval_contract_mode"] is not None:
        updates["retrieval_contract_mode"] = profile_applied["retrieval_contract_mode"]
    if profile_applied["visible_evidence_only"] is not None:
        updates["visible_evidence_only"] = profile_applied["visible_evidence_only"]
    return updates


def normalize_query_contract(payload: QueryContractNormalizationInput) -> QueryContractNormalizationOutput:
    state = payload.state
    request_retrieval_mode, retrieval_mode_routed = _resolve_request_retrieval_mode(
        state=state,
        query_for_retrieval=payload.query_for_retrieval,
    )

    profile_applied = apply_retrieval_profile_overrides(
        profile=state.get("retrieval_profile"),
        top_k=_requested_top_k(state, payload.defaults),
        score_threshold=_requested_score_threshold(state, payload.defaults),
        retrieval_mode=request_retrieval_mode,
        enable_reranker=bool(state.get("enable_reranker", payload.defaults.enable_reranker)),
        reranker_provider=state.get("reranker_provider", payload.defaults.reranker_provider),
        reranker_top_n=int(
            state.get("reranker_top_n", payload.defaults.reranker_top_n) or payload.defaults.reranker_top_n
        ),
        enable_weight_rerank=bool(state.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            state.get("retrieval_contract_mode")
            if state.get("retrieval_contract_mode") is not None
            else payload.defaults.retrieval_contract_mode
        ),
        visible_evidence_only=(
            bool(state.get("visible_evidence_only")) if state.get("visible_evidence_only") is not None else None
        ),
    )
    profile_norm = profile_applied["retrieval_profile"]

    hierarchy = _apply_hierarchy_profile_overrides(payload.hierarchy, profile_applied)
    retriever_update: dict[str, Any] = {
        "k": profile_applied["top_k"],
        "score_threshold": profile_applied["score_threshold"],
        "alpha": state.get("alpha", 0.6),
        "retrieval_profile": profile_norm,
        "context_neighbor_window": profile_applied.get("context_neighbor_window"),
        "context_neighbor_max_added": profile_applied.get("context_neighbor_max_added"),
        "context_neighbor_score_driven": profile_applied.get("context_neighbor_score_driven"),
        "context_neighbor_high_threshold": profile_applied.get("context_neighbor_high_threshold"),
        "context_neighbor_mid_threshold": profile_applied.get("context_neighbor_mid_threshold"),
        "context_neighbor_high_span": profile_applied.get("context_neighbor_high_span"),
        "context_neighbor_mid_span": profile_applied.get("context_neighbor_mid_span"),
        "fusion_strategy": state.get("fusion_strategy") or payload.defaults.retrieval_fusion_strategy,
        "fusion_budgets": state.get("fusion_budgets"),
        "fusion_min_scores": state.get("fusion_min_scores"),
        "fusion_weights": state.get("fusion_weights"),
        "retrieval_overfetch_multiplier": state.get("retrieval_overfetch_multiplier"),
        "retrieval_overfetch_max_k": state.get("retrieval_overfetch_max_k"),
        "retrieval_mode": profile_applied["retrieval_mode"] or request_retrieval_mode,
        "enable_weight_rerank": profile_applied["enable_weight_rerank"],
        "vector_weight": state.get("vector_weight", 0.6),
        "keyword_weight": state.get("keyword_weight", 0.4),
        "mmr_lambda": state.get("mmr_lambda", payload.defaults.retrieval_mmr_lambda),
        "enable_reranker": profile_applied["enable_reranker"],
        "reranker_provider": str(
            profile_applied["reranker_provider"]
            or state.get("reranker_provider", payload.defaults.reranker_provider)
            or payload.defaults.reranker_provider
        ),
        "reranker_top_n": profile_applied["reranker_top_n"],
        "tenant_id": state.get("tenant_id"),
        "account_id": state.get("account_id"),
        "dataset_id": state.get("dataset_id"),
        "dataset_ids": state.get("dataset_ids"),
        "document_ids": state.get("document_ids"),
        "metadata_filter": state.get("metadata_filter"),
        "lexical_db_hybrid_fallback_only": state.get("lexical_db_hybrid_fallback_only"),
        "lexical_db_hybrid_metadata_exact_fallback_enabled": state.get(
            "lexical_db_hybrid_metadata_exact_fallback_enabled"
        ),
        "metadata_exact_db_fallback_enabled": state.get("metadata_exact_db_fallback_enabled"),
        "enable_hierarchy_recall": hierarchy.enabled,
        "hierarchy_family_collapse": hierarchy.family_collapse,
        "hierarchy_overfetch_factor": hierarchy.overfetch_factor,
    }

    state_updates = _state_updates_from_profile(profile_applied)

    retrieval_contract_policy = resolve_retrieval_contract_policy(
        mode=(
            state_updates.get("retrieval_contract_mode")
            if state_updates.get("retrieval_contract_mode") is not None
            else (
                state.get("retrieval_contract_mode")
                if state.get("retrieval_contract_mode") is not None
                else payload.defaults.retrieval_contract_mode
            )
        ),
        requested_top_k=retriever_update["k"],
        hard_fallback_enabled_setting=payload.defaults.hard_fallback_enabled_setting,
        hard_fallback_mode_setting=payload.defaults.hard_fallback_mode_setting,
        hard_fallback_top_k_setting=payload.defaults.hard_fallback_top_k_setting,
        visible_evidence_only_setting=payload.defaults.visible_evidence_only_setting,
        evidence_span_strict_setting=payload.defaults.evidence_span_strict_setting,
    )
    retrieval_contract_mode = retrieval_contract_policy["mode"]
    contract_deterministic_recall = retrieval_contract_policy["deterministic_recall"]

    if is_recall_first_profile(profile_norm):
        retriever_update.update(
            {
                "dedup_enabled": False,
                "max_chunks_per_doc": 0,
                "max_chunks_per_page": 0,
                "min_distinct_docs": 0,
            }
        )

    return QueryContractNormalizationOutput(
        request_retrieval_mode=request_retrieval_mode,
        retrieval_mode_routed=retrieval_mode_routed,
        profile_applied=profile_applied,
        profile_norm=profile_norm,
        hierarchy=hierarchy,
        retriever_update=retriever_update,
        state_updates=state_updates,
        retrieval_contract_policy=retrieval_contract_policy,
        retrieval_contract_mode=retrieval_contract_mode,
        contract_deterministic_recall=contract_deterministic_recall,
    )
