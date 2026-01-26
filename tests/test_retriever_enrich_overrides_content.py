from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.rag.retriever import HybridRetriever


class _FakeChunk:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        chunk_index: int,
        content: str,
        chunk_id: UUID | None = None,
        doc_metadata: dict | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.id = chunk_id or uuid4()
        self.page_number = None
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
        self.closed = False

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._results)

    def close(self):
        self.closed = True


def test_enrich_results_overrides_vector_content_with_db_chunk_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    If vectors store embedding-only text (e.g. prefixed header context), we still want the DB
    chunk content for citations/highlighting.
    """
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    db_chunk = _FakeChunk(
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=0,
        content="DB CONTENT",
        chunk_id=chunk_id,
        doc_metadata={"source": "doc.txt"},
    )
    monkeypatch.setattr("app.rag.retriever.SessionLocal", lambda: _FakeSession([db_chunk]))

    retriever = HybridRetriever()
    results = [
        {
            "chunk_id": str(chunk_id),
            "content": "[Section] Header\nVECTOR CONTENT",
            "metadata": {"tenant_id": str(tenant_id), "document_id": str(document_id), "chunk_index": 0},
            "score": 0.9,
        }
    ]

    out = retriever._enrich_results_with_db_metadata(results)
    assert out[0]["content"] == "DB CONTENT"

