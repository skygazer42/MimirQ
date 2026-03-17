from __future__ import annotations

from langchain_core.documents import Document


def _d(doc_id: str, idx: int, *, node_key: str, parent_key: str | None) -> Document:
    meta = {
        "document_id": doc_id,
        "chunk_index": idx,
        "hierarchy_node_key": node_key,
        # Use explicit field presence so orchestrator helpers don't fall back to parent_id.
        "hierarchy_parent_key": parent_key,
    }
    return Document(page_content=f"{node_key}", metadata=meta, id=f"{doc_id}:{idx}")


def test_hierarchy_tree_dedup_prefers_ancestor_even_if_ancestor_appears_later() -> None:
    from app.rag.retrieval.orchestrator import _apply_hierarchy_tree_dedup

    child1 = _d("d1", 0, node_key="c1", parent_key="p")
    child2 = _d("d1", 1, node_key="c2", parent_key="p")
    parent = _d("d1", 2, node_key="p", parent_key=None)

    out, meta = _apply_hierarchy_tree_dedup(
        [child1, child2, parent],
        refill=None,
        top_k=10,
        overfetch_factor=4,
    )

    assert [d.page_content for d in out] == ["p"]
    assert meta["enabled"] is True
    assert meta["removed_by_ancestor"] >= 2


def test_hierarchy_tree_dedup_keeps_descendants_when_no_ancestor_present() -> None:
    from app.rag.retrieval.orchestrator import _apply_hierarchy_tree_dedup

    child1 = _d("d1", 0, node_key="c1", parent_key="p")
    child2 = _d("d1", 1, node_key="c2", parent_key="p")

    out, meta = _apply_hierarchy_tree_dedup(
        [child1, child2],
        refill=None,
        top_k=10,
        overfetch_factor=4,
    )

    assert [d.page_content for d in out] == ["c1", "c2"]
    assert meta["enabled"] is True
    assert meta["removed_by_ancestor"] == 0


def test_hierarchy_tree_dedup_does_not_drop_self_parent() -> None:
    from app.rag.retrieval.orchestrator import _apply_hierarchy_tree_dedup

    # Historical/dirty metadata can contain parent_key == node_key; treat as root.
    parent_self = _d("d1", 0, node_key="p", parent_key="p")

    out, meta = _apply_hierarchy_tree_dedup(
        [parent_self],
        refill=None,
        top_k=10,
        overfetch_factor=4,
    )

    assert [d.page_content for d in out] == ["p"]
    assert meta["enabled"] is True
