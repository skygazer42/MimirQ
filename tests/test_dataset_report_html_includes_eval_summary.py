from __future__ import annotations


def test_dataset_report_html_includes_eval_summary_section() -> None:
    from app.services.report_html import render_dataset_report_html

    html = render_dataset_report_html(
        title="t",
        dataset_name="ds",
        dataset_id="d",
        generated_at="2026-01-01T00:00:00Z",
        report={
            "profile": {"total_documents": 1, "total_size_bytes": 0, "by_status": {}, "by_file_type": {}},
            "chunk_quality_metrics": {
                "gate_grade_docs": {},
                "coverage_low_documents": 0,
                "overlap_waste_high_documents": 0,
                "token_stats_missing_documents": 0,
            },
            "pipeline_versions": [],
            "connectors": [],
            "latest_regression_run": {
                "run_id": "00000000-0000-0000-0000-000000000000",
                "status": "completed",
                "metrics": ["faithfulness"],
                "params": {"top_k": 20},
                "summary": {"faithfulness": 0.75, "retrieval_hit_at_20": 1.0},
                "created_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:10Z",
            },
        },
        redact=False,
    )

    assert "评估 Summary" in html
    assert "faithfulness" in html

