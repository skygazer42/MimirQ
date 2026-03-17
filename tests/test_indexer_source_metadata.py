from uuid import UUID

from app.services.indexer import Indexer
from app.types.indexing import ChunkInput


def test_indexer_index_chunks_sets_source_metadata_from_default_source():
    class _DummyIndexer:
        vector_docs = None
        persisted_chunks = None

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return False

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs = vector_docs
            return [None] * len(vector_docs)

        def _persist_document_chunks(self, **kwargs):  # noqa: ANN001
            self.persisted_chunks = kwargs.get("chunks")
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()
    doc_id = UUID(int=1)
    tenant_id = UUID(int=2)
    chunks = [ChunkInput(content="hello", metadata={})]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=None,
    )

    assert dummy.vector_docs[0]["metadata"]["source"] == "orig.pdf"
    assert dummy.persisted_chunks[0].metadata["source"] == "orig.pdf"


def test_indexer_index_chunks_does_not_override_existing_source():
    class _DummyIndexer:
        vector_docs = None

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return False

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs = vector_docs
            return [None] * len(vector_docs)

        def _persist_document_chunks(self, **_kwargs):  # noqa: ANN001
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()
    doc_id = UUID(int=1)
    tenant_id = UUID(int=2)
    chunks = [ChunkInput(content="hello", metadata={"source": "keep.md"})]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source="ignored.pdf",
        commit=False,
        options=None,
    )

    assert dummy.vector_docs[0]["metadata"]["source"] == "keep.md"


def test_indexer_index_chunks_backfills_hierarchy_and_adjacency_metadata() -> None:
    class _DummyIndexer:
        vector_docs = None
        persisted_chunks = None

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return False

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs = vector_docs
            return [None] * len(vector_docs)

        def _persist_document_chunks(self, **kwargs):  # noqa: ANN001
            self.persisted_chunks = kwargs.get("chunks")
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()
    doc_id = UUID(int=11)
    tenant_id = UUID(int=22)
    chunks = [
        ChunkInput(content="parent", metadata={"chunk_role": "parent", "parent_id": "p1"}),
        ChunkInput(content="child", metadata={"chunk_role": "child", "parent_id": "p1"}),
    ]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source="orig.md",
        commit=False,
        options=None,
    )

    m0 = dummy.vector_docs[0]["metadata"]
    m1 = dummy.vector_docs[1]["metadata"]
    assert m0["hierarchy_node_key"] == m0["chunk_key"]
    assert m0["hierarchy_family_key"]
    assert m0["hierarchy_sibling_index"] == 0
    assert m0["hierarchy_prev_sibling_key"] is None
    assert m0["hierarchy_next_sibling_key"] == f"{doc_id}:1"
    assert m1["hierarchy_parent_key"] == "p1"
    assert m1["hierarchy_sibling_index"] == 1
    assert m1["hierarchy_prev_sibling_key"] == f"{doc_id}:0"
    assert m1["hierarchy_next_sibling_key"] is None


def test_indexer_index_chunks_backfills_hierarchy_overlay_metadata():
    class _DummyIndexer:
        vector_docs = None
        persisted_chunks = None

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return False

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs = vector_docs
            return [None] * len(vector_docs)

        def _persist_document_chunks(self, **kwargs):  # noqa: ANN001
            self.persisted_chunks = kwargs.get("chunks")
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()
    doc_id = UUID(int=11)
    tenant_id = UUID(int=12)
    chunks = [
        ChunkInput(content="hello", metadata={}),
        ChunkInput(content="world", metadata={}),
    ]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=None,
    )

    metas = [c.metadata for c in dummy.persisted_chunks]
    assert metas[0]["hierarchy_basis"] == "chunk_sequence"
    assert metas[0]["hierarchy_level"] == "chunk"
    assert metas[0]["hierarchy_node_key"] == f"{doc_id}:0"
    assert metas[0]["hierarchy_family_key"] == f"{doc_id}:0"
    assert metas[0]["hierarchy_prev_sibling_key"] is None
    assert metas[0]["hierarchy_next_sibling_key"] == f"{doc_id}:1"

    assert metas[1]["hierarchy_basis"] == "chunk_sequence"
    assert metas[1]["hierarchy_level"] == "chunk"
    assert metas[1]["hierarchy_node_key"] == f"{doc_id}:1"
    assert metas[1]["hierarchy_family_key"] == f"{doc_id}:1"
    assert metas[1]["hierarchy_prev_sibling_key"] == f"{doc_id}:0"
    assert metas[1]["hierarchy_next_sibling_key"] is None

    assert dummy.vector_docs[0]["metadata"]["hierarchy_node_key"] == f"{doc_id}:0"
    assert dummy.vector_docs[1]["metadata"]["hierarchy_node_key"] == f"{doc_id}:1"
