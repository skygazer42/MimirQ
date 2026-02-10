from __future__ import annotations


def test_dataset_report_html_includes_kg_stats_section() -> None:
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
            "kg_stats": {
                "events": 2,
                "entities": 3,
                "links": 4,
                "entity_types": [{"type": "person", "count": 2}],
                "updated_at": "2026-01-01T00:00:00Z",
            },
        },
        redact=False,
    )

    assert "Knowledge Graph（KG）" in html
    assert "2" in html  # events

