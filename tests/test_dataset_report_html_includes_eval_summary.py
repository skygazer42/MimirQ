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


def test_dataset_report_html_includes_safe_retrieval_audit_section() -> None:
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
            "retrieval_audit": {
                "status": "failed",
                "plugin_refs": ["plugin:demo@1.0.0:chunk"],
                "plugin_package_hashes": ["abcdef1234567890"],
                "failure_categories": {"scope": 1, "ranking": 1},
                "recommended_next_action": "Fix metadata scope and ranking before enabling production retrieval.",
                "gates": [
                    {
                        "name": "latest_regression_run",
                        "status": "failed",
                        "source": "regression_runs.summary",
                        "metrics": {
                            "hit_at_1": 0.5,
                            "hit_at_3": 1.0,
                            "expected_metadata_hit_rate": 0.8,
                            "retrieval_effective_context_rate": 0.7,
                            "raw_context": "SHOULD_NOT_RENDER_RAW_CHUNK",
                            "api_key": "SHOULD_NOT_RENDER_SECRET",
                        },
                        "failed_conditions": ["scope", "ranking"],
                    }
                ],
            },
        },
        redact=False,
    )

    assert "Retrieval Audit" in html
    assert "failed" in html
    assert "plugin:demo@1.0.0:chunk" in html
    assert "abcdef12" in html
    assert "expected_metadata_hit_rate" in html
    assert "retrieval_effective_context_rate" in html
    assert "SHOULD_NOT_RENDER_RAW_CHUNK" not in html
    assert "SHOULD_NOT_RENDER_SECRET" not in html
