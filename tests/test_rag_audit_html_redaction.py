from __future__ import annotations


def test_rag_audit_html_redaction_hides_dataset_fields_and_paths() -> None:
    from app.services.report_html import render_rag_audit_html

    html = render_rag_audit_html(
        title="t",
        dataset_name="秘密数据集",
        dataset_id="abc-123",
        generated_at="2026-01-01T00:00:00Z",
        report={
            "dataset_name": "秘密数据集",
            "dataset_id": "abc-123",
            "profile": {"total_documents": 1, "total_size_bytes": 0, "by_status": {}, "by_file_type": {}},
            "compliance": {"quarantined_documents": 0, "failed_documents": 0},
            "latest_regression_run": {
                "status": "completed",
                "summary": {
                    "retrieval_slices": {
                        "directory": {"buckets": [{"key": "/private/secret", "items": 1, "retrieval_hit_at_20": 1.0}]}
                    }
                },
            },
            "precheck_summary": {
                "scan_run_id": "run-1",
                "generated_at": "2026-01-01T00:00:00Z",
                "total_files": 1,
                "total_size_bytes": 10,
                "by_file_type": {"txt": 1},
                "file_size_histogram": [{"label": "0-100KB", "count": 1}],
                "token_histogram": [{"label": "0-200", "count": 1}],
                "language_mix": {"en": 1},
                "pii_hits_total": {},
                "secrets_hits_total": {},
                "pdf_scan": {"scanned": 0, "not_scanned": 0, "unknown": 0},
                "findings": [],
                "directory_stats": [{"path": "/private/secret", "total_files": 1, "risky_files": 1, "total_size_bytes": 10}],
            },
        },
        redact=True,
    )

    assert "秘密数据集" not in html
    assert "abc-123" not in html
    assert "/private/secret" not in html
    assert "run-1" not in html
    assert "[REDACTED]" in html

