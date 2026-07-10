
from app.rag.evaluation.runners.base import build_runner_result


def test_build_runner_result_emits_unified_shape() -> None:
    result = build_runner_result(
        sample_id="s1",
        route_id="retrieval",
        query_type="factual",
        source_type="real_log",
        expected_route="retrieval",
        actual_route="retrieval",
        answer={"text": "ok"},
        citations=[{"chunk_id": "c1"}],
        latency_ms=1200,
        token_cost=0.05,
        route_config={"top_k": 10},
        evaluators={"answer_det": {"answer_em": 1.0}},
    )

    assert result["route_id"] == "retrieval"
    assert result["answer"]["text"] == "ok"
    assert result["agentic_status"] is None
