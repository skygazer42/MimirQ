from __future__ import annotations

from uuid import UUID

from app.services.indexer import Indexer
from app.types.indexing import ChunkInput, IndexingOptions


def test_indexer_writes_extra_field_aware_vectors_when_enabled() -> None:
    class _DummyIndexer:
        vector_docs_calls: list[list[dict]] = []
        persisted_chunks = None

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return True

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs_calls.append(list(vector_docs))
            return ["vid"] * len(vector_docs)

        def _persist_document_chunks(self, **kwargs):  # noqa: ANN001
            self.persisted_chunks = kwargs.get("chunks")
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()

    doc_id = UUID(int=1)
    tenant_id = UUID(int=2)
    chunks = [
        ChunkInput(
            content="hello world",
            metadata={
                "title": "Doc Title",
                "header_path": "H1 / H2",
            },
        )
    ]
    options = IndexingOptions(
        chunk_vector_enabled=True,
        bm25_index_enabled=False,
        embedding_context_prefix_enabled=False,
        embedding_field_aware_enabled=True,
    )

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=options,
    )

    # First call: body vectors (1 per chunk). Second call: extra field-aware vectors.
    assert len(dummy.vector_docs_calls) == 2
    body_docs = dummy.vector_docs_calls[0]
    extra_docs = dummy.vector_docs_calls[1]
    assert len(body_docs) == 1
    assert len(extra_docs) >= 1

    body_meta = body_docs[0]["metadata"] or {}
    base_chunk_id = str(body_meta.get("chunk_id") or "")
    assert base_chunk_id

    extra_chunk_ids = {str(d.get("metadata", {}).get("chunk_id") or "") for d in extra_docs}
    assert f"{base_chunk_id}:title" in extra_chunk_ids
    assert f"{base_chunk_id}:heading" in extra_chunk_ids

    # Persisted chunk metadata should record the flag (useful for audits/debug).
    persisted = dummy.persisted_chunks
    assert persisted and persisted[0].metadata.get("embedding_field_aware_enabled") is True

