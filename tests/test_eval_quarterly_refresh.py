from __future__ import annotations


def _sample(idx: int) -> dict:
    return {
        "sample_id": f"s-{idx:02d}",
        "query": f"query {idx}",
        "query_type": "factual",
        "source_type": "synthetic",
        "gold_answer": f"answer {idx}",
        "gold_chunk_ids": [f"chunk-{idx}"],
        "expected_route": "retrieval",
        "annotation_status": "reviewed",
        "review_status": "approved",
    }


def test_plan_quarterly_refresh_selects_deterministic_20_percent_slice() -> None:
    from app.rag.evaluation.datasets.quarterly_refresh import plan_quarterly_refresh

    rows = [_sample(i) for i in range(10)]

    a = plan_quarterly_refresh(rows=rows, quarter_key="2026Q3")
    b = plan_quarterly_refresh(rows=rows, quarter_key="2026Q3")
    c = plan_quarterly_refresh(rows=rows, quarter_key="2026Q4")

    assert a["schema"] == "mimirq.eval.dataset.quarterly_refresh.v1"
    assert a["summary"]["total_samples"] == 10
    assert a["summary"]["refresh_samples"] == 2
    assert a["summary"]["stable_samples"] == 8
    assert a["refresh_sample_ids"] == b["refresh_sample_ids"]
    assert a["refresh_sample_ids"] != c["refresh_sample_ids"]


def test_plan_quarterly_refresh_marks_refresh_rows_with_quarter_metadata() -> None:
    from app.rag.evaluation.datasets.quarterly_refresh import plan_quarterly_refresh

    rows = [_sample(i) for i in range(5)]
    out = plan_quarterly_refresh(rows=rows, quarter_key="2026Q3", refresh_ratio=0.2)

    refreshed = out["refresh_rows"]
    assert len(refreshed) == 1
    row = refreshed[0]
    assert row["refresh_quarter"] == "2026Q3"
    assert row["refresh_action"] == "regenerate"
    assert "quarterly_refresh" in list(row.get("tags") or [])
