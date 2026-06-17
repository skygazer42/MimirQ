from __future__ import annotations

import pytest


def test_metric_resolver_supports_expected_keys():
    from app.rag.evaluation.ragas import _resolve_metrics

    metrics = _resolve_metrics(
        [
            "faithfulness",
            "response_relevancy",
            "answer_similarity",
            "answer_correctness",
            "context_recall",
            "context_precision",
            "id_based_context_recall",
            "id_based_context_precision",
        ]
    )

    assert [type(m).__name__ for m in metrics] == [
        "Faithfulness",
        "ResponseRelevancy",
        "AnswerSimilarity",
        "AnswerCorrectness",
        "ContextRecall",
        "ContextPrecision",
        "IDBasedContextRecall",
        "IDBasedContextPrecision",
    ]


def test_metric_resolver_rejects_unknown_metric():
    from app.rag.evaluation.ragas import _resolve_metrics

    with pytest.raises(ValueError):
        _resolve_metrics(["nope_metric"])


def test_metric_resolver_defaults_when_empty():
    from app.rag.evaluation.ragas import _resolve_metrics

    metrics = _resolve_metrics([])
    assert [type(m).__name__ for m in metrics] == ["Faithfulness", "ResponseRelevancy"]


def test_metric_resolver_auto_lowers_response_relevancy_strictness_for_deepseek(monkeypatch):
    from app.rag.evaluation import ragas as mod

    monkeypatch.setattr(mod.settings, "LLM_API_BASE", "https://api.deepseek.com/v1", raising=False)
    monkeypatch.setattr(mod.settings, "LLM_MODEL", "deepseek-v4-flash", raising=False)
    monkeypatch.setattr(mod.settings, "RAGAS_RESPONSE_RELEVANCY_STRICTNESS", 0, raising=False)

    metrics = mod._resolve_metrics(["response_relevancy"])

    assert metrics[0].strictness == 1


def test_build_ragas_run_config_uses_bounded_runtime_settings(monkeypatch):
    from app.rag.evaluation import ragas as mod

    monkeypatch.setattr(mod.settings, "RAGAS_RUN_TIMEOUT_SEC", 45, raising=False)
    monkeypatch.setattr(mod.settings, "RAGAS_RUN_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(mod.settings, "RAGAS_RUN_MAX_WAIT_SEC", 2, raising=False)
    monkeypatch.setattr(mod.settings, "RAGAS_RUN_MAX_WORKERS", 3, raising=False)

    run_config = mod._build_ragas_run_config()

    assert run_config.timeout == 45
    assert run_config.max_retries == 1
    assert run_config.max_wait == 2
    assert run_config.max_workers == 3
