from __future__ import annotations

from langchain_core.documents import Document


def _mk(
    *,
    document_id: str,
    chunk_index: int,
    node_key: str,
    parent_key: str | None,
    prev_key: str | None = None,
    next_key: str | None = None,
    chunk_id: str | None = None,
    score: float = 1.0,
    record_key: str | None = None,
) -> Document:
    meta = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "chunk_id": chunk_id or f"{document_id}:{chunk_index}",
        "hierarchy_node_key": node_key,
        # Explicit key presence: don't fall back to parent_id in helpers.
        "hierarchy_parent_key": parent_key,
        "hierarchy_prev_sibling_key": prev_key,
        "hierarchy_next_sibling_key": next_key,
        "score": float(score),
    }
    if record_key:
        meta["_record_identity"] = {
            "schema": "mimirq.record_identity.v1",
            "key": record_key,
            "fields": {"source_record_id": record_key},
        }
    return Document(page_content=node_key, metadata=meta, id=meta["chunk_id"])


def test_expand_hierarchy_context_adds_parent_and_siblings_in_order() -> None:
    from app.rag.retrieval.hierarchy_expand import expand_hierarchy_context

    anchor = _mk(
        document_id="d1",
        chunk_index=1,
        node_key="c1",
        parent_key="p",
        prev_key="c0",
        next_key="c2",
        chunk_id="c1id",
        score=2.0,
    )
    parent = _mk(
        document_id="d1",
        chunk_index=10,
        node_key="p",
        parent_key=None,
        chunk_id="pid",
        score=0.1,
    )
    prev_sib = _mk(
        document_id="d1",
        chunk_index=0,
        node_key="c0",
        parent_key="p",
        next_key="c1",
        chunk_id="c0id",
        score=0.1,
    )
    next_sib = _mk(
        document_id="d1",
        chunk_index=2,
        node_key="c2",
        parent_key="p",
        prev_key="c1",
        chunk_id="c2id",
        score=0.1,
    )

    store = {
        ("d1", "p"): parent,
        ("d1", "c0"): prev_sib,
        ("d1", "c2"): next_sib,
    }

    def fetch(pairs):  # noqa: ANN001
        return {p: store[p] for p in pairs if p in store}

    out, meta = expand_hierarchy_context(
        [anchor],
        parent_depth=1,
        sibling_window=1,
        fetch_by_key=fetch,
        max_added_docs=20,
    )

    assert [d.page_content for d in out] == ["p", "c0", "c1", "c2"]
    assert meta["enabled"] is True
    assert meta["added_docs"] == 3
    assert meta["added_parents"] == 1
    assert meta["added_siblings"] == 2

    # Expansion docs should carry role + neighbor_of for provenance.
    roles = [str((d.metadata or {}).get("retrieval_role") or "") for d in out]
    assert roles[0] == "hierarchy_parent"
    assert roles[1] == "hierarchy_sibling"
    assert roles[2] == ""  # anchor unchanged
    assert roles[3] == "hierarchy_sibling"
    assert (out[0].metadata or {}).get("neighbor_of") == "c1id"


def test_expand_hierarchy_context_does_not_duplicate_original_docs() -> None:
    from app.rag.retrieval.hierarchy_expand import expand_hierarchy_context

    anchor = _mk(
        document_id="d1",
        chunk_index=1,
        node_key="c1",
        parent_key="p",
        prev_key="c0",
        next_key="c2",
        chunk_id="c1id",
        score=1.0,
    )
    # c0 is already in original docs_list; it should not be re-inserted as an expansion.
    c0_already = _mk(
        document_id="d1",
        chunk_index=0,
        node_key="c0",
        parent_key="p",
        next_key="c1",
        chunk_id="c0id",
        score=0.5,
    )
    c2 = _mk(
        document_id="d1",
        chunk_index=2,
        node_key="c2",
        parent_key="p",
        prev_key="c1",
        chunk_id="c2id",
        score=0.1,
    )

    store = {
        ("d1", "c0"): c0_already,
        ("d1", "c2"): c2,
    }

    def fetch(pairs):  # noqa: ANN001
        return {p: store[p] for p in pairs if p in store}

    out, meta = expand_hierarchy_context(
        [c0_already, anchor],
        parent_depth=0,
        sibling_window=1,
        fetch_by_key=fetch,
        max_added_docs=20,
    )

    assert [d.page_content for d in out] == ["c0", "c1", "c2"]
    assert meta["enabled"] is True
    assert meta["added_docs"] == 1


def test_expand_hierarchy_context_does_not_cross_record_identity_for_siblings() -> None:
    from app.rag.retrieval.hierarchy_expand import expand_hierarchy_context

    anchor = _mk(
        document_id="d1",
        chunk_index=1,
        node_key="record-b",
        parent_key=None,
        prev_key="record-a",
        next_key="record-c",
        chunk_id="bid",
        score=1.0,
        record_key="record-b",
    )
    prev_sib = _mk(
        document_id="d1",
        chunk_index=0,
        node_key="record-a",
        parent_key=None,
        next_key="record-b",
        chunk_id="aid",
        score=0.1,
        record_key="record-a",
    )
    next_sib = _mk(
        document_id="d1",
        chunk_index=2,
        node_key="record-c",
        parent_key=None,
        prev_key="record-b",
        chunk_id="cid",
        score=0.1,
        record_key="record-c",
    )

    store = {
        ("d1", "record-a"): prev_sib,
        ("d1", "record-c"): next_sib,
    }

    def fetch(pairs):  # noqa: ANN001
        return {p: store[p] for p in pairs if p in store}

    out, meta = expand_hierarchy_context(
        [anchor],
        parent_depth=0,
        sibling_window=1,
        fetch_by_key=fetch,
        max_added_docs=20,
    )

    assert [d.page_content for d in out] == ["record-b"]
    assert meta["enabled"] is True
    assert meta["added_docs"] == 0
    assert meta["skipped_cross_record_siblings"] == 2
