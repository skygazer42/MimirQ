from __future__ import annotations

from uuid import uuid4

from app.rag.retrieval.sibling_expand import expand_document_siblings, select_document_expansion_mode


class _FakeChunk:
    def __init__(self, *, chunk_id, tenant_id, document_id, chunk_index, content, header_path="Section A"):  # noqa: ANN001
        self.id = chunk_id
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.page_number = None
        self.start_char = None
        self.end_char = None
        self.doc_metadata = {"header_path": header_path}


def test_select_document_expansion_mode_prefers_sibling_for_short_docs() -> None:
    assert select_document_expansion_mode(total_chunks=5, short_doc_max_chunks=8) == "sibling"
    assert select_document_expansion_mode(total_chunks=30, short_doc_max_chunks=8) == "neighbor"


def test_expand_document_siblings_returns_whole_short_document_in_order() -> None:
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

    out = expand_document_siblings(
        results=[
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
        ],
        document_chunks_by_doc={str(document_id): db_chunks},
        short_doc_ids={str(document_id)},
        max_added=10,
    )

    assert [item.get("content") for item in out] == ["zero", "one", "two", "three", "four"]
    assert [str((item.get("metadata") or {}).get("retrieval_role") or "") for item in out] == [
        "sibling",
        "sibling",
        "",
        "sibling",
        "sibling",
    ]

