from __future__ import annotations


def test_alias_candidates_prioritize_long_domain_phrases() -> None:
    from app.rag.kg.repository import _extract_alias_candidates

    terms = _extract_alias_candidates(
        "Which survey reviews graph neural networks including graph convolution and graph attention networks?"
    )

    assert "graph neural networks" in terms
    assert "neural" in terms
    assert terms.index("graph neural networks") < terms.index("neural")

