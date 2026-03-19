from __future__ import annotations


def test_score_chunk_semantic_quality_basic_shape() -> None:
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    scores, token_set = score_chunk_semantic_quality(
        "This section describes the API behavior. It returns JSON.\n",
        tokens_est=50,
        prev_token_set=None,
    )

    assert isinstance(scores, dict)
    assert isinstance(token_set, set)
    assert "information_density" in scores
    assert "semantic_completeness" in scores
    assert "self_containedness" in scores
    assert "pronoun_ratio" in scores
    assert "dedup_risk_prev_jaccard" in scores
    assert "needs_review" in scores
    assert "reasons" in scores

    for k in ("information_density", "semantic_completeness", "self_containedness", "pronoun_ratio"):
        v = float(scores.get(k) or 0.0)
        assert 0.0 <= v <= 1.0


def test_score_chunk_semantic_quality_near_duplicate_flags() -> None:
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    a, token_set_a = score_chunk_semantic_quality("API returns JSON. API returns JSON.", tokens_est=40, prev_token_set=None)
    b, _token_set_b = score_chunk_semantic_quality(
        "API returns JSON. API returns JSON.",
        tokens_est=40,
        prev_token_set=token_set_a,
    )

    assert a["dedup_risk_prev_jaccard"] is None
    assert b["dedup_risk_prev_jaccard"] is not None
    assert float(b["dedup_risk_prev_jaccard"] or 0.0) >= 0.9
    assert "near_duplicate" in (b.get("reasons") or [])


def test_score_chunk_semantic_quality_incomplete_end_is_penalized() -> None:
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    good, _ = score_chunk_semantic_quality("A complete sentence.", tokens_est=10, prev_token_set=None)
    bad, _ = score_chunk_semantic_quality("A complete sentence", tokens_est=10, prev_token_set=None)

    assert float(good["semantic_completeness"]) > float(bad["semantic_completeness"])

