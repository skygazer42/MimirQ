from __future__ import annotations

import numpy as np

from app.rag.reranker.colbert import ColBERTReranker, TokenEmbedder
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate


class _OneHotEmbedder(TokenEmbedder):
    def __init__(self) -> None:
        # Fixed tiny vocab for determinism in tests.
        self._vecs = {
            "kubernetes": np.array([1.0, 0.0], dtype=np.float32),
            "foo": np.array([0.0, 1.0], dtype=np.float32),
            "bar": np.array([0.0, 1.0], dtype=np.float32),
            "baz": np.array([0.0, 1.0], dtype=np.float32),
        }

    def encode(self, tokens: list[str]) -> np.ndarray:
        rows = []
        for t in tokens:
            rows.append(self._vecs.get(t, np.zeros((2,), dtype=np.float32)))
        return np.stack(rows, axis=0) if rows else np.zeros((0, 2), dtype=np.float32)


def test_colbert_reranker_orders_by_late_interaction_score() -> None:
    reranker = ColBERTReranker(embedder=_OneHotEmbedder())
    candidates = [
        RerankCandidate(id="a", text="kubernetes foo"),
        RerankCandidate(id="b", text="bar baz"),
    ]

    out = reranker.rerank("kubernetes", candidates)
    assert out.ordered_ids[0] == "a"
    assert out.score_map["a"] > out.score_map["b"]


def test_factory_resolves_colbert_provider() -> None:
    inst = get_reranker("colbert")
    assert inst.__class__.__name__.lower().startswith("colbert")

