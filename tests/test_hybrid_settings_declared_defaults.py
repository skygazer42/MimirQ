from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("implementation", ["mixin", "active"])
def test_zero_lexical_settings_use_existing_minimums(implementation, monkeypatch):
    from app.rag.retrieval.hybrid import lexical, lexical_search

    for name in ["LEXICAL_DB_FETCH_MULTIPLIER", "LEXICAL_DB_MAX_CANDIDATES", "LEXICAL_DB_TRGM_MIN_QUERY_CHARS"]:
        monkeypatch.setattr(lexical.settings, name, 0)
    monkeypatch.setattr(lexical.settings, "LEXICAL_DB_TRGM_ENABLED", False)
    resolve = (
        lexical.LexicalDBMixin._lexical_search_config
        if implementation == "mixin"
        else lexical_search._lexical_search_config
    )
    _, fetch_k, want_trgm, min_chars = resolve(5)
    assert fetch_k == 5
    assert want_trgm is False
    assert min_chars == 1


def test_zero_conditional_rerank_thresholds_skip_model_call(monkeypatch):
    from app.rag.retrieval.hybrid.candidate_ranking import _RankingRun, settings

    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_SKIP_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "RERANK_SKIP_GAP", 0.0)
    model_call = MagicMock(side_effect=AssertionError("zero thresholds should skip reranker"))
    context = SimpleNamespace(
        reranker_provider="llm",
        reranker_top_n=None,
        metrics={},
        request=SimpleNamespace(options=SimpleNamespace(requested_k=None, top_k=1), query="question"),
        _run_llm_reranker=model_call,
    )
    results = [{"score": 0.1}, {"score": 0.1}]
    assert _RankingRun._apply_optional_llm_reranker(context, results) is results
    assert context.metrics["rerank"]["skip_reason"] == "high_confidence"
    model_call.assert_not_called()
