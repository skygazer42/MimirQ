from __future__ import annotations

from langchain_core.documents import Document


def test_merge_cross_page_tables_when_columns_match_and_following_header_is_missing() -> None:
    from app.parsing.processors.cross_page_merge import merge_cross_page_documents

    docs = [
        Document(
            page_content="| Name | Value |\n| --- | --- |\n| alpha | 1 |",
            metadata={
                "page": 1,
                "doc_type_kwd": "table",
                "table_columns": ["Name", "Value"],
                "table_header_present": True,
                "table_truncated": True,
            },
        ),
        Document(
            page_content="| beta | 2 |\n| gamma | 3 |",
            metadata={
                "page": 2,
                "doc_type_kwd": "table",
                "table_columns": ["Name", "Value"],
                "table_header_present": False,
            },
        ),
    ]

    out = merge_cross_page_documents(docs)

    assert len(out) == 1
    assert "| gamma | 3 |" in out[0].page_content
    assert out[0].metadata["cross_page_merged"] is True
    assert out[0].metadata["cross_page_merge_kind"] == "table"
    assert out[0].metadata["cross_page_merge_pages"] == [1, 2]


def test_merge_cross_page_numbered_lists_when_sequence_continues() -> None:
    from app.parsing.processors.cross_page_merge import merge_cross_page_documents

    docs = [
        Document(
            page_content="1. first item\n2. second item",
            metadata={"page": 3},
        ),
        Document(
            page_content="3. third item\n4. fourth item",
            metadata={"page": 4},
        ),
    ]

    out = merge_cross_page_documents(docs)

    assert len(out) == 1
    assert "4. fourth item" in out[0].page_content
    assert out[0].metadata["cross_page_merge_kind"] == "list"
    assert out[0].metadata["cross_page_merge_pages"] == [3, 4]


def test_does_not_merge_tables_when_column_shape_changes() -> None:
    from app.parsing.processors.cross_page_merge import merge_cross_page_documents

    docs = [
        Document(
            page_content="| Name | Value |\n| --- | --- |\n| alpha | 1 |",
            metadata={
                "page": 1,
                "doc_type_kwd": "table",
                "table_columns": ["Name", "Value"],
                "table_truncated": True,
            },
        ),
        Document(
            page_content="| Name | Value | Extra |\n| --- | --- | --- |\n| beta | 2 | x |",
            metadata={
                "page": 2,
                "doc_type_kwd": "table",
                "table_columns": ["Name", "Value", "Extra"],
                "table_header_present": True,
            },
        ),
    ]

    out = merge_cross_page_documents(docs)

    assert len(out) == 2
