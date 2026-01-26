from app.services.report_html import render_dataset_profile_html, render_precheck_html


def test_dataset_profile_html_redaction_hides_dataset_fields():
    html = render_dataset_profile_html(
        title="t",
        dataset_name="秘密数据集",
        dataset_id="abc-123",
        generated_at="2026-01-01T00:00:00Z",
        summary={
            "total_documents": 2,
            "total_size_bytes": 1234,
            "length_percentiles": {"p50": 10, "p90": 20},
            "pdf_scan": {"scanned": 1, "not_scanned": 0, "unknown": 0},
            "by_file_type": {"pdf": 2},
            "by_status": {"completed": 2},
            "length_histogram": [{"label": "0-500", "count": 2}],
            "file_size_histogram": [{"label": "0-100KB", "count": 2}],
            "pii_hits_total": {"phone": 3},
            "secrets_hits_total": {"openai_key": 1},
            "findings": [{"key": "pii", "label": "PII 命中", "severity": "warning", "count": 1}],
        },
        redact=True,
    )
    assert "秘密数据集" not in html
    assert "abc-123" not in html
    assert "[REDACTED]" in html


def test_precheck_html_redaction_hides_root_path():
    html = render_precheck_html(
        title="t2",
        dataset_name="ds",
        dataset_id="abc-456",
        root_path=r"C:\secret\data",
        generated_at="2026-01-01T00:00:00Z",
        summary={
            "total_files": 1,
            "total_size_bytes": 10,
            "by_file_type": {"txt": 1},
            "file_size_histogram": [{"label": "0-100KB", "count": 1}],
            "length_percentiles": {"p50": 10, "p90": 10},
            "length_histogram": [{"label": "0-500", "count": 1}],
            "pdf_scan": {"scanned": 0, "not_scanned": 0, "unknown": 0},
            "pii_hits_total": {},
            "secrets_hits_total": {},
            "findings": [],
        },
        redact=True,
    )
    assert r"C:\secret\data" not in html
    assert "[REDACTED]" in html

