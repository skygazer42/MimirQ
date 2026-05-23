from __future__ import annotations

import sys
import time
import types

import pytest

from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate


class _FakeCrossEncoder:
    def predict(self, pairs):  # noqa: ANN001
        # pairs: [(query, doc), ...]
        out = []
        for q, d in pairs:
            q = str(q or "")
            d = str(d or "")
            # Simple deterministic scoring signal for tests:
            # - exact token hit => higher score
            # - otherwise => lower score
            out.append(1.0 if q and (q in d) else 0.0)
        return out


def test_cross_encoder_reranker_orders_by_score_and_is_stable() -> None:
    from app.rag.reranker.cross_encoder import CrossEncoderReranker

    reranker = CrossEncoderReranker(model_name="fake", model=_FakeCrossEncoder())
    candidates = [
        RerankCandidate(id="a", text="kubernetes foo"),
        RerankCandidate(id="b", text="bar baz"),
        RerankCandidate(id="c", text="kubernetes again"),
        # Tie case: both miss -> keep original order between them.
        RerankCandidate(id="d", text="nope"),
        RerankCandidate(id="e", text="still nope"),
    ]

    out = reranker.rerank("kubernetes", candidates, batch_size=2)
    assert out.ordered_ids[:3] == ["a", "c", "b"]
    assert out.score_map["a"] > out.score_map["b"]
    assert out.score_map["c"] > out.score_map["b"]

    # Stable tie-break for equal scores.
    d_idx = out.ordered_ids.index("d")
    e_idx = out.ordered_ids.index("e")
    assert d_idx < e_idx


def test_factory_resolves_cross_encoder_provider() -> None:
    inst = get_reranker("cross_encoder")
    assert inst.__class__.__name__.lower().startswith("crossencoder")


def test_cross_encoder_reranker_times_out_slow_model_load(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.reranker.cross_encoder import CrossEncoderReranker

    class _SlowCrossEncoder:
        def __init__(self, *_args, **_kwargs) -> None:
            time.sleep(0.2)

        def predict(self, pairs):  # noqa: ANN001
            return [0.0 for _ in pairs]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=_SlowCrossEncoder))
    reranker = CrossEncoderReranker(model_name="fake", load_timeout_sec=0.05)

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="cross_encoder_load_timeout"):
        reranker.rerank("kubernetes", [RerankCandidate(id="a", text="kubernetes foo")])
    assert time.monotonic() - started < 0.15


def test_describe_reranker_provider_classifies_tiers() -> None:
    from app.rag.reranker.factory import describe_reranker_provider

    assert describe_reranker_provider("cross_encoder")["tier"] == "prod"
    assert describe_reranker_provider("long_context")["tier"] == "prod"
    assert describe_reranker_provider("ltr")["tier"] == "prod"
    assert describe_reranker_provider("llm")["tier"] == "experimental"
    assert describe_reranker_provider("none")["tier"] == "disabled"
    assert describe_reranker_provider("colbert", provider_name="deterministic")["tier"] == "offline_only"
    assert describe_reranker_provider("colbert", provider_name="hf")["tier"] == "experimental"
