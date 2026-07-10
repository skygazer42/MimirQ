
from collections.abc import Callable
from typing import Any

from app.rag.evaluation.runners.agentic_runner import run_agentic_route
from app.rag.evaluation.runners.hybrid_runner import run_hybrid_route
from app.rag.evaluation.runners.kg_runner import run_kg_route
from app.rag.evaluation.runners.retrieval_runner import run_retrieval_route

_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, Any]] | None] = {
    "retrieval": run_retrieval_route,
    "kg": run_kg_route,
    "hybrid": run_hybrid_route,
    "agentic": run_agentic_route,
}


def get_registered_route_ids() -> list[str]:
    return list(_REGISTRY.keys())


def get_runner(route_id: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    return _REGISTRY.get(str(route_id or ""))
