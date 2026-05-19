from __future__ import annotations

from langchain_core.documents import Document

from app.parsing.enrich.cross_page_table_linker import link_cross_page_table_documents


def _table_doc(name: str, *, page: int, bbox: dict[str, int], rows: list[list[str]]) -> Document:
    markdown_rows = ["| Name | Value |", "| --- | --- |", *[f"| {r[0]} | {r[1]} |" for r in rows]]
    return Document(
        page_content="\n".join(markdown_rows),
        metadata={
            "content_type": "table",
            "element_kind": "table",
            "element_id": name,
            "element_page": page,
            "element_bbox": bbox,
            "table_columns": ["Name", "Value"],
            "table_extraction": {
                "columns": ["Name", "Value"],
                "rows": rows,
                "row_count": len(rows),
                "col_count": 2,
                "source_page": page,
                "source_bbox": bbox,
                "source_element_id": name,
            },
            "table_outputs": {"markdown": "\n".join(markdown_rows)},
        },
    )


def test_link_cross_page_table_documents_merges_adjacent_continuation_tables() -> None:
    docs = [
        _table_doc("t1", page=1, bbox={"x0": 10, "x1": 100, "y0": 780, "y1": 950}, rows=[["A", "1"]]),
        _table_doc("t2", page=2, bbox={"x0": 10, "x1": 100, "y0": 20, "y1": 160}, rows=[["B", "2"]]),
    ]

    linked = link_cross_page_table_documents(docs)

    assert len(linked) == 1
    assert linked[0].metadata["cross_page_table_link"]["merged_count"] == 2
    assert linked[0].metadata["cross_page_table_link"]["pages"] == [1, 2]
    assert linked[0].metadata["table_extraction"]["row_count"] == 2
    assert "| B | 2 |" in linked[0].page_content


def test_link_cross_page_table_documents_keeps_mismatched_columns_separate() -> None:
    docs = [
        _table_doc("t1", page=1, bbox={"x0": 10, "x1": 100, "y0": 780, "y1": 950}, rows=[["A", "1"]]),
        _table_doc("t2", page=2, bbox={"x0": 10, "x1": 100, "y0": 20, "y1": 160}, rows=[["B", "2"]]),
    ]
    docs[1].metadata["table_columns"] = ["Other", "Value"]
    docs[1].metadata["table_extraction"]["columns"] = ["Other", "Value"]

    linked = link_cross_page_table_documents(docs)

    assert len(linked) == 2
