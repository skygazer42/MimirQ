from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.retriever import HybridRetriever
from app.services.indexer import Indexer
from app.types.indexing import ChunkInput


def test_indexer_injects_embedding_space_hash_into_chunk_metadata() -> None:
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

    expected = current_embedding_space_hash()
    assert dummy.vector_docs[0]["metadata"]["embedding_space_hash"] == expected
    assert dummy.persisted_chunks[0].metadata["embedding_space_hash"] == expected


class _FakeChunk:
    def __init__(
        self,
        *,
        tenant_id,
        document_id,
        chunk_index: int,
        content: str,
        chunk_id=None,
        doc_metadata: dict | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.id = chunk_id or uuid4()
        self.page_number = None
        self.start_char = None
        self.end_char = None
        self.doc_metadata = doc_metadata or {}


class _FakeQuery:
    def __init__(self, results: list[_FakeChunk]) -> None:
        self._results = results

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._results)


class _FakeSession:
    def __init__(self, results: list[_FakeChunk]) -> None:
        self._results = results

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._results)

    def close(self):
        return None


def test_retriever_filters_vector_hits_from_other_embedding_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    current = current_embedding_space_hash()
    other = current + "x"

    db_chunk = _FakeChunk(
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=0,
        content="DB CONTENT",
        chunk_id=chunk_id,
        doc_metadata={"embedding_space_hash": other},
    )
    monkeypatch.setattr("app.rag.retriever.SessionLocal", lambda: _FakeSession([db_chunk]))

    retriever = HybridRetriever()
    results = [
        {
            "chunk_id": str(chunk_id),
            "content": "VECTOR CONTENT",
            # Milvus vector hits include `metadata.score`, which we use to detect vector-only enforcement.
            "metadata": {
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "chunk_index": 0,
                "score": 0.9,
            },
            "score": 0.9,
        }
    ]

    out = retriever._enrich_results_with_db_metadata(results)
    assert out == []

