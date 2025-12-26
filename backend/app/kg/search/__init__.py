"""SAG search module."""

from __future__ import annotations

from typing import Any

__all__ = [
    "RerankStrategy",
    "ReturnType",
    "RecallConfig",
    "ExpandConfig",
    "RerankConfig",
    "SearchConfig",
    "SearchBaseConfig",
    "SAGSearcher",
    "RecallSearcher",
    "RecallResult",
    "ExpandSearcher",
    "ExpandResult",
    "Tracker",
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
        from app.kg.search.config import (
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

    if name == "SAGSearcher":
        from app.kg.search.searcher import SAGSearcher

        return SAGSearcher
    if name in {"RecallSearcher", "RecallResult"}:
        from app.kg.search.recall import RecallResult, RecallSearcher

        return {"RecallSearcher": RecallSearcher, "RecallResult": RecallResult}[name]
    if name in {"ExpandSearcher", "ExpandResult"}:
        from app.kg.search.expand import ExpandResult, ExpandSearcher

        return {"ExpandSearcher": ExpandSearcher, "ExpandResult": ExpandResult}[name]
    if name == "Tracker":
        from app.kg.search.tracker import Tracker

        return Tracker

    raise AttributeError(f"module 'app.kg.search' has no attribute {name!r}")
