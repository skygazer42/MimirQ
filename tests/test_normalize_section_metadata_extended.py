from __future__ import annotations


def test_normalize_section_metadata_uses_minutes_section_title() -> None:
    from app.rag.core.metadata import normalize_section_metadata

    meta = {"minutes_section_title": "Action Items"}
    out = normalize_section_metadata(meta)
    assert out.get("header_path") == "Action Items"


def test_normalize_section_metadata_uses_sheet_name() -> None:
    from app.rag.core.metadata import normalize_section_metadata

    meta = {"sheet_name": "Sheet A"}
    out = normalize_section_metadata(meta)
    assert out.get("header_path") == "Sheet A"


def test_normalize_section_metadata_uses_table_title() -> None:
    from app.rag.core.metadata import normalize_section_metadata

    meta = {"table_title": "Table 1: Orders"}
    out = normalize_section_metadata(meta)
    assert out.get("header_path") == "Table 1: Orders"

