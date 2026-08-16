"""Safe retriever shims for retrieval orchestration import paths."""

from typing import Any


class _VectorStoreShim:
    def search(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []


class _HybridRetrieverShim:
    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self._state = dict(state or {})
        self._last_debug_metrics: dict[str, Any] = {}

    def model_copy(self, *, update: dict[str, Any] | None = None):  # noqa: ANN001
        next_state = dict(self._state)
        if isinstance(update, dict):
            next_state.update(update)
        return _HybridRetrieverShim(next_state)

    def invoke(self, _q: str):  # noqa: ANN001
        return []

    def _search_bm25(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return []


def _real_hybrid_retriever() -> Any | None:
    try:
        from app.rag.retriever import hybrid_retriever as real_hybrid_retriever

        return real_hybrid_retriever
    except Exception:
        return None


def get_vector_store():
    try:
        from app.rag.retriever import get_vector_store as real_get_vector_store

        return real_get_vector_store()
    except Exception:
        return _VectorStoreShim()


hybrid_retriever = _real_hybrid_retriever() or _HybridRetrieverShim()


__all__ = ["get_vector_store", "hybrid_retriever"]
