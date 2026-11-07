from typing import Any, NotRequired, TypedDict

from app.core.model_execution import reject_retired_model_provider, reject_retired_retrieval_profile


class _ProfileOptions(TypedDict):
    retrieval_profile: str | None
    top_k: int
    score_threshold: float
    retrieval_mode: str | None
    enable_reranker: bool | None
    reranker_provider: str | None
    reranker_top_n: int | None
    enable_weight_rerank: bool | None
    retrieval_contract_mode: str | None
    visible_evidence_only: bool | None
    enable_hierarchy_recall: NotRequired[bool]
    hierarchy_family_collapse: NotRequired[bool]
    hierarchy_family_aggregation: NotRequired[str]
    hierarchy_tree_dedup: NotRequired[bool]
    hierarchy_parent_depth: NotRequired[int]
    hierarchy_sibling_window: NotRequired[int]
    hierarchy_overfetch_factor: NotRequired[int]
    context_neighbor_window: NotRequired[int]
    context_neighbor_max_added: NotRequired[int]
    context_neighbor_score_driven: NotRequired[bool]
    context_neighbor_high_threshold: NotRequired[float]
    context_neighbor_mid_threshold: NotRequired[float]
    context_neighbor_high_span: NotRequired[int]
    context_neighbor_mid_span: NotRequired[int]
    sparse_retrieval_enabled: NotRequired[bool]
    sparse_retrieval_provider: NotRequired[str]


FAST_RETRIEVAL_PROFILE = "fast"
BALANCED_RETRIEVAL_PROFILE = "balanced"
QUALITY_RETRIEVAL_PROFILE = "quality"
PRODUCTION_RETRIEVAL_PROFILE = "hybrid_ce"
STRICT_GROUNDED_RETRIEVAL_PROFILE = "grounded_strict"
LONG_CONTEXT_RETRIEVAL_PROFILE = "long_context"
EXPANDED_RETRIEVAL_PROFILE = "expanded"
HIERARCHY_PRODUCTION_RETRIEVAL_PROFILE = "hierarchy_hybrid_ce"
HIERARCHY_STRICT_GROUNDED_RETRIEVAL_PROFILE = "hierarchy_grounded_strict"
HIERARCHY_EXPANDED_RECALL_RETRIEVAL_PROFILE = "hierarchy_recall20_expand"
RECALL_FIRST_RETRIEVAL_PROFILES = {
    QUALITY_RETRIEVAL_PROFILE,
    "recall20",
    "recall50",
    "coverage80",
    EXPANDED_RETRIEVAL_PROFILE,
    "hierarchy_recall20",
    HIERARCHY_EXPANDED_RECALL_RETRIEVAL_PROFILE,
}
SUPPORTED_RETRIEVAL_PROFILES = set(RECALL_FIRST_RETRIEVAL_PROFILES) | {
    FAST_RETRIEVAL_PROFILE,
    BALANCED_RETRIEVAL_PROFILE,
    QUALITY_RETRIEVAL_PROFILE,
    PRODUCTION_RETRIEVAL_PROFILE,
    STRICT_GROUNDED_RETRIEVAL_PROFILE,
    LONG_CONTEXT_RETRIEVAL_PROFILE,
    HIERARCHY_PRODUCTION_RETRIEVAL_PROFILE,
    HIERARCHY_STRICT_GROUNDED_RETRIEVAL_PROFILE,
}


def normalize_retrieval_profile(profile: Any) -> str | None:
    value = str(profile or "").strip().lower()
    reject_retired_retrieval_profile(value)
    if not value:
        return None
    return value


def is_recall_first_profile(profile: Any) -> bool:
    normalized = normalize_retrieval_profile(profile)
    return bool(normalized in RECALL_FIRST_RETRIEVAL_PROFILES)


def _apply_hierarchy_overlay_defaults(out: _ProfileOptions) -> _ProfileOptions:
    out["enable_hierarchy_recall"] = True
    out["hierarchy_family_collapse"] = True
    out["hierarchy_family_aggregation"] = "combined"
    out["hierarchy_tree_dedup"] = True
    out["hierarchy_parent_depth"] = 0
    out["hierarchy_sibling_window"] = 0
    out["hierarchy_overfetch_factor"] = 4
    return out


def _apply_default_expansion_defaults(out: _ProfileOptions) -> _ProfileOptions:
    out["top_k"] = max(out["top_k"], 20)
    out["score_threshold"] = 0.0
    out = _apply_hierarchy_overlay_defaults(out)
    out["hierarchy_parent_depth"] = 1
    out["hierarchy_sibling_window"] = 1
    out["context_neighbor_window"] = 2
    out["context_neighbor_max_added"] = 24
    out["context_neighbor_score_driven"] = True
    out["context_neighbor_high_threshold"] = 0.7
    out["context_neighbor_mid_threshold"] = 0.4
    out["context_neighbor_high_span"] = 2
    out["context_neighbor_mid_span"] = 1
    return out


def _configured_reranker_provider(out: _ProfileOptions) -> str:
    """Require an explicit supported reranker for profiles that enable reranking."""
    provider = out["reranker_provider"]
    reject_retired_model_provider(provider, capability="reranker")
    if provider and provider not in {"none", "off", "false", "0"}:
        return provider
    raise ValueError("This retrieval profile requires an explicitly configured reranker provider")


def _normalize_profile_option(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized else None


def _initial_profile_options(
    *,
    normalized: str | None,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str | None,
    enable_reranker: bool | None,
    reranker_provider: str | None,
    reranker_top_n: int | None,
    enable_weight_rerank: bool | None,
    retrieval_contract_mode: str | None,
    visible_evidence_only: bool | None,
) -> _ProfileOptions:
    return {
        "retrieval_profile": normalized,
        "top_k": int(top_k or 0),
        "score_threshold": float(score_threshold or 0.0),
        "retrieval_mode": _normalize_profile_option(retrieval_mode),
        "enable_reranker": None if enable_reranker is None else bool(enable_reranker),
        "reranker_provider": _normalize_profile_option(reranker_provider),
        "reranker_top_n": None if reranker_top_n is None else int(reranker_top_n or 0),
        "enable_weight_rerank": None if enable_weight_rerank is None else bool(enable_weight_rerank),
        "retrieval_contract_mode": _normalize_profile_option(retrieval_contract_mode),
        "visible_evidence_only": None if visible_evidence_only is None else bool(visible_evidence_only),
    }


def _apply_fast_profile(out: _ProfileOptions) -> _ProfileOptions:
    out.update(
        retrieval_mode="vector",
        top_k=10,
        score_threshold=0.0,
        enable_reranker=False,
        reranker_provider="none",
        reranker_top_n=1,
        enable_weight_rerank=False,
        sparse_retrieval_enabled=False,
    )
    return out


def _apply_balanced_profile(out: _ProfileOptions) -> _ProfileOptions:
    out.update(retrieval_mode="hybrid", top_k=10, score_threshold=0.0, enable_weight_rerank=False)
    if out["enable_reranker"] is False:
        out.update(reranker_provider="none", reranker_top_n=1)
        return out
    out.update(
        enable_reranker=True,
        reranker_provider=_configured_reranker_provider(out),
        reranker_top_n=20,
    )
    return out


def _apply_quality_profile(out: _ProfileOptions) -> _ProfileOptions:
    _apply_default_expansion_defaults(out)
    out.update(retrieval_mode="hybrid", enable_weight_rerank=False)
    if out["enable_reranker"] is False:
        out.update(reranker_provider="none", reranker_top_n=1)
        return out
    out.update(
        enable_reranker=True,
        reranker_provider=_configured_reranker_provider(out),
        reranker_top_n=max(40, out["top_k"]),
    )
    return out


def _apply_recall_profile(out: _ProfileOptions, *, minimum_top_k: int) -> _ProfileOptions:
    out["top_k"] = max(out["top_k"], minimum_top_k)
    out["score_threshold"] = 0.0
    return out


def _apply_hierarchy_recall_profile(out: _ProfileOptions) -> _ProfileOptions:
    _apply_recall_profile(out, minimum_top_k=20)
    return _apply_hierarchy_overlay_defaults(out)


def _apply_production_profile(out: _ProfileOptions, *, hierarchy: bool = False) -> _ProfileOptions:
    out.update(
        retrieval_mode="hybrid",
        top_k=max(out["top_k"], 20),
        score_threshold=0.0,
        enable_weight_rerank=False,
    )
    if out["enable_reranker"] is False:
        out["reranker_provider"] = "none"
    else:
        out.update(
            enable_reranker=True,
            reranker_provider=_configured_reranker_provider(out),
            reranker_top_n=max((out["reranker_top_n"] or 0), out["top_k"], 20),
        )
    return _apply_hierarchy_overlay_defaults(out) if hierarchy else out


def _apply_hierarchy_production_profile(out: _ProfileOptions) -> _ProfileOptions:
    return _apply_production_profile(out, hierarchy=True)


def _apply_long_context_profile(out: _ProfileOptions) -> _ProfileOptions:
    out.update(
        retrieval_mode="hybrid",
        top_k=8,
        score_threshold=0.0,
        enable_reranker=True,
        reranker_provider="long_context",
        reranker_top_n=4,
        enable_weight_rerank=False,
    )
    return out


def _apply_strict_profile(out: _ProfileOptions, *, hierarchy: bool = False) -> _ProfileOptions:
    out.update(
        retrieval_mode="hybrid",
        top_k=max(out["top_k"], 20),
        score_threshold=0.0,
        enable_reranker=True,
        reranker_provider=_configured_reranker_provider(out),
        reranker_top_n=max((out["reranker_top_n"] or 0), out["top_k"], 20),
        enable_weight_rerank=False,
        retrieval_contract_mode="evidence_strict",
        visible_evidence_only=True,
    )
    return _apply_hierarchy_overlay_defaults(out) if hierarchy else out


def _apply_hierarchy_strict_profile(out: _ProfileOptions) -> _ProfileOptions:
    return _apply_strict_profile(out, hierarchy=True)


_RECALL_PROFILE_MINIMUMS = {"recall20": 20, "recall50": 50, "coverage80": 80}
_EXPANSION_PROFILES = {EXPANDED_RETRIEVAL_PROFILE, HIERARCHY_EXPANDED_RECALL_RETRIEVAL_PROFILE}
_PROFILE_APPLIERS = {
    FAST_RETRIEVAL_PROFILE: _apply_fast_profile,
    BALANCED_RETRIEVAL_PROFILE: _apply_balanced_profile,
    QUALITY_RETRIEVAL_PROFILE: _apply_quality_profile,
    PRODUCTION_RETRIEVAL_PROFILE: _apply_production_profile,
    LONG_CONTEXT_RETRIEVAL_PROFILE: _apply_long_context_profile,
    HIERARCHY_PRODUCTION_RETRIEVAL_PROFILE: _apply_hierarchy_production_profile,
    STRICT_GROUNDED_RETRIEVAL_PROFILE: _apply_strict_profile,
    HIERARCHY_STRICT_GROUNDED_RETRIEVAL_PROFILE: _apply_hierarchy_strict_profile,
}
_INVALID_PROFILE_MESSAGE = (
    "retrieval_profile must be one of: fast, balanced, quality, recall20, recall50, coverage80, expanded, "
    "sparse_splade, hybrid_ce, grounded_strict, long_context, hierarchy_recall20, hierarchy_recall20_expand, "
    "hierarchy_hybrid_ce, hierarchy_grounded_strict"
)


def apply_retrieval_profile_overrides(
    *,
    profile: Any,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str | None = None,
    enable_reranker: bool | None = None,
    reranker_provider: str | None = None,
    reranker_top_n: int | None = None,
    enable_weight_rerank: bool | None = None,
    retrieval_contract_mode: str | None = None,
    visible_evidence_only: bool | None = None,
) -> _ProfileOptions:
    normalized = normalize_retrieval_profile(profile)
    out = _initial_profile_options(
        normalized=normalized,
        top_k=top_k,
        score_threshold=score_threshold,
        retrieval_mode=retrieval_mode,
        enable_reranker=enable_reranker,
        reranker_provider=reranker_provider,
        reranker_top_n=reranker_top_n,
        enable_weight_rerank=enable_weight_rerank,
        retrieval_contract_mode=retrieval_contract_mode,
        visible_evidence_only=visible_evidence_only,
    )
    if normalized is None:
        return out
    if normalized not in SUPPORTED_RETRIEVAL_PROFILES:
        raise ValueError(_INVALID_PROFILE_MESSAGE)
    minimum_top_k = _RECALL_PROFILE_MINIMUMS.get(normalized)
    if minimum_top_k is not None:
        return _apply_recall_profile(out, minimum_top_k=minimum_top_k)
    if normalized == "hierarchy_recall20":
        return _apply_hierarchy_recall_profile(out)
    if normalized in _EXPANSION_PROFILES:
        return _apply_default_expansion_defaults(out)
    return _PROFILE_APPLIERS[normalized](out)


__all__ = [
    "FAST_RETRIEVAL_PROFILE",
    "BALANCED_RETRIEVAL_PROFILE",
    "QUALITY_RETRIEVAL_PROFILE",
    "PRODUCTION_RETRIEVAL_PROFILE",
    "STRICT_GROUNDED_RETRIEVAL_PROFILE",
    "LONG_CONTEXT_RETRIEVAL_PROFILE",
    "EXPANDED_RETRIEVAL_PROFILE",
    "HIERARCHY_PRODUCTION_RETRIEVAL_PROFILE",
    "HIERARCHY_STRICT_GROUNDED_RETRIEVAL_PROFILE",
    "HIERARCHY_EXPANDED_RECALL_RETRIEVAL_PROFILE",
    "RECALL_FIRST_RETRIEVAL_PROFILES",
    "SUPPORTED_RETRIEVAL_PROFILES",
    "apply_retrieval_profile_overrides",
    "is_recall_first_profile",
    "normalize_retrieval_profile",
]
