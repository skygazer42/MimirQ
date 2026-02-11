from __future__ import annotations


def test_rag_audit_html_includes_precheck_section() -> None:
    from app.services.report_html import render_rag_audit_html

    html = render_rag_audit_html(
        title="t",
        dataset_name="ds",
        dataset_id="d",
        generated_at="2026-01-01T00:00:00Z",
        report={
            "profile": {"total_documents": 1, "total_size_bytes": 0, "by_status": {}, "by_file_type": {}},
            "compliance": {"quarantined_documents": 0, "failed_documents": 0},
            "precheck_summary": {
                "scan_run_id": "run-1",
                "generated_at": "2026-01-01T00:00:00Z",
                "total_files": 2,
                "total_size_bytes": 100,
                "by_file_type": {"pdf": 2},
                "file_size_histogram": [{"label": "0-100KB", "count": 2}],
                "token_histogram": [{"label": "0-200", "count": 2}],
                "language_mix": {"en": 2},
                "pii_hits_total": {},
                "secrets_hits_total": {},
                "pdf_scan": {"scanned": 0, "not_scanned": 2, "unknown": 0},
                "findings": [{"key": "pii", "label": "PII 命中", "severity": "warning", "count": 1}],
                "directory_stats": [{"path": "secret/dir", "total_files": 2, "risky_files": 1, "total_size_bytes": 100}],
            },
        },
        redact=False,
    )

    assert "Precheck（入库前摸底）" in html
    assert "secret/dir" in html

