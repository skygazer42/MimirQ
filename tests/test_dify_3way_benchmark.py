from scripts.dify_3way_benchmark import _execution_stats, _is_timeout_error_text, _merge_retry_results
from scripts.evaluate_mixed_rag_quality import evaluate_item, evaluate_mixed_rag_quality


def test_timeout_detection_includes_gateway_504() -> None:
    assert _is_timeout_error_text("HTTP 504: Gateway Time-out") is True
    assert _is_timeout_error_text("HTTP 400: bad request") is False


def test_execution_stats_only_measure_current_concurrent_run() -> None:
    stats = _execution_stats(
        [
            {"case_id": "current-a", "latency_ms": 100},
            {"case_id": "current-b", "latency_ms": 300},
            {"case_id": "resumed", "latency_ms": 900},
        ],
        executed_case_ids={"current-a", "current-b"},
        concurrency=3,
        elapsed_ms=1000,
    )

    assert stats == {
        "concurrency": 3,
        "cases": 2,
        "elapsed_ms": 1000,
        "throughput_cases_per_sec": 2.0,
        "latency_ms": {
            "count": 2,
            "min_ms": 100,
            "max_ms": 300,
            "mean_ms": 200.0,
            "p50_ms": 100,
            "p90_ms": 300,
            "p95_ms": 300,
            "p99_ms": 300,
        },
    }


def test_retry_latency_includes_all_attempts() -> None:
    items = _merge_retry_results(
        [{"case_id": "case-a", "ok": False, "latency_ms": 1000, "error": "timeout"}],
        [{"case_id": "case-a", "ok": True, "latency_ms": 250}],
    )

    assert items[0]["attempt_count"] == 2
    assert items[0]["attempt_latency_ms"] == [1000.0, 250.0]
    assert items[0]["total_latency_ms"] == 1250.0
    stats = _execution_stats(items, executed_case_ids={"case-a"}, concurrency=1, elapsed_ms=1250)
    assert stats["latency_ms"]["mean_ms"] == 1250.0


def test_quality_report_uses_total_retry_latency() -> None:
    report = evaluate_mixed_rag_quality(
        cases=[{"id": "case-a", "question": "test"}],
        runs=[
            {
                "system": "mimirq",
                "items": [
                    {
                        "case_id": "case-a",
                        "records": [],
                        "latency_ms": 250.0,
                        "total_latency_ms": 1250.0,
                    }
                ],
            }
        ],
    )

    assert report["items"][0]["latency_ms"] == 1250.0
    assert report["systems"][0]["mean_latency_ms"] == 1250.0


def test_answer_subquestion_coverage_is_neutral_when_no_subquestions() -> None:
    result = evaluate_item(
        {
            "id": "case-1",
            "evidence_clauses": [
                {"id": "fee", "required_terms": ["事项名称：企业登记", "收费情况：", "不收费"]}
            ],
        },
        {"system": "test"},
        {
            "answer": "企业登记收费情况：不收费",
            "records": [{"content": "收费情况：不收费", "metadata": {"service_name": "企业登记"}}],
        },
    )

    assert result["answer_subquestion_coverage"] == 1.0
    assert result["evidence_coverage"] == 1.0
