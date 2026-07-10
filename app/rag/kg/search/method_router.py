
from typing import Any

from app.rag.kg.search.query_mode import classify_kg_query_mode
from app.rag.policy.complexity_classifier import classify_query_complexity


def route_kg_search_method(query: str) -> dict[str, Any]:
    complexity = classify_query_complexity(query)
    kg_mode = classify_kg_query_mode(query=query)

    method = "hybrid"
    reason_codes: list[str] = []
    if str(kg_mode.get("mode") or "") == "drift":
        method = "drift_search"
        reason_codes.append("kg_mode_drift")
    elif str(complexity.get("label") or "") == "structured":
        method = "pprank"
        reason_codes.append("structured_pprank")
    elif str(complexity.get("label") or "") == "multi_hop":
        method = "hybrid"
        reason_codes.append("multi_hop_hybrid")
    else:
        reason_codes.append("default_hybrid")

    return {
        "method": method,
        "complexity": complexity,
        "kg_mode": kg_mode,
        "reason_codes": reason_codes,
    }


__all__ = ["route_kg_search_method"]
