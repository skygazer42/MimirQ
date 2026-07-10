
from app.rag.evaluation.metrics.ragas_adapter import adapt_ragas_scores


def test_adapt_ragas_scores_maps_known_metrics_into_unified_shape() -> None:
    adapted = adapt_ragas_scores(
        {
            "faithfulness": 0.82,
            "answer_relevancy": 0.76,
            "context_precision": 0.71,
        }
    )

    assert adapted["provider"] == "ragas"
    assert adapted["scores"]["faithfulness"] == 0.82
    assert adapted["scores"]["answer_relevancy"] == 0.76
    assert adapted["scores"]["context_precision"] == 0.71
