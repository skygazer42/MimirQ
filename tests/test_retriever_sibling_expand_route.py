from __future__ import annotations

from uuid import UUID, uuid4


class _FakeChunk:
    def __init__(
        self,
        *,
        chunk_id: UUID,
        tenant_id: UUID,
        document_id: UUID,
        chunk_index: int,
        content: str,
        header_path: str = "Section A",
    ) -> None:
        self.id = chunk_id
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.page_number = None
        self.start_char = None
        self.end_char = None
        self.doc_metadata = {"header_path": header_path}


class _FakeQuery:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self._chunks = list(chunks)

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN201
        return list(self._chunks)


class _FakeSession:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self._chunks = list(chunks)

    def query(self, *_args, **_kwargs):  # noqa: ANN001
        return _FakeQuery(self._chunks)

    def close(self) -> None:
        return None


def test_retriever_routes_short_documents_to_sibling_expand(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "RAG_CONTEXT_NEIGHBOR_WINDOW", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_NEIGHBOR_MAX_ADDED", 10, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_SIBLING_EXPAND_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_SIBLING_SHORT_DOC_MAX_CHUNKS", 8, raising=False)

    tenant_id = uuid4()
    document_id = uuid4()
    anchor_id = uuid4()

    db_chunks = [
        _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=document_id, chunk_index=0, content="zero"),
        _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=document_id, chunk_index=1, content="one"),
        _FakeChunk(chunk_id=anchor_id, tenant_id=tenant_id, document_id=document_id, chunk_index=2, content="two"),
        _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=document_id, chunk_index=3, content="three"),
        _FakeChunk(chunk_id=uuid4(), tenant_id=tenant_id, document_id=document_id, chunk_index=4, content="four"),
    ]

    monkeypatch.setattr("app.rag.retriever.SessionLocal", lambda: _FakeSession(db_chunks))

    retriever = HybridRetriever(tenant_id=tenant_id)
    results = [
        {
            "chunk_id": str(anchor_id),
            "content": "two",
            "metadata": {
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "chunk_index": 2,
                "chunk_id": str(anchor_id),
                "header_path": "Section A",
            },
            "score": 1.0,
        }
    ]

    out = retriever._expand_results_with_neighbors(results)
    assert [item.get("content") for item in out] == ["zero", "one", "two", "three", "four"]
    sibling_roles = [str((item.get("metadata") or {}).get("retrieval_role") or "") for item in out]
    assert sibling_roles.count("sibling") == 4
