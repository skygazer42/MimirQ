from __future__ import annotations


def test_precheck_html_includes_token_histogram_and_kpis() -> None:
    from app.services.report_html import render_precheck_html

    html = render_precheck_html(
        title="t",
        dataset_name="ds",
        dataset_id="d",
        root_path="/tmp",
        generated_at="2026-01-01T00:00:00Z",
        summary={
            "total_files": 1,
            "total_size_bytes": 10,
            "by_file_type": {"txt": 1},
            "file_size_histogram": [{"label": "0-100KB", "count": 1}],
            "length_percentiles": {"p50": 10, "p90": 10},
            "length_histogram": [{"label": "0-500", "count": 1}],
            "token_percentiles": {"p50": 123, "p90": 456},
            "token_histogram": [{"label": "0-200", "count": 1}],
            "pdf_scan": {"scanned": 0, "not_scanned": 0, "unknown": 0},
            "pii_hits_total": {},
            "secrets_hits_total": {},
            "findings": [],
        },
        redact=False,
    )

    # Headings / KPIs are stable strings used for offline sharing.
    assert "长度分布（tokens）" in html
    assert "P50 文本长度（tokens）" in html
    assert "123" in html

