from __future__ import annotations

from scripts import remote_observability_metrics_probe as mod


def test_build_chat_payload_defaults_to_extractive_hybrid() -> None:
    payload = mod.build_chat_payload(
        dataset_id="dataset-1",
        message="What token belongs only to OBS?",
    )

    assert payload["dataset_id"] == "dataset-1"
    assert payload["message"] == "What token belongs only to OBS?"
    assert payload["stream"] is False
    rag = payload["rag_config"]
    assert rag["answer_mode"] == "extractive"
    assert rag["retrieval_mode"] == "hybrid"
    assert rag["score_threshold"] == 0.0


def test_build_chat_payload_accepts_keyword_zero_hit_override() -> None:
    payload = mod.build_chat_payload(
        dataset_id="dataset-1",
        message="qwertyuiop asdfghjkl zxcvbnm",
        retrieval_mode="keyword",
        score_threshold=1.0,
    )

    rag = payload["rag_config"]
    assert rag["retrieval_mode"] == "keyword"
    assert rag["score_threshold"] == 1.0
    assert rag["answer_mode"] == "extractive"


def test_metrics_progress_satisfied_requires_enabled_and_count_growth() -> None:
    before_summary = {"rag_trace_count": 10}
    before_qa = {"rag_trace_count": 7, "zero_hit_count": 2}

    assert (
        mod.metrics_progress_satisfied(
            before_summary=before_summary,
            before_query_analytics=before_qa,
            summary_after={"enabled": True, "rag_trace_count": 11},
            query_analytics_after={"enabled": True, "rag_trace_count": 8, "zero_hit_count": 3},
            min_trace_delta=1,
            min_zero_hit_delta=1,
        )
        is True
    )

    assert (
        mod.metrics_progress_satisfied(
            before_summary=before_summary,
            before_query_analytics=before_qa,
            summary_after={"enabled": False, "rag_trace_count": 11},
            query_analytics_after={"enabled": True, "rag_trace_count": 8, "zero_hit_count": 3},
            min_trace_delta=1,
            min_zero_hit_delta=1,
        )
        is False
    )

    assert (
        mod.metrics_progress_satisfied(
            before_summary=before_summary,
            before_query_analytics=before_qa,
            summary_after={"enabled": True, "rag_trace_count": 10},
            query_analytics_after={"enabled": True, "rag_trace_count": 8, "zero_hit_count": 3},
            min_trace_delta=1,
            min_zero_hit_delta=1,
        )
        is False
    )
