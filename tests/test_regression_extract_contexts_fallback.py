from __future__ import annotations

from uuid import uuid4


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self) -> None:
        self._chunk_rows: list[object] = []

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", str(model))
        if name == "DocumentChunk":
            return _FakeQuery(self._chunk_rows)
        raise AssertionError(f"unexpected model in query(): {name}")


def test_extract_contexts_falls_back_to_quote_for_missing_chunk_rows() -> None:
    from app.rag.evaluation.ragas import _extract_contexts

    tenant_id = uuid4()
    doc_id = uuid4()
    missing_chunk_id = uuid4()

    db = _FakeDB()
    contexts = _extract_contexts(
        db=db,
        tenant_id=tenant_id,
        account_id="acct",
        citations=[
            {
                "chunk_id": str(missing_chunk_id),
                "document_id": str(doc_id),
                "quote": "fallback quote text",
                "hit_type": "tag",
            }
        ],
        allowed_document_ids=[doc_id],
        dataset_id=None,
        max_context_chars=200,
    )
    assert contexts == ["fallback quote text"]


def test_extract_contexts_respects_allowed_document_ids_for_fallback_text() -> None:
    from app.rag.evaluation.ragas import _extract_contexts

    tenant_id = uuid4()
    doc_id = uuid4()
    missing_chunk_id = uuid4()

    db = _FakeDB()
    contexts = _extract_contexts(
        db=db,
        tenant_id=tenant_id,
        account_id="acct",
        citations=[
            {
                "chunk_id": str(missing_chunk_id),
                "document_id": str(doc_id),
                "quote": "should not leak",
                "hit_type": "tag",
            }
        ],
        allowed_document_ids=[uuid4()],  # different doc
        dataset_id=None,
        max_context_chars=200,
    )
    assert contexts == []

