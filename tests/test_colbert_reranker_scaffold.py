from __future__ import annotations

import numpy as np
import pytest

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


def test_colbert_reranker_can_report_hf_provider_metadata() -> None:
    reranker = ColBERTReranker(
        provider_name="hf",
        model_name="colbert-ir/colbertv2.0",
        embedder=_OneHotEmbedder(),
    )
    candidates = [
        RerankCandidate(id="a", text="kubernetes foo"),
        RerankCandidate(id="b", text="bar baz"),
    ]

    out = reranker.rerank("kubernetes", candidates)
    assert out.ordered_ids[0] == "a"
    assert out.model_used == "colbert-ir/colbertv2.0"
    assert out.stats.get("embedder_provider") == "hf"
    assert out.stats.get("late_interaction") is True


def test_factory_resolves_colbert_provider() -> None:
    inst = get_reranker("colbert")
    assert inst.__class__.__name__.lower().startswith("colbert")


def test_factory_uses_configured_colbert_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "COLBERT_RERANK_PROVIDER", "hf", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MODEL_NAME", "colbert-ir/colbertv2.0", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_DEVICE", "cpu", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_BATCH_SIZE", 4, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RERANK_MAX_LENGTH", 64, raising=False)

    inst = get_reranker("colbert")
    assert getattr(inst, "provider_name", None) == "hf"
    assert getattr(inst, "model_name", None) == "colbert-ir/colbertv2.0"
