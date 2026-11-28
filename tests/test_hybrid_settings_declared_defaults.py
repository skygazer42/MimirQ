from types import SimpleNamespace
from unittest.mock import MagicMock


def test_metadata_exact_supplement_requires_opt_in() -> None:
    from app.infrastructure.config import Settings

    assert Settings.model_fields["LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED"].default is False


def test_chat_retrieval_options_preserve_the_lexical_supplement_policy() -> None:
    from app.api.schemas.conversations import ChatRAGConfig
    from app.services.retrieval.defaults import retrieval_options

    policy = {
        "lexical_db_hybrid_fallback_only": True,
        "lexical_db_hybrid_metadata_exact_fallback_enabled": False,
        "metadata_exact_db_fallback_enabled": True,
    }
    options = retrieval_options(ChatRAGConfig(**policy))
    assert {name: options[name] for name in policy} == policy


def test_zero_lexical_settings_use_existing_minimums(monkeypatch):
    from app.rag.retrieval.recall import lexical_search

    for name in ["LEXICAL_DB_FETCH_MULTIPLIER", "LEXICAL_DB_MAX_CANDIDATES", "LEXICAL_DB_TRGM_MIN_QUERY_CHARS"]:
        monkeypatch.setattr(lexical_search.settings, name, 0)
    monkeypatch.setattr(lexical_search.settings, "LEXICAL_DB_TRGM_ENABLED", False)
    _, fetch_k, want_trgm, min_chars = lexical_search._lexical_search_config(5)
    assert fetch_k == 5
    assert want_trgm is False
    assert min_chars == 1


def test_zero_conditional_rerank_thresholds_skip_model_call(monkeypatch):
    from app.rag.retrieval.ranking.candidates import _RankingRun, settings

    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_SKIP_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "RERANK_SKIP_GAP", 0.0)
    model_call = MagicMock(side_effect=AssertionError("zero thresholds should skip reranker"))
    context = SimpleNamespace(
        reranker_provider="llm",
        reranker_top_n=None,
        metrics={},
        request=SimpleNamespace(options=SimpleNamespace(requested_k=None, top_k=1), query="question"),
        _run_optional_reranker=model_call,
    )
    results = [{"score": 0.1}, {"score": 0.1}]
    assert _RankingRun._apply_optional_reranker(context, results) is results
    assert context.metrics["rerank"]["skip_reason"] == "high_confidence"
    model_call.assert_not_called()
