from __future__ import annotations


def test_processor_build_governance_audit_metadata_patch() -> None:
    from langchain_core.documents import Document

    from app.parsing.processors.processor import DocumentProcessorService

    svc = DocumentProcessorService()
    before = [Document(page_content="abc", metadata={})]
    after = [
        Document(
            page_content="ab",
            metadata={
                "governance_quality": {
                    "chars_non_space": 10,
                    "chars_alnum_cjk": 5,
                    "lines_total": 10,
                    "lines_outline": 2,
                    "content_chars": 50,
                }
            },
        )
    ]

    patch = svc._build_governance_audit_metadata_patch(before_items=before, after_items=after)

    assert patch["governance_char_stats"]["original_chars"] == 3
    assert patch["governance_char_stats"]["cleaned_chars"] == 2
    assert patch["governance_char_stats"]["reduction_pct"] == 33

    quality = patch["governance_quality"]
    assert abs(float(quality["density"]) - 0.5) < 1e-9
    assert abs(float(quality["heading_ratio"]) - 0.2) < 1e-9
    assert patch["governance_quality_source"] == "cleaned"

