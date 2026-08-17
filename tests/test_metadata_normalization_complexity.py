from app.rag.core.hashing import stable_hash
from app.rag.core.metadata import (
    ensure_hierarchy_overlay_metadata,
    infer_chunk_structure,
    normalize_section_metadata,
)


def test_infer_chunk_structure_preserves_existing_fields_and_detects_lists_and_tables() -> None:
    metadata = {
        "structure": {"custom": {"kind": "kept"}},
        "sheet_name": " Revenue ",
        "table_header": " Quarterly totals ",
    }

    result = infer_chunk_structure(
        metadata,
        "- parent\n  * child\n    1. grandchild\nplain text",
    )

    assert result is metadata
    assert result["structure"] == {
        "custom": {"kind": "kept"},
        "list": {"item_count": 3, "min_level": 0, "max_level": 2},
        "table": {"sheet_name": "Revenue", "title": "Quarterly totals"},
    }


def test_infer_chunk_structure_uses_sheet_as_title_but_ignores_meta_sheet() -> None:
    assert infer_chunk_structure({"sheet_name": " Data "}, "")["structure"] == {
        "table": {"sheet_name": "Data", "title": "Data"}
    }
    assert infer_chunk_structure({"sheet_name": "_meta"}, "") == {"sheet_name": "_meta"}
    assert infer_chunk_structure([], "- item") == {}


def test_normalize_section_metadata_preserves_precedence_and_outline_cleanup() -> None:
    existing = {"header_path": " Existing ", "outline_path_str": "ignored"}
    assert normalize_section_metadata(existing) is existing
    assert existing["header_path"] == " Existing "

    outlined = {"outline_path": [" Intro ", "", 2]}
    assert normalize_section_metadata(outlined) == {
        "outline_path": ["Intro", "2"],
        "outline_path_str": "Intro / 2",
        "header_path": "Intro / 2",
    }

    markdown = {
        "sheet_name": "_meta",
        "header_1": " Guide ",
        "header_2": None,
        "header_3": 0,
        "header_4": " Setup ",
    }
    assert normalize_section_metadata(markdown)["header_path"] == "Guide > 0 > Setup"


def test_normalize_section_metadata_uses_fallback_priority() -> None:
    assert normalize_section_metadata({"outline_path_str": " Outline "})["header_path"] == "Outline"
    assert normalize_section_metadata({"header_context": " Context "})["header_path"] == "Context"
    assert normalize_section_metadata({"minutes_section_title": " Minutes "})["header_path"] == "Minutes"
    assert normalize_section_metadata({"sheet_name": " Sheet "})["header_path"] == "Sheet"
    assert normalize_section_metadata({"table_title": " Table "})["header_path"] == "Table"
    assert normalize_section_metadata([]) == {}


def test_ensure_hierarchy_overlay_metadata_builds_parent_family_and_adjacency() -> None:
    metadata = {
        "chunk_strategy": "parent_child",
        "parent_id": "parent-1",
    }

    result = ensure_hierarchy_overlay_metadata(
        metadata,
        document_id="doc-1",
        chunk_index=2,
        total_chunks=4,
    )

    assert result is metadata
    assert result == {
        "chunk_strategy": "parent_child",
        "parent_id": "parent-1",
        "chunk_key": "doc-1:2",
        "hierarchy_node_key": "doc-1:2",
        "hierarchy_parent_key": "parent-1",
        "hierarchy_level": "child",
        "hierarchy_basis": "parent_child",
        "hierarchy_family_key": stable_hash("hf:doc-1:parent-1", length=32),
        "hierarchy_sibling_index": 2,
        "prev_chunk_index": 1,
        "prev_chunk_key": "doc-1:1",
        "hierarchy_prev_sibling_key": "doc-1:1",
        "next_chunk_index": 3,
        "next_chunk_key": "doc-1:3",
        "hierarchy_next_sibling_key": "doc-1:3",
    }


def test_ensure_hierarchy_overlay_metadata_respects_explicit_parent_and_neighbors() -> None:
    metadata = {
        "hierarchy_parent_key": None,
        "parent_id": "legacy-parent",
        "chunk_role": "parent",
        "chunk_strategy": "hierarchical_markdown",
        "prev_chunk_index": "bad",
        "next_chunk_index": -1,
    }

    result = ensure_hierarchy_overlay_metadata(
        metadata,
        document_id="doc-2",
        chunk_index=-3,
        total_chunks=-1,
    )

    assert result["chunk_key"] == "doc-2:0"
    assert result["hierarchy_parent_key"] is None
    assert result["hierarchy_level"] == "parent"
    assert result["hierarchy_basis"] == "markdown_structure"
    assert result["hierarchy_family_key"] == "doc-2:0"
    assert result["hierarchy_sibling_index"] == 0
    assert result["prev_chunk_index"] == "bad"
    assert result["hierarchy_prev_sibling_key"] is None
    assert result["next_chunk_index"] == -1
    assert result["hierarchy_next_sibling_key"] is None
    assert ensure_hierarchy_overlay_metadata([], document_id="", chunk_index=0) == {}
