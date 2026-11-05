"""KG search module."""

from typing import Any

__all__ = [
    "RerankStrategy",
    "ReturnType",
    "RecallConfig",
    "ExpandConfig",
    "RerankConfig",
    "SearchConfig",
    "SearchBaseConfig",
    "search_kg",
    "recall_kg",
    "RecallResult",
    "expand_kg",
    "ExpandResult",
    "Tracker",
    "build_subqrag_plan",
    "classify_kg_query_mode",
    "normalize_kg_query_mode",
    "build_mode_aware_recall_overrides",
]


def __getattr__(name: str) -> Any:  # pragma: no cover
    # Config exports
    if name in {
        "RerankStrategy",
        "ReturnType",
        "RecallConfig",
        "ExpandConfig",
        "RerankConfig",
        "SearchConfig",
        "SearchBaseConfig",
    }:
        from app.rag.kg.search.config import (
            ExpandConfig,
            RecallConfig,
            RerankConfig,
            RerankStrategy,
            ReturnType,
            SearchBaseConfig,
            SearchConfig,
        )

        return {
            "RerankStrategy": RerankStrategy,
            "ReturnType": ReturnType,
            "RecallConfig": RecallConfig,
            "ExpandConfig": ExpandConfig,
            "RerankConfig": RerankConfig,
            "SearchConfig": SearchConfig,
            "SearchBaseConfig": SearchBaseConfig,
        }[name]

    if name == "search_kg":
        from app.rag.kg.search.searcher import search

        return search
    if name in {"recall_kg", "RecallResult"}:
        from app.rag.kg.search.recall import RecallResult, recall

        return {"recall_kg": recall, "RecallResult": RecallResult}[name]
    if name in {"expand_kg", "ExpandResult"}:
        from app.rag.kg.search.expand import ExpandResult, expand

        return {"expand_kg": expand, "ExpandResult": ExpandResult}[name]
    if name == "Tracker":
        from app.rag.kg.search.tracker import Tracker

        return Tracker
    if name == "build_subqrag_plan":
        from app.rag.kg.search.subqrag import build_subqrag_plan

        return build_subqrag_plan
    if name in {"classify_kg_query_mode", "normalize_kg_query_mode", "build_mode_aware_recall_overrides"}:
        from app.rag.kg.search.query_mode import (
            build_mode_aware_recall_overrides,
            classify_kg_query_mode,
            normalize_kg_query_mode,
        )

        return {
            "classify_kg_query_mode": classify_kg_query_mode,
            "normalize_kg_query_mode": normalize_kg_query_mode,
            "build_mode_aware_recall_overrides": build_mode_aware_recall_overrides,
        }[name]

    raise AttributeError(f"module 'app.kg.search' has no attribute {name!r}")
