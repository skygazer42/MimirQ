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


def test_hierarchical_chunk_markdown_emits_stable_family_and_sibling_keys() -> None:
    from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown

    markdown = "Alpha one. Alpha two.\n\nBeta only."

    out1 = hierarchical_chunk_markdown(markdown)
    out2 = hierarchical_chunk_markdown(markdown)

    paragraphs1 = out1["paragraphs"]
    paragraphs2 = out2["paragraphs"]
    assert len(paragraphs1) == 2
    assert len(paragraphs2) == 2

    p1a, p2a = paragraphs1
    p1b, p2b = paragraphs2

    assert p1a["hierarchy_basis"] == "markdown_hierarchy"
    assert p1a["hierarchy_level"] == "paragraph"
    assert p1a["hierarchy_family_key"] == p1a["hierarchy_node_key"]
    assert p1a["hierarchy_prev_sibling_key"] is None
    assert p1a["hierarchy_next_sibling_key"] == p2a["hierarchy_node_key"]
    assert p2a["hierarchy_prev_sibling_key"] == p1a["hierarchy_node_key"]
    assert p2a["hierarchy_next_sibling_key"] is None

    assert p1a["hierarchy_node_key"] == p1b["hierarchy_node_key"]
    assert p2a["hierarchy_node_key"] == p2b["hierarchy_node_key"]

    alpha_sentences1 = [s for s in out1["sentences"] if s.get("parent_id") == p1a["id"]]
    alpha_sentences2 = [s for s in out2["sentences"] if s.get("parent_id") == p1b["id"]]
    assert len(alpha_sentences1) == 2
    assert len(alpha_sentences2) == 2

    assert all(s["hierarchy_basis"] == "markdown_hierarchy" for s in alpha_sentences1)
    assert all(s["hierarchy_level"] == "sentence" for s in alpha_sentences1)
    assert all(s["hierarchy_parent_key"] == p1a["hierarchy_node_key"] for s in alpha_sentences1)
    assert all(s["hierarchy_family_key"] == p1a["hierarchy_node_key"] for s in alpha_sentences1)
    assert alpha_sentences1[0]["hierarchy_prev_sibling_key"] is None
    assert alpha_sentences1[0]["hierarchy_next_sibling_key"] == alpha_sentences1[1]["hierarchy_node_key"]
    assert alpha_sentences1[1]["hierarchy_prev_sibling_key"] == alpha_sentences1[0]["hierarchy_node_key"]
    assert alpha_sentences1[1]["hierarchy_next_sibling_key"] is None

    assert [s["hierarchy_node_key"] for s in alpha_sentences1] == [s["hierarchy_node_key"] for s in alpha_sentences2]
