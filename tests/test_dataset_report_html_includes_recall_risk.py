from __future__ import annotations


def test_dataset_report_html_includes_recall_risk_section() -> None:
    from app.services.report_html import render_dataset_report_html

    html = render_dataset_report_html(
        title="t",
        dataset_name="ds",
        dataset_id="d",
        generated_at="2026-01-01T00:00:00Z",
        report={
            "profile": {
                "total_documents": 2,
                "total_size_bytes": 0,
                "by_status": {},
                "by_file_type": {},
                "recall_risk_hints": [
                    {
                        "key": "short_chunks_heavy",
                        "label": "短 Chunk 占比偏高",
                        "severity": "warning",
                        "observed": {"short_chunk_pct": 42},
                        "message": "短 chunk 占比偏高",
                    }
                ],
            },
            "chunk_quality_metrics": {
                "gate_grade_docs": {},
                "coverage_low_documents": 0,
                "overlap_waste_high_documents": 0,
                "token_stats_missing_documents": 0,
            },
            "pipeline_versions": [],
            "connectors": [],
        },
        redact=False,
    )

    assert "召回风险摘要（Recall Risk Hints）" in html
    assert "短 Chunk 占比偏高" in html
