from __future__ import annotations

from langchain_core.documents import Document

from app.types.document_analytics import compute_document_analytics


def test_compute_document_analytics_basic_counts_and_language() -> None:
    md = "# 标题\n\n这是一个测试。\n\nHello.\n@@1\t0\t0\t1\t1##\n"
    docs = [
        Document(page_content="table", metadata={"content_type": "table"}),
        Document(page_content="image", metadata={"doc_type_kwd": "image"}),
    ]

    analytics = compute_document_analytics(
        markdown=md,
        documents=docs,
        pdf_quality={"page_count": 12},
        detect_language=True,
        language_min_chars=1,
    )

    assert analytics.char_count == len(md)
    assert analytics.line_count == len(md.splitlines())
    assert analytics.heading_count == 1
    assert analytics.page_count == 12
    assert analytics.table_count == 1
    assert analytics.image_count == 1
    assert analytics.block_count == 1
    assert analytics.language == "mixed" or analytics.language == "zh"
    assert (analytics.language_confidence or 0.0) >= 0.0

