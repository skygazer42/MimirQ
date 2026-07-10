
from typing import Any

from app.rag.core.text import heuristic_decompose_query
from app.rag.kg.search.method_router import route_kg_search_method

_TRAILING_PUNCT = " \t\r\n,;:!?，。；：！？"


def build_subqrag_plan(query: str, *, max_subqueries: int = 3) -> dict[str, Any]:
    root_query = str(query or "").strip()
    pieces = heuristic_decompose_query(root_query, max_subquestions=max_subqueries)
    if len(pieces) == 1:
        piece_norm = str(pieces[0] or "").strip().rstrip(_TRAILING_PUNCT)
        root_norm = root_query.rstrip(_TRAILING_PUNCT)
        if piece_norm == root_norm:
            pieces = []
    if not pieces:
        pieces = [root_query] if root_query else []

    subqueries: list[dict[str, Any]] = []
    for index, subquery in enumerate(pieces, start=1):
        route = route_kg_search_method(subquery)
        subqueries.append(
            {
                "subquery_id": f"subq_{index}",
                "query": subquery,
                "method": route["method"],
                "reason_codes": list(route.get("reason_codes") or []),
                "complexity_label": str((route.get("complexity") or {}).get("label") or ""),
                "kg_mode": str((route.get("kg_mode") or {}).get("mode") or ""),
            }
        )

    return {
        "planner": "deterministic_subqrag_proxy",
        "query": root_query,
        "subqueries": subqueries,
        "requires_fusion": len(subqueries) > 1,
        "fusion_strategy": ("rank_then_union" if len(subqueries) > 1 else "single_route"),
    }


__all__ = ["build_subqrag_plan"]
