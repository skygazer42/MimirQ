from __future__ import annotations

from app.rag.tools.retrieval_config_tool import configure_retrieval


def test_configure_retrieval_applies_profile_overrides_after_requested_knob_updates() -> None:
    out = configure_retrieval(
        top_k=5,
        reranker_top_n=3,
        retrieval_profile="hybrid_ce",
        retrieval_mode="vector",
    )

    assert out["schema"] == "mimirq.retrieval_config_tool.v1"
    assert out["top_k"] >= 20
    assert out["reranker_top_n"] >= 20
    assert out["retrieval_profile"] == "hybrid_ce"
    assert out["retrieval_mode"] == "hybrid"
    assert out["reranker_provider"] == "cross_encoder"


def test_configure_retrieval_clamps_manual_values_without_profile() -> None:
    out = configure_retrieval(
        top_k=999,
        reranker_top_n=0,
        retrieval_profile=None,
        retrieval_mode="keyword",
    )

    assert out["top_k"] == 100
    assert out["reranker_top_n"] == 1
    assert out["retrieval_profile"] is None
    assert out["retrieval_mode"] == "keyword"
