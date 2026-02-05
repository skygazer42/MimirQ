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

