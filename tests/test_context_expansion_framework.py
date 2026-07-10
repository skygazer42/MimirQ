
from uuid import uuid4

from langchain_core.documents import Document


class _FakeChunk:
    def __init__(
        self,
        *,
        chunk_id,
        tenant_id,
        document_id,
        chunk_index: int,
        content: str,
        header_path: str = "Section A",
    ) -> None:  # noqa: ANN001
        self.id = chunk_id
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.page_number = None
        self.start_char = None
        self.end_char = None
        self.doc_metadata = {"header_path": header_path}


def test_expand_ranked_chunk_results_unifies_sibling_and_neighbor_strategies() -> None:
    from app.rag.retrieval.context_expansion import expand_ranked_chunk_results

    tenant_id = uuid4()
    short_doc_id = uuid4()
    long_doc_id = uuid4()

    short_anchor_id = uuid4()
    long_anchor_id = uuid4()

    short_chunks = [
        _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=short_doc_id, chunk_index=0, content="short-0"),
        _FakeChunk(chunk_id=short_anchor_id, tenant_id=tenant_id, document_id=short_doc_id, chunk_index=1, content="short-1"),
        _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=short_doc_id, chunk_index=2, content="short-2"),
    ]
    long_left = _FakeChunk(
        chunk_id=uuid4(),
        tenant_id=tenant_id,
        document_id=long_doc_id,
        chunk_index=0,
        content="long-0",
    )
    long_anchor = _FakeChunk(
        chunk_id=long_anchor_id,
        tenant_id=tenant_id,
        document_id=long_doc_id,
        chunk_index=1,
        content="long-1",
    )
    long_right = _FakeChunk(
        chunk_id=uuid4(),
        tenant_id=tenant_id,
        document_id=long_doc_id,
        chunk_index=2,
        content="long-2",
    )

    out, meta = expand_ranked_chunk_results(
        results=[
            {
                "chunk_id": str(short_anchor_id),
                "content": "short-1",
                "metadata": {
                    "tenant_id": str(tenant_id),
                    "document_id": str(short_doc_id),
                    "chunk_index": 1,
                    "chunk_id": str(short_anchor_id),
                    "header_path": "Section A",
                },
                "score": 1.0,
            },
            {
                "chunk_id": str(long_anchor_id),
                "content": "long-1",
                "metadata": {
                    "tenant_id": str(tenant_id),
                    "document_id": str(long_doc_id),
                    "chunk_index": 1,
                    "chunk_id": str(long_anchor_id),
                    "header_path": "Section A",
                },
                "score": 0.9,
            },
        ],
        window=1,
        max_added=10,
        sibling_max_added=10,
        document_chunks_by_doc={str(short_doc_id): short_chunks, str(long_doc_id): [long_left, long_anchor, long_right]},
        short_doc_ids={str(short_doc_id)},
        neighbors_by_pair={
            (str(long_doc_id), 0): long_left,
            (str(long_doc_id), 2): long_right,
        },
    )

    assert [item.get("content") for item in out] == ["short-0", "short-1", "short-2", "long-0", "long-1", "long-2"]
    assert meta["added_docs"] == 4
    assert meta["sibling_added"] == 2
    assert meta["neighbor_added"] == 2
    assert set(meta["strategies_used"]) == {"neighbor", "sibling"}


def test_expand_ranked_chunk_results_can_expand_neighbors_by_score_band() -> None:
    from app.rag.retrieval.context_expansion import expand_ranked_chunk_results

    tenant_id = uuid4()
    doc_id = uuid4()
    high_anchor_id = uuid4()
    low_anchor_id = uuid4()
    c8 = _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=doc_id, chunk_index=8, content="c8")
    c9 = _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=doc_id, chunk_index=9, content="c9")
    c11 = _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=doc_id, chunk_index=11, content="c11")
    c12 = _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=doc_id, chunk_index=12, content="c12")
    c19 = _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=doc_id, chunk_index=19, content="c19")
    c21 = _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=doc_id, chunk_index=21, content="c21")

    out, meta = expand_ranked_chunk_results(
        results=[
            {
                "chunk_id": str(high_anchor_id),
                "content": "c10",
                "score": 0.91,
                "metadata": {
                    "tenant_id": str(tenant_id),
                    "document_id": str(doc_id),
                    "chunk_id": str(high_anchor_id),
                    "chunk_index": 10,
                    "header_path": "Section A",
                },
            },
            {
                "chunk_id": str(low_anchor_id),
                "content": "c20",
                "score": 0.2,
                "metadata": {
                    "tenant_id": str(tenant_id),
                    "document_id": str(doc_id),
                    "chunk_id": str(low_anchor_id),
                    "chunk_index": 20,
                    "header_path": "Section A",
                },
            },
        ],
        window=2,
        max_added=10,
        sibling_max_added=0,
        neighbors_by_pair={
            (str(doc_id), 8): c8,
            (str(doc_id), 9): c9,
            (str(doc_id), 11): c11,
            (str(doc_id), 12): c12,
            (str(doc_id), 19): c19,
            (str(doc_id), 21): c21,
        },
        score_driven=True,
        high_threshold=0.7,
        mid_threshold=0.4,
        high_span=2,
        mid_span=1,
    )

    contents = [item.get("content") for item in out]
    assert contents == ["c10", "c20", "c8", "c9", "c11", "c12"]
    assert "c19" not in contents
    assert "c21" not in contents
    assert meta["strategy"] == "neighbor_score"
    assert meta["score_driven"] is True
    assert meta["neighbor_added"] == 4


def test_expand_hierarchy_documents_flows_through_unified_framework() -> None:
    from app.rag.retrieval.context_expansion import expand_hierarchy_documents

    anchor = Document(
        page_content="anchor",
        metadata={
            "document_id": "d1",
            "chunk_index": 1,
            "chunk_id": "c1id",
            "hierarchy_node_key": "c1",
            "hierarchy_parent_key": "p",
            "score": 1.0,
        },
        id="c1id",
    )
    parent = Document(
        page_content="parent",
        metadata={
            "document_id": "d1",
            "chunk_index": 10,
            "chunk_id": "pid",
            "hierarchy_node_key": "p",
            "hierarchy_parent_key": None,
            "score": 0.1,
        },
        id="pid",
    )

    out, meta = expand_hierarchy_documents(
        [anchor],
        parent_depth=1,
        sibling_window=0,
        fetch_by_key=lambda pairs: {pair: parent for pair in pairs if pair == ("d1", "p")},
        max_added_docs=10,
    )

    assert [doc.page_content for doc in out] == ["parent", "anchor"]
    assert meta["enabled"] is True
    assert meta["added_docs"] == 1
    assert meta["strategy"] == "hierarchy"
    assert meta["framework"] == "context_expansion"
