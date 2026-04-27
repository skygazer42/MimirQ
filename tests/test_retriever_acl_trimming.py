from __future__ import annotations

from datetime import UTC, datetime
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
        self.start_char = None
        self.end_char = None
        self.doc_metadata = doc_metadata or {}
        self.disabled_at = None


class _FakeQuery:
    def __init__(self, results):  # noqa: ANN001
        self._results = results

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def all(self):
        return list(self._results)


class _FakeSession:
    def __init__(self, *, chunks, doc_rows):  # noqa: ANN001
        self._chunks = chunks
        self._doc_rows = doc_rows

    def query(self, *args, **_kwargs):  # noqa: ANN001
        # `_enrich_results_with_db_metadata` issues:
        # - query(DocumentChunk) -> model class
        # - query(DBDocument.id, DBDocument.dataset_id, DBDocument.status, DBDocument.doc_metadata, archived_at, disabled_at, publication_status)
        if len(args) == 1 and getattr(args[0], "__name__", "") == "DocumentChunk":
            return _FakeQuery(self._chunks)
        return _FakeQuery(self._doc_rows)

    def close(self):
        return None


def test_retriever_candidate_acl_trims_disallowed_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    doc_allowed = uuid4()
    doc_denied = uuid4()
    chunk_allowed = uuid4()
    chunk_denied = uuid4()

    chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=doc_allowed,
            chunk_index=0,
            content="allowed",
            chunk_id=chunk_allowed,
            doc_metadata={"pipeline_hash": "h"},
        ),
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=doc_denied,
            chunk_index=0,
            content="denied",
            chunk_id=chunk_denied,
            doc_metadata={"pipeline_hash": "h"},
        ),
    ]
    # (doc_id, dataset_id, status, doc_metadata)
    doc_rows = [
        (doc_allowed, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "published"),
        (doc_denied, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "published"),
    ]

    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: _FakeSession(chunks=chunks, doc_rows=doc_rows),
    )

    # Only allow `doc_allowed` for this account.
    def _fake_allowed_sets(_db, _tenant_id, _account_id, doc_ids, *, check_member=True):  # noqa: ANN001
        allowed = {doc_allowed}
        missing = set()
        return allowed & set(doc_ids), missing

    monkeypatch.setattr(
        "app.services.document_access.get_allowed_document_id_sets",
        _fake_allowed_sets,
        raising=True,
    )

    retriever = HybridRetriever(tenant_id=tenant_id, account_id="acct")
    results = [
        {
            "chunk_id": str(chunk_allowed),
            "content": "vector allowed",
            "metadata": {"document_id": str(doc_allowed), "chunk_index": 0},
            "score": 0.9,
        },
        {
            "chunk_id": str(chunk_denied),
            "content": "vector denied",
            "metadata": {"document_id": str(doc_denied), "chunk_index": 0},
            "score": 0.8,
        },
    ]

    stats: dict = {}
    out = retriever._enrich_results_with_db_metadata(results, stats=stats)
    assert len(out) == 1
    assert str(out[0]["metadata"]["document_id"]) == str(doc_allowed)
    assert stats["filtered_acl"] == 1
    assert stats["output_results"] == 1


def test_retriever_filters_archived_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=0,
            content="archived",
            chunk_id=chunk_id,
            doc_metadata={"pipeline_hash": "h"},
        )
    ]
    doc_rows = [
        (
            document_id,
            None,
            "completed",
            {"active_pipeline_ready": True, "pipeline_hash": "h"},
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
            "published",
        )
    ]

    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: _FakeSession(chunks=chunks, doc_rows=doc_rows),
    )

    retriever = HybridRetriever(tenant_id=tenant_id)
    results = [
        {
            "chunk_id": str(chunk_id),
            "content": "VECTOR CONTENT",
            "metadata": {"document_id": str(document_id), "chunk_index": 0},
            "score": 0.9,
        }
    ]

    stats: dict = {}
    out = retriever._enrich_results_with_db_metadata(results, stats=stats)
    assert out == []
    assert stats["filtered_not_ready"] == 1


def test_retriever_filters_disabled_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    disabled_chunk = _FakeChunk(
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=0,
        content="disabled chunk",
        chunk_id=chunk_id,
        doc_metadata={"pipeline_hash": "h"},
    )
    disabled_chunk.disabled_at = datetime(2026, 1, 2, tzinfo=UTC)

    chunks = [disabled_chunk]
    doc_rows = [
        (document_id, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "published"),
    ]

    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: _FakeSession(chunks=chunks, doc_rows=doc_rows),
    )

    retriever = HybridRetriever(tenant_id=tenant_id)
    results = [
        {
            "chunk_id": str(chunk_id),
            "content": "VECTOR CONTENT",
            "metadata": {"document_id": str(document_id), "chunk_index": 0},
            "score": 0.9,
        }
    ]

    stats: dict = {}
    out = retriever._enrich_results_with_db_metadata(results, stats=stats)
    assert out == []
    assert stats["filtered_not_ready"] == 1


def test_retriever_filters_non_published_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=0,
            content="draft doc",
            chunk_id=chunk_id,
            doc_metadata={"pipeline_hash": "h"},
        )
    ]
    doc_rows = [
        (document_id, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "draft"),
    ]

    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: _FakeSession(chunks=chunks, doc_rows=doc_rows),
    )

    retriever = HybridRetriever(tenant_id=tenant_id)
    results = [
        {
            "chunk_id": str(chunk_id),
            "content": "VECTOR CONTENT",
            "metadata": {"document_id": str(document_id), "chunk_index": 0},
            "score": 0.9,
        }
    ]

    stats: dict = {}
    out = retriever._enrich_results_with_db_metadata(results, stats=stats)
    assert out == []
    assert stats["filtered_not_ready"] == 1


def test_retriever_acl_escape_forged_metadata_document_id_does_not_bypass_db_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    doc_allowed = uuid4()
    doc_denied = uuid4()
    allowed_chunk_id = uuid4()
    denied_chunk_id = uuid4()

    chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=doc_allowed,
            chunk_index=0,
            content="allowed db chunk",
            chunk_id=allowed_chunk_id,
            doc_metadata={"pipeline_hash": "h"},
        ),
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=doc_denied,
            chunk_index=0,
            content="denied db chunk",
            chunk_id=denied_chunk_id,
            doc_metadata={"pipeline_hash": "h"},
        ),
    ]
    doc_rows = [
        (doc_allowed, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "published"),
        (doc_denied, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "published"),
    ]

    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: _FakeSession(chunks=chunks, doc_rows=doc_rows),
    )

    def _fake_allowed_sets(_db, _tenant_id, _account_id, doc_ids, *, check_member=True):  # noqa: ANN001
        allowed = {doc_allowed}
        return allowed & set(doc_ids), set()

    monkeypatch.setattr(
        "app.services.document_access.get_allowed_document_id_sets",
        _fake_allowed_sets,
        raising=True,
    )

    retriever = HybridRetriever(tenant_id=tenant_id, account_id="acct")
    results = [
        {
            # Real chunk belongs to denied doc, but vector metadata is forged to look allowed.
            "chunk_id": str(denied_chunk_id),
            "content": "forged vector content",
            "metadata": {"document_id": str(doc_allowed), "chunk_index": 0},
            "score": 0.9,
        }
    ]

    stats: dict = {}
    out = retriever._enrich_results_with_db_metadata(results, stats=stats)
    assert out == []
    assert stats["filtered_acl"] == 1
    assert stats["output_results"] == 0


def test_retriever_acl_escape_fails_closed_when_acl_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=0,
            content="allowed if acl works",
            chunk_id=chunk_id,
            doc_metadata={"pipeline_hash": "h"},
        ),
    ]
    doc_rows = [
        (document_id, None, "completed", {"active_pipeline_ready": True, "pipeline_hash": "h"}, None, None, "published"),
    ]

    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: _FakeSession(chunks=chunks, doc_rows=doc_rows),
    )

    def _raise_acl(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("acl backend unavailable")

    monkeypatch.setattr(
        "app.services.document_access.get_allowed_document_id_sets",
        _raise_acl,
        raising=True,
    )

    retriever = HybridRetriever(tenant_id=tenant_id, account_id="acct")
    results = [
        {
            "chunk_id": str(chunk_id),
            "content": "vector content",
            "metadata": {"document_id": str(document_id), "chunk_index": 0},
            "score": 0.9,
        }
    ]

    stats: dict = {}
    out = retriever._enrich_results_with_db_metadata(results, stats=stats)
    assert out == []
    assert stats["filtered_acl"] == 1
    assert stats["output_results"] == 0
