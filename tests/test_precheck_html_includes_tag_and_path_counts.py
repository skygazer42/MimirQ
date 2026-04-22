from __future__ import annotations


def test_precheck_html_includes_primary_tags_and_processing_paths_sections() -> None:
    from app.services.report_html import render_precheck_html

    html = render_precheck_html(
        title="t",
        dataset_name="ds",
        dataset_id="d",
        root_path="/tmp",
        generated_at="2026-01-01T00:00:00Z",
        summary={
            "total_files": 2,
            "total_size_bytes": 20,
            "by_file_type": {"pdf": 1, "xlsx": 1},
            "file_size_histogram": [{"label": "0-100KB", "count": 2}],
            "length_percentiles": {"p50": 10, "p90": 20},
            "length_histogram": [{"label": "0-500", "count": 2}],
            "token_percentiles": {"p50": 100, "p90": 200},
            "token_histogram": [{"label": "0-200", "count": 2}],
            "pdf_scan": {"scanned": 1, "not_scanned": 0, "unknown": 0},
            "pii_hits_total": {},
            "secrets_hits_total": {},
            "findings": [],
            "primary_tag_counts": {"Scan_PDF": 1, "Table_Heavy": 1},
            "processing_path_counts": {"ocr_or_vlm_path": 1, "structured_table_path": 1},
        },
        redact=False,
    )

    assert "主标签分布" in html
    assert "处理路径建议" in html
    assert "Scan_PDF" in html
    assert "structured_table_path" in html
