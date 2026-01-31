from __future__ import annotations

from app.rag.core.metadata import normalize_section_metadata


def test_normalize_section_metadata_sets_header_path_from_outline_path_str() -> None:
    meta = {"outline_path_str": "A / B"}
    out = normalize_section_metadata(meta)
    assert out.get("header_path") == "A / B"


def test_normalize_section_metadata_builds_header_path_from_outline_path_list() -> None:
    meta = {"outline_path": ["A", "B"]}
    out = normalize_section_metadata(meta)
    assert out.get("outline_path_str") == "A / B"
    assert out.get("header_path") == "A / B"


def test_normalize_section_metadata_uses_header_context_as_header_path() -> None:
    meta = {"header_context": "## Title"}
    out = normalize_section_metadata(meta)
    assert out.get("header_path") == "## Title"


def test_normalize_section_metadata_builds_header_path_from_markdown_headers() -> None:
    meta = {"header_1": "H1", "header_2": "H2"}
    out = normalize_section_metadata(meta)
    assert out.get("header_path") == "H1 > H2"

