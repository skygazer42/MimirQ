from __future__ import annotations

from typing import Any

from app.rag.core.retrieval_profiles import PRODUCTION_RETRIEVAL_PROFILE
from app.rag.policy.complexity_classifier import classify_query_complexity


def route_system_query(query: str) -> dict[str, Any]:
    classified = classify_query_complexity(query)
    label = classified["label"]
    if label == "structured":
        route = "kg"
        retrieval_profile = None
    elif label == "multi_hop":
        route = "hybrid"
        retrieval_profile = PRODUCTION_RETRIEVAL_PROFILE
    else:
        route = "retrieval"
        retrieval_profile = PRODUCTION_RETRIEVAL_PROFILE
    return {
        "route": route,
        "retrieval_profile": retrieval_profile,
        "complexity": classified,
    }


__all__ = ["route_system_query"]
