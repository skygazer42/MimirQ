from __future__ import annotations


def test_infer_chunk_structure_detects_list_counts_and_levels() -> None:
    from app.rag.core.metadata import infer_chunk_structure

    meta: dict[str, object] = {}
    content = "\n".join(
        [
            "- one",
            "  - two",
            "    - three",
            "1. four",
            "   1) five",
        ]
    )
    out = infer_chunk_structure(meta, content)
    structure = out.get("structure") or {}
    assert isinstance(structure, dict)

    list_info = structure.get("list") or {}
    assert isinstance(list_info, dict)
    assert list_info.get("item_count") == 5
    assert list_info.get("min_level") == 0
    assert list_info.get("max_level") == 2


def test_infer_chunk_structure_sets_table_fields_from_metadata() -> None:
    from app.rag.core.metadata import infer_chunk_structure

    meta: dict[str, object] = {"sheet_name": "Sheet 1", "table_header": "ID | Name"}
    out = infer_chunk_structure(meta, "ID | Name\n1 | Alice")
    structure = out.get("structure") or {}
    assert isinstance(structure, dict)

    table_info = structure.get("table") or {}
    assert isinstance(table_info, dict)
    assert table_info.get("sheet_name") == "Sheet 1"
    assert table_info.get("title") == "ID | Name"

