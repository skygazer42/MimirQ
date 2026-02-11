from __future__ import annotations


def test_governance_stats_tracks_structural_cleaning_effects() -> None:
    from langchain_core.documents import Document

    from app.rag.preprocessing.processor import governance_processor

    doc = Document(
        page_content=(
            "## 免责声明\n"
            "这里是免责声明内容。\n"
            "\n"
            "## 正文\n"
            "![logo](logo.png)\n"
            "\n"
            "a | b\n"
            "---|---\n"
            "1|2\n"
            "\n"
            "```python\n"
            "1 print('a')\n"
            "2 print('b')\n"
            "3 print('c')\n"
            "4 print('d')\n"
            "5 print('e')\n"
            "```\n"
        ),
        metadata={},
    )

    cleaned, stats = governance_processor.clean_documents(
        [doc],
        remove_boilerplate=True,
        remove_images="all",
        normalize_tables=True,
        strip_code_line_numbers=True,
    )

    assert cleaned
    assert stats.boilerplate_removed_sections > 0
    assert stats.images_removed > 0
    assert stats.tables_normalized > 0
    assert stats.table_rows_changed > 0
    assert stats.code_lines_stripped > 0

