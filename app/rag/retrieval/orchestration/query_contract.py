"""Pure query-contract normalization helpers for retrieval orchestration."""

from dataclasses import dataclass
from typing import Any, Mapping

from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint
from app.rag.core.retrieval_profiles import (
    apply_retrieval_profile_overrides,
    is_recall_first_profile,
)
from app.rag.retrieval.contract import resolve_retrieval_contract_policy
from app.rag.retrieval.orchestration.text_helpers import guess_retrieval_mode, normalize_retrieval_mode


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
    requested_retrieval_mode: Any
    requested_retrieval_profile: Any
    sparse_enabled: bool
    sparse_provider: str
    hierarchy: HierarchyContractSettings
    defaults: QueryContractDefaults


@dataclass(frozen=True)
class QueryContractNormalizationOutput:
    request_retrieval_mode: str
    retrieval_mode_routed: bool
    profile_applied: dict[str, Any]
    profile_norm: str | None
    sparse_enabled: bool
    sparse_provider: str
    hierarchy: HierarchyContractSettings
    retriever_update: dict[str, Any]
    state_updates: dict[str, Any]
    retrieval_contract_policy: dict[str, Any]
    retrieval_contract_mode: str
    contract_deterministic_recall: bool


@dataclass(frozen=True)
class RetrievalConfigSnapshotInput:
    retrieval_config: Mapping[str, Any]
    rag_config_template: Any


@dataclass(frozen=True)
class RetrievalConfigSnapshotOutput:
    fingerprint: dict[str, Any]


def _requested_top_k(state: Mapping[str, Any], defaults: QueryContractDefaults) -> int:
    return int(state.get("top_k", defaults.retrieval_top_k) or defaults.retrieval_top_k or 5)


def _requested_score_threshold(state: Mapping[str, Any], defaults: QueryContractDefaults) -> float:
    raw = state.get("score_threshold", defaults.similarity_threshold)
    if raw is None:
        return float(defaults.similarity_threshold or 0.0)
    return float(raw)


def _resolve_request_retrieval_mode(*, state: Mapping[str, Any], query_for_retrieval: str) -> tuple[str, bool]:
    effective_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    request_retrieval_mode = normalize_retrieval_mode(effective_retrieval_mode)
    mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm == "auto":
        routed_mode = guess_retrieval_mode(query_for_retrieval)
        mode_norm = str(routed_mode or "hybrid").lower().strip()
        return (routed_mode if mode_norm in ("hybrid", "vector", "keyword", "mmr") else "hybrid"), True
    if mode_norm not in ("hybrid", "vector", "keyword", "mmr"):
        return "hybrid", False
    return str(request_retrieval_mode or "hybrid"), False


def _apply_hierarchy_profile_overrides(
    hierarchy: HierarchyContractSettings,
    profile_applied: Mapping[str, Any],
) -> HierarchyContractSettings:
    updates: dict[str, Any] = {}
    if profile_applied.get("enable_hierarchy_recall") is not None:
        updates["enabled"] = bool(profile_applied.get("enable_hierarchy_recall"))
    if profile_applied.get("hierarchy_family_collapse") is not None:
        updates["family_collapse"] = bool(profile_applied.get("hierarchy_family_collapse"))
    if profile_applied.get("hierarchy_family_aggregation") is not None:
        updates["family_aggregation"] = (
            str(profile_applied.get("hierarchy_family_aggregation") or "combined").strip().lower() or "combined"
        )
    if profile_applied.get("hierarchy_tree_dedup") is not None:
        updates["tree_dedup"] = bool(profile_applied.get("hierarchy_tree_dedup"))
    if profile_applied.get("hierarchy_parent_depth") is not None:
        updates["parent_depth"] = max(0, int(profile_applied.get("hierarchy_parent_depth") or 0))
    if profile_applied.get("hierarchy_sibling_window") is not None:
        updates["sibling_window"] = max(0, int(profile_applied.get("hierarchy_sibling_window") or 0))
    if profile_applied.get("hierarchy_overfetch_factor") is not None:
        updates["overfetch_factor"] = max(1, int(profile_applied.get("hierarchy_overfetch_factor") or 1))
    if not updates:
        return hierarchy

    return HierarchyContractSettings(
        enabled=bool(updates.get("enabled", hierarchy.enabled)),
        family_collapse=bool(updates.get("family_collapse", hierarchy.family_collapse)),
        family_aggregation=str(updates.get("family_aggregation", hierarchy.family_aggregation)),
        tree_dedup=bool(updates.get("tree_dedup", hierarchy.tree_dedup)),
        parent_depth=int(updates.get("parent_depth", hierarchy.parent_depth)),
        sibling_window=int(updates.get("sibling_window", hierarchy.sibling_window)),
        overfetch_factor=int(updates.get("overfetch_factor", hierarchy.overfetch_factor)),
    )


def _resolve_sparse_settings(
    *,
    sparse_enabled: bool,
    sparse_provider: str,
    profile_applied: Mapping[str, Any],
) -> tuple[bool, str]:
    enabled = sparse_enabled
    provider = sparse_provider
    if profile_applied.get("sparse_retrieval_enabled") is not None:
        enabled = bool(profile_applied.get("sparse_retrieval_enabled"))
    if profile_applied.get("sparse_retrieval_provider"):
        provider = str(profile_applied.get("sparse_retrieval_provider") or "")
    return enabled, provider


def _state_updates_from_profile(profile_applied: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if profile_applied.get("retrieval_contract_mode") is not None:
        updates["retrieval_contract_mode"] = profile_applied.get("retrieval_contract_mode")
    if profile_applied.get("visible_evidence_only") is not None:
        updates["visible_evidence_only"] = bool(profile_applied.get("visible_evidence_only"))
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
        reranker_provider=str(state.get("reranker_provider", payload.defaults.reranker_provider) or ""),
        reranker_top_n=int(state.get("reranker_top_n", payload.defaults.reranker_top_n) or payload.defaults.reranker_top_n or 20),
        enable_weight_rerank=bool(state.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            state.get("retrieval_contract_mode")
            if state.get("retrieval_contract_mode") is not None
            else payload.defaults.retrieval_contract_mode
        ),
        visible_evidence_only=(
            bool(state.get("visible_evidence_only"))
            if state.get("visible_evidence_only") is not None
            else None
        ),
    )
    profile_norm = str(profile_applied.get("retrieval_profile") or "").strip().lower() or None

    hierarchy = _apply_hierarchy_profile_overrides(payload.hierarchy, profile_applied)
    sparse_enabled, sparse_provider = _resolve_sparse_settings(
        sparse_enabled=payload.sparse_enabled,
        sparse_provider=payload.sparse_provider,
        profile_applied=profile_applied,
    )

    retriever_update: dict[str, Any] = {
        "k": int(profile_applied.get("top_k") or payload.defaults.retrieval_top_k),
        "score_threshold": float(profile_applied.get("score_threshold") or 0.0),
        "alpha": state.get("alpha", 0.6),
        "retrieval_profile": profile_norm or None,
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
        "retrieval_mode": str(profile_applied.get("retrieval_mode") or request_retrieval_mode),
        "enable_weight_rerank": (
            profile_applied.get("enable_weight_rerank")
            if profile_applied.get("enable_weight_rerank") is not None
            else state.get("enable_weight_rerank", True)
        ),
        "vector_weight": state.get("vector_weight", 0.6),
        "keyword_weight": state.get("keyword_weight", 0.4),
        "mmr_lambda": state.get("mmr_lambda", payload.defaults.retrieval_mmr_lambda),
        "enable_reranker": (
            profile_applied.get("enable_reranker")
            if profile_applied.get("enable_reranker") is not None
            else state.get("enable_reranker", payload.defaults.enable_reranker)
        ),
        "reranker_provider": str(
            profile_applied.get("reranker_provider")
            or state.get("reranker_provider", payload.defaults.reranker_provider)
            or payload.defaults.reranker_provider
        ),
        "reranker_top_n": int(
            profile_applied.get("reranker_top_n")
            if profile_applied.get("reranker_top_n") is not None
            else state.get("reranker_top_n", payload.defaults.reranker_top_n)
        ),
        "sparse_enabled": sparse_enabled,
        "sparse_provider": sparse_provider,
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
        "enable_hierarchy_recall": bool(hierarchy.enabled),
        "hierarchy_family_collapse": bool(hierarchy.family_collapse),
        "hierarchy_overfetch_factor": int(hierarchy.overfetch_factor),
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
        requested_top_k=int(retriever_update.get("k") or payload.defaults.retrieval_top_k or 5),
        hard_fallback_enabled_setting=bool(payload.defaults.hard_fallback_enabled_setting),
        hard_fallback_mode_setting=str(payload.defaults.hard_fallback_mode_setting or "keyword"),
        hard_fallback_top_k_setting=int(payload.defaults.hard_fallback_top_k_setting or 30),
        visible_evidence_only_setting=bool(payload.defaults.visible_evidence_only_setting),
        evidence_span_strict_setting=bool(payload.defaults.evidence_span_strict_setting),
    )
    retrieval_contract_mode = str(retrieval_contract_policy.get("mode") or "").strip().lower()
    contract_deterministic_recall = bool(retrieval_contract_policy.get("deterministic_recall"))

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
        request_retrieval_mode=str(request_retrieval_mode or "hybrid"),
        retrieval_mode_routed=bool(retrieval_mode_routed),
        profile_applied=dict(profile_applied),
        profile_norm=profile_norm,
        sparse_enabled=bool(sparse_enabled),
        sparse_provider=str(sparse_provider or ""),
        hierarchy=hierarchy,
        retriever_update=retriever_update,
        state_updates=state_updates,
        retrieval_contract_policy=dict(retrieval_contract_policy or {}),
        retrieval_contract_mode=retrieval_contract_mode,
        contract_deterministic_recall=bool(contract_deterministic_recall),
    )


def _normalize_rag_config_template(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None

    out: dict[str, Any] = {}
    key = str(raw.get("template_key") or "").strip()
    if key:
        out["template_key"] = key

    try:
        version = int(raw.get("version") or 0)
    except (TypeError, ValueError, AttributeError):
        version = 0
    if version > 0:
        out["version"] = version

    exp = str(raw.get("ab_experiment_key") or "").strip()
    if exp:
        out["ab_experiment_key"] = exp

    variant = str(raw.get("ab_variant") or "").strip()
    if variant:
        out["ab_variant"] = variant

    patch_hash = str(raw.get("patch_hash") or "").strip()
    if patch_hash:
        out["patch_hash"] = patch_hash

    return out or None


def build_retrieval_config_snapshot(payload: RetrievalConfigSnapshotInput) -> RetrievalConfigSnapshotOutput:
    config = dict(payload.retrieval_config or {})
    rag_config_template = _normalize_rag_config_template(payload.rag_config_template)
    if rag_config_template:
        config["rag_config_template"] = rag_config_template
    return RetrievalConfigSnapshotOutput(
        fingerprint=build_retrieval_config_fingerprint(config=config)
    )
