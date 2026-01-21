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

