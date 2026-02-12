from __future__ import annotations


def test_report_html_renders_extended_retrieval_slices_dims() -> None:
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
                "metrics": [],
                "params": {"top_k": 20},
                "summary": {
                    "items": 1,
                    "retrieval_hit_at_20": 1.0,
                    "retrieval_slices": {
                        "file_type": {"buckets": [{"key": "pdf", "items": 1}]},
                        "language": {"buckets": [{"key": "zh", "items": 1}]},
                        "directory": {"buckets": [{"key": "root", "items": 1}]},
                        "hit_type": {"buckets": [{"key": "vector", "items": 1}]},
                        "quality": {"buckets": [{"key": "high_density", "items": 1}]},
                        "pipeline_hash": {"buckets": [{"key": "ph1", "items": 1}]},
                    },
                },
                "created_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:10Z",
            },
        },
        redact=False,
    )

    assert "<h2>hit_type</h2>" in html
    assert "<h2>quality</h2>" in html
    assert "<h2>pipeline_hash</h2>" in html

