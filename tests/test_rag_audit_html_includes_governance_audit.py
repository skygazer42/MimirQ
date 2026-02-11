from __future__ import annotations


def test_rag_audit_html_includes_governance_audit_section() -> None:
    from app.services.report_html import render_rag_audit_html

    html = render_rag_audit_html(
        title="t",
        dataset_name="ds",
        dataset_id="d",
        generated_at="2026-01-01T00:00:00Z",
        report={
            "profile": {"total_documents": 2, "total_size_bytes": 0, "by_status": {}, "by_file_type": {}},
            "compliance": {"quarantined_documents": 0, "failed_documents": 0},
            "governance_audit": {
                "used_documents": 2,
                "truncated": False,
                "docs_with_parsed_content_persisted": 1,
                "original_chars_total": 1000,
                "cleaned_chars_total": 800,
                "char_reduction_ratio": 0.2,
                "docs_changed": 2,
                "docs_dropped": 0,
                "paragraphs_dropped_total": 5,
                "references_removed_lines_total": 12,
                "urls_changed_total": 3,
                "boilerplate_removed_sections_total": 1,
                "boilerplate_removed_lines_total": 9,
                "images_removed_total": 2,
                "tables_normalized_total": 1,
                "table_rows_changed_total": 4,
                "code_lines_stripped_total": 7,
            },
        },
        redact=False,
    )

    assert "Governance Audit（治理效果）" in html
    assert "char_reduction_ratio" in html
    assert "0.20" in html  # 20%
    assert "paragraphs_dropped_total" in html
    assert "5" in html

