from __future__ import annotations

from typing import Any

from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

_SCHEMA = "mimirq.retrieval_config_tool.v1"


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = minimum
    return max(minimum, min(maximum, num))


def configure_retrieval(
    *,
    top_k: int,
    reranker_top_n: int,
    retrieval_profile: str | None = None,
    retrieval_mode: str | None = None,
    score_threshold: float = 0.0,
) -> dict[str, Any]:
    requested_top_k = _clamp_int(top_k, minimum=1, maximum=100)
    requested_reranker_top_n = _clamp_int(reranker_top_n, minimum=1, maximum=200)
    applied = apply_retrieval_profile_overrides(
        profile=retrieval_profile,
        top_k=requested_top_k,
        score_threshold=float(score_threshold or 0.0),
        retrieval_mode=retrieval_mode,
        reranker_top_n=requested_reranker_top_n,
    )

    return {
        "schema": _SCHEMA,
        "retrieval_profile": applied.get("retrieval_profile"),
        "retrieval_mode": applied.get("retrieval_mode"),
        "top_k": int(applied.get("top_k") or requested_top_k),
        "reranker_top_n": int(applied.get("reranker_top_n") or requested_reranker_top_n),
        "reranker_provider": applied.get("reranker_provider"),
        "enable_reranker": applied.get("enable_reranker"),
        "score_threshold": float(applied.get("score_threshold") or 0.0),
    }


__all__ = ["configure_retrieval"]
