from __future__ import annotations

from typing import Any

PRODUCTION_RETRIEVAL_PROFILE = "hybrid_ce"
RECALL_FIRST_RETRIEVAL_PROFILES = {"recall20", "recall50", "coverage80"}
SUPPORTED_RETRIEVAL_PROFILES = set(RECALL_FIRST_RETRIEVAL_PROFILES) | {PRODUCTION_RETRIEVAL_PROFILE}


def normalize_retrieval_profile(profile: Any) -> str | None:
    value = str(profile or "").strip().lower()
    if not value:
        return None
    return value


def is_recall_first_profile(profile: Any) -> bool:
    normalized = normalize_retrieval_profile(profile)
    return bool(normalized in RECALL_FIRST_RETRIEVAL_PROFILES)


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
) -> dict[str, Any]:
    normalized = normalize_retrieval_profile(profile)

    out: dict[str, Any] = {
        "retrieval_profile": normalized,
        "top_k": int(top_k or 0),
        "score_threshold": float(score_threshold or 0.0),
        "retrieval_mode": str(retrieval_mode or "").strip().lower() or None,
        "enable_reranker": None if enable_reranker is None else bool(enable_reranker),
        "reranker_provider": str(reranker_provider or "").strip().lower() or None,
        "reranker_top_n": None if reranker_top_n is None else int(reranker_top_n or 0),
        "enable_weight_rerank": None if enable_weight_rerank is None else bool(enable_weight_rerank),
    }

    if normalized is None:
        out["retrieval_profile"] = None
        return out

    if normalized == "recall20":
        out["top_k"] = max(int(out["top_k"] or 0), 20)
        out["score_threshold"] = 0.0
        return out

    if normalized == "recall50":
        out["top_k"] = max(int(out["top_k"] or 0), 50)
        out["score_threshold"] = 0.0
        return out

    if normalized == "coverage80":
        out["top_k"] = max(int(out["top_k"] or 0), 80)
        out["score_threshold"] = 0.0
        return out

    if normalized == PRODUCTION_RETRIEVAL_PROFILE:
        out["retrieval_mode"] = "hybrid"
        out["top_k"] = max(int(out["top_k"] or 0), 20)
        out["score_threshold"] = 0.0
        out["enable_reranker"] = True
        out["reranker_provider"] = "cross_encoder"
        out["reranker_top_n"] = max(int(out["reranker_top_n"] or 0), int(out["top_k"] or 0), 20)
        out["enable_weight_rerank"] = False
        return out

    raise ValueError("retrieval_profile must be one of: recall20, recall50, coverage80, hybrid_ce")


__all__ = [
    "PRODUCTION_RETRIEVAL_PROFILE",
    "RECALL_FIRST_RETRIEVAL_PROFILES",
    "SUPPORTED_RETRIEVAL_PROFILES",
    "apply_retrieval_profile_overrides",
    "is_recall_first_profile",
    "normalize_retrieval_profile",
]
