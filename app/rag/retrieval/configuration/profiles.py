"""Retrieval modes, profile presets and their configuration overlays."""

from typing import NotRequired, TypedDict

from app.infrastructure.model_policy import (
    RetiredModelProviderError,
    reject_retired_provider,
    reject_retired_retrieval_profile,
)

_VALID_RETRIEVAL_MODES = {"hybrid", "vector", "keyword", "mmr", "auto"}


_RETRIEVAL_MODE_ALIASES = {
    "fulltext": "keyword",
    "bm25": "keyword",
    "lexical": "keyword",
    "dense": "vector",
    "semantic": "vector",
}


def normalize_retrieval_mode(mode: str | None) -> str:
    """Normalize supported modes and legacy aliases, defaulting to hybrid."""
    raw = (mode or "").strip().lower()
    if not raw:
        return "hybrid"
    if raw == "sparse":
        raise RetiredModelProviderError("The sparse retrieval mode has been retired")
    mapped = _RETRIEVAL_MODE_ALIASES.get(raw, raw)
    if mapped in _VALID_RETRIEVAL_MODES:
        return mapped
    return "hybrid"


class RetrievalProfileOptions(TypedDict):
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


def normalize_retrieval_profile(profile: str | None) -> str | None:
    value = _normalize_profile_option(profile)
    reject_retired_retrieval_profile(value)
    return value


def is_recall_first_profile(profile: str | None) -> bool:
    normalized = normalize_retrieval_profile(profile)
    return normalized in RECALL_FIRST_RETRIEVAL_PROFILES


def _apply_hierarchy_overlay_defaults(out: RetrievalProfileOptions) -> RetrievalProfileOptions:
    out["enable_hierarchy_recall"] = True
    out["hierarchy_family_collapse"] = True
    out["hierarchy_family_aggregation"] = "combined"
    out["hierarchy_tree_dedup"] = True
    out["hierarchy_parent_depth"] = 0
    out["hierarchy_sibling_window"] = 0
    out["hierarchy_overfetch_factor"] = 4
    return out


def _apply_default_expansion_defaults(out: RetrievalProfileOptions) -> RetrievalProfileOptions:
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


def _configured_reranker_provider(out: RetrievalProfileOptions) -> str:
    """Require an explicit supported reranker for profiles that enable reranking."""
    provider = out["reranker_provider"]
    reject_retired_provider(provider, capability="reranker")
    if provider and provider not in {"none", "off", "false", "0"}:
        return provider
    raise ValueError("This retrieval profile requires an explicitly configured reranker provider")


def _normalize_profile_option(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized


_RECALL_PROFILE_MINIMUMS = {"recall20": 20, "recall50": 50, "coverage80": 80}


_EXPANSION_PROFILES = {EXPANDED_RETRIEVAL_PROFILE, HIERARCHY_EXPANDED_RECALL_RETRIEVAL_PROFILE}


_INVALID_PROFILE_MESSAGE = (
    "retrieval_profile must be one of: fast, balanced, quality, recall20, recall50, coverage80, expanded, "
    "hybrid_ce, grounded_strict, long_context, hierarchy_recall20, hierarchy_recall20_expand, "
    "hierarchy_hybrid_ce, hierarchy_grounded_strict"
)


def apply_retrieval_profile_overrides(
    *,
    profile: str | None,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str | None = None,
    enable_reranker: bool | None = None,
    reranker_provider: str | None = None,
    reranker_top_n: int | None = None,
    enable_weight_rerank: bool | None = None,
    retrieval_contract_mode: str | None = None,
    visible_evidence_only: bool | None = None,
) -> RetrievalProfileOptions:
    normalized = normalize_retrieval_profile(profile)
    out: RetrievalProfileOptions = {
        "retrieval_profile": normalized,
        "top_k": int(top_k),
        "score_threshold": float(score_threshold),
        "retrieval_mode": _normalize_profile_option(retrieval_mode),
        "enable_reranker": enable_reranker,
        "reranker_provider": _normalize_profile_option(reranker_provider),
        "reranker_top_n": reranker_top_n,
        "enable_weight_rerank": enable_weight_rerank,
        "retrieval_contract_mode": _normalize_profile_option(retrieval_contract_mode),
        "visible_evidence_only": visible_evidence_only,
    }
    if normalized is None:
        return out
    if normalized not in SUPPORTED_RETRIEVAL_PROFILES:
        raise ValueError(_INVALID_PROFILE_MESSAGE)
    minimum_top_k = _RECALL_PROFILE_MINIMUMS.get(normalized)
    if minimum_top_k is not None:
        out["top_k"] = max(out["top_k"], minimum_top_k)
        out["score_threshold"] = 0.0
        return out
    if normalized == "hierarchy_recall20":
        out["top_k"] = max(out["top_k"], 20)
        out["score_threshold"] = 0.0
        return _apply_hierarchy_overlay_defaults(out)
    if normalized in _EXPANSION_PROFILES:
        return _apply_default_expansion_defaults(out)
    if normalized == FAST_RETRIEVAL_PROFILE:
        out.update(
            retrieval_mode="vector",
            top_k=10,
            score_threshold=0.0,
            enable_reranker=False,
            reranker_provider="none",
            reranker_top_n=1,
            enable_weight_rerank=False,
        )
        return out
    if normalized == LONG_CONTEXT_RETRIEVAL_PROFILE:
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
    if normalized in {BALANCED_RETRIEVAL_PROFILE, QUALITY_RETRIEVAL_PROFILE}:
        if normalized == QUALITY_RETRIEVAL_PROFILE:
            _apply_default_expansion_defaults(out)
            out.update(retrieval_mode="hybrid", enable_weight_rerank=False)
            rerank_top_n = max(40, out["top_k"])
        else:
            out.update(retrieval_mode="hybrid", top_k=10, score_threshold=0.0, enable_weight_rerank=False)
            rerank_top_n = 20
        if out["enable_reranker"] is False:
            out.update(reranker_provider="none", reranker_top_n=1)
        else:
            out.update(
                enable_reranker=True,
                reranker_provider=_configured_reranker_provider(out),
                reranker_top_n=rerank_top_n,
            )
        return out

    strict = normalized in {STRICT_GROUNDED_RETRIEVAL_PROFILE, HIERARCHY_STRICT_GROUNDED_RETRIEVAL_PROFILE}
    out.update(
        retrieval_mode="hybrid",
        top_k=max(out["top_k"], 20),
        score_threshold=0.0,
        enable_weight_rerank=False,
    )
    if out["enable_reranker"] is False and not strict:
        out["reranker_provider"] = "none"
    else:
        out.update(
            enable_reranker=True,
            reranker_provider=_configured_reranker_provider(out),
            reranker_top_n=max((out["reranker_top_n"] or 0), out["top_k"], 20),
        )
    if strict:
        out.update(retrieval_contract_mode="evidence_strict", visible_evidence_only=True)
    if normalized in {HIERARCHY_PRODUCTION_RETRIEVAL_PROFILE, HIERARCHY_STRICT_GROUNDED_RETRIEVAL_PROFILE}:
        _apply_hierarchy_overlay_defaults(out)
    return out
