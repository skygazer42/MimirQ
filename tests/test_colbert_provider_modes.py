from __future__ import annotations

import pytest

from app.rag.reranker.colbert import ColBERTReranker, get_token_embedder
from app.rag.reranker.factory import describe_reranker_provider, get_reranker
from app.rag.reranker.types import RerankCandidate


def test_colbert_deterministic_mode_is_explicit_and_observable() -> None:
    reranker = get_reranker("colbert", provider_name="deterministic", deterministic_dim=32)
    assert isinstance(reranker, ColBERTReranker)
    assert reranker.provider_name == "deterministic"
    assert reranker.deterministic_dim == 32

    out = reranker.rerank(
        query="kubernetes",
        candidates=[
            RerankCandidate(id="a", text="kubernetes basics"),
            RerankCandidate(id="b", text="finance report"),
        ],
    )
    assert out.provider == "colbert"
    assert out.model_used == "deterministic_hash"
    assert out.stats.get("embedder_provider") == "deterministic"


def test_colbert_hf_mode_requires_model_name() -> None:
    with pytest.raises(ValueError, match="model_name"):
        _ = get_token_embedder(provider_name="hf", model_name="")


def test_colbert_hf_mode_rejects_invalid_device() -> None:
    with pytest.raises(ValueError, match="device"):
        _ = get_token_embedder(
            provider_name="hf",
            model_name="colbert-ir/colbertv2.0",
            device="tpu",
        )


def test_describe_reranker_provider_colbert_modes_are_explicit() -> None:
    det = describe_reranker_provider("colbert", provider_name="deterministic")
    hf = describe_reranker_provider("colbert", provider_name="hf")

    assert det == {"provider": "colbert", "tier": "offline_only", "mode": "deterministic"}
    assert hf == {"provider": "colbert", "tier": "experimental", "mode": "hf"}
