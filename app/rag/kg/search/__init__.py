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
    "KGSearcher",
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

    if name == "KGSearcher":
        from app.rag.kg.search.searcher import KGSearcher

        return KGSearcher
    if name in {"RecallSearcher", "RecallResult"}:
        from app.rag.kg.search.recall import RecallResult, RecallSearcher

        return {"RecallSearcher": RecallSearcher, "RecallResult": RecallResult}[name]
    if name in {"ExpandSearcher", "ExpandResult"}:
        from app.rag.kg.search.expand import ExpandResult, ExpandSearcher

        return {"ExpandSearcher": ExpandSearcher, "ExpandResult": ExpandResult}[name]
    if name == "Tracker":
        from app.rag.kg.search.tracker import Tracker

        return Tracker

    raise AttributeError(f"module 'app.kg.search' has no attribute {name!r}")
