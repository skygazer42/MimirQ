import asyncio
import importlib
import uuid
from types import SimpleNamespace

import pytest

from app.api.schemas.document import (
    DocumentChunkCreateRequest,
    DocumentChunkReembedRequest,
    DocumentChunkUpdateRequest,
)


class _QueryResult:
    def __init__(
        self,
        *,
        first_value=None,
        scalar_value=None,
        all_value=None,
        delete_value=1,
    ) -> None:
        self._first_value = first_value
        self._scalar_value = scalar_value
        self._all_value = list(all_value or [])
        self._delete_value = delete_value

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def first(self):  # noqa: ANN201
        return self._first_value

    def scalar(self):  # noqa: ANN201
        return self._scalar_value

    def all(self):  # noqa: ANN201
        return list(self._all_value)

    def delete(self, **_kwargs):  # noqa: ANN003, ANN201
        return self._delete_value


class _QueuedDB:
    def __init__(self, queries: list[_QueryResult]) -> None:
        self._queries = list(queries)
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commit_calls = 0
        self.refresh_calls: list[object] = []
        self.rollback_calls = 0

    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        if not self._queries:
            raise AssertionError("unexpected query call")
        return self._queries.pop(0)

    def add(self, value) -> None:  # noqa: ANN001
        self.added.append(value)

    def delete(self, value) -> None:  # noqa: ANN001
        self.deleted.append(value)

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, value) -> None:  # noqa: ANN001
        self.refresh_calls.append(value)

    def rollback(self) -> None:
        self.rollback_calls += 1


def _document(*, tenant_id: uuid.UUID, document_id: uuid.UUID, filename: str = "doc.txt") -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        status="completed",
        filename=filename,
        updated_at=None,
        chunk_count=0,
        total_characters=0,
        doc_metadata={
            "active_pipeline_hash": "active",
            "pipeline_hash": "active",
        },
    )


def _chunk(*, tenant_id: uuid.UUID, document_id: uuid.UUID, chunk_id: uuid.UUID | None = None) -> SimpleNamespace:
    cid = chunk_id or uuid.uuid4()
    return SimpleNamespace(
        id=cid,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=2,
        content="chunk body",
        page_number=1,
        start_char=0,
        end_char=10,
        disabled_at=None,
        vector_id="vector-before",
        doc_metadata={
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "chunk_id": str(cid),
            "chunk_index": 2,
            "doc_pipeline_key": f"{document_id}:active",
            "pipeline_hash": "active",
        },
    )


def test_manual_chunk_mutations_route_vector_ops_through_indexer_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.documents as documents_module
    from app.rag import retriever as retriever_module
    from app.services import indexer as indexer_module

    chunk_routes = importlib.import_module("app.api.v1.document_chunks_write")

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    account_id = "editor"
    document = _document(tenant_id=tenant_id, document_id=document_id)
    existing_chunk = _chunk(tenant_id=tenant_id, document_id=document_id)
    helper_calls: list[dict[str, object]] = []

    class _FakeIndexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            self._db = _db

        def upsert_document_chunk_vector(self, **kwargs):  # noqa: ANN003, ANN201
            helper_calls.append({"op": "upsert", **kwargs})
            return f"vector:{kwargs['metadata']['chunk_id']}"

        def delete_document_chunk_vectors(self, **kwargs) -> None:  # noqa: ANN003
            helper_calls.append({"op": "delete", **kwargs})

        def _update_bm25_for_chunks(self, **_kwargs) -> None:  # noqa: ANN003
            return None

        def delete_event_indexes_for_chunks(self, **_kwargs) -> None:  # noqa: ANN003
            return None

    async def _noop_drift(**_kwargs):  # noqa: ANN003, ANN202
        return ({"success": True}, [], None)

    monkeypatch.setattr(
        indexer_module,
        "get_vector_store",
        lambda: pytest.fail("routes must not call the default vector store directly"),
        raising=True,
    )
    monkeypatch.setattr(chunk_routes.documents_module, "Indexer", _FakeIndexer, raising=False)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_writable_for_chunk_ops", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(chunk_routes.documents_module, "audit_log_event", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(documents_module, "_normalize_index_consistency_strictness", lambda **_k: "best_effort", raising=True)
    monkeypatch.setattr(documents_module, "_build_index_channel_result", lambda **kwargs: kwargs, raising=True)
    monkeypatch.setattr(documents_module, "_build_chunk_index_operation_result", lambda **kwargs: {"success": True, **kwargs}, raising=True)
    monkeypatch.setattr(documents_module, "_persist_chunk_index_operation_result", lambda **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_record_chunk_index_drift", _noop_drift, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_resolve_active_doc_pipeline_key",
        lambda doc_id, _meta: f"{doc_id}:active",
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_get_document_for_chunk_ops", lambda *_a, **_k: document, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_get_chunk_for_chunk_ops",
        lambda *_a, **_k: existing_chunk,
        raising=True,
    )
    retriever_cls = type(retriever_module.hybrid_retriever)
    monkeypatch.setattr(
        retriever_cls,
        "remove_from_bm25_index_by_metadata_filter",
        lambda _self, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        retriever_cls,
        "upsert_bm25_documents",
        lambda _self, *_args, **_kwargs: None,
        raising=False,
    )

    create_db = _QueuedDB(
        [
            _QueryResult(first_value=document),
            _QueryResult(scalar_value=1),
            _QueryResult(first_value=(3, 42)),
        ]
    )
    created = chunk_routes.create_document_chunk(
        document_id=document_id,
        payload=DocumentChunkCreateRequest(content="new chunk", metadata={"source": "manual"}),
        tenant_id=tenant_id,
        account_id=account_id,
        db=create_db,
    )
    assert created.vector_id.startswith("vector:")
    assert helper_calls[0]["op"] == "upsert"
    assert helper_calls[0]["document_id"] == document_id
    assert helper_calls[0]["tenant_id"] == tenant_id
    assert helper_calls[0]["content"] == "new chunk"

    helper_calls.clear()
    patch_db = _QueuedDB([_QueryResult(first_value=document), _QueryResult(first_value=existing_chunk)])
    patched = chunk_routes.patch_document_chunk(
        document_id=document_id,
        chunk_id=existing_chunk.id,
        payload=DocumentChunkUpdateRequest(content="patched chunk"),
        tenant_id=tenant_id,
        account_id=account_id,
        db=patch_db,
    )
    assert patched.content == "patched chunk"
    assert [call["op"] for call in helper_calls] == ["delete", "upsert"]
    assert helper_calls[0]["metadata_filter"] == {"chunk_id": {"$eq": str(existing_chunk.id)}}

    helper_calls.clear()
    delete_db = _QueuedDB(
        [
            _QueryResult(first_value=document),
            _QueryResult(first_value=existing_chunk),
            _QueryResult(first_value=(0, 0)),
            _QueryResult(delete_value=1),
        ]
    )
    delete_response = asyncio.run(
        chunk_routes.delete_document_chunk(
            document_id=document_id,
            chunk_id=existing_chunk.id,
            tenant_id=tenant_id,
            account_id=account_id,
            db=delete_db,
        )
    )
    assert delete_response.status_code == 204
    assert [call["op"] for call in helper_calls] == ["delete"]
    assert helper_calls[0]["metadata_filter"] == {"chunk_id": {"$eq": str(existing_chunk.id)}}

    helper_calls.clear()
    disable_db = _QueuedDB([])
    disabled = asyncio.run(
        chunk_routes.disable_document_chunk(
            document_id=document_id,
            chunk_id=existing_chunk.id,
            tenant_id=tenant_id,
            account_id=account_id,
            db=disable_db,
        )
    )
    assert disabled.disabled_at is not None
    assert disabled.vector_id is None
    assert [call["op"] for call in helper_calls] == ["delete"]

    helper_calls.clear()
    reembed_db = _QueuedDB([])
    reembed_result = chunk_routes.reembed_document_chunks(
        document_id=document_id,
        payload=DocumentChunkReembedRequest(chunk_ids=[existing_chunk.id], include_disabled=True),
        tenant_id=tenant_id,
        account_id=account_id,
        db=reembed_db,
    )
    assert reembed_result["reembedded"] == 1
    assert reembed_result["conflicts"] == []
    assert [call["op"] for call in helper_calls] == ["delete", "upsert"]
    assert helper_calls[0]["metadata_filter"] == {"chunk_id": {"$eq": str(existing_chunk.id)}}


def test_delete_document_version_routes_vector_cleanup_through_indexer_helper(
    pg_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import document_versions
    from app.models.dataset import Dataset, DatasetPermissionEnum
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentChunk
    from app.rag import retriever as retriever_module
    from app.services import indexer as indexer_module

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    helper_calls: list[dict[str, object]] = []

    pg_session.add(
        Dataset(
            id=dataset_id,
            tenant_id=tenant_id,
            name="ds",
            description=None,
            permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            owner_id="owner",
            dataset_metadata={},
        )
    )
    pg_session.add(
        DBDocument(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="doc.txt",
            file_type="txt",
            file_size=3,
            file_path="uploads/doc.txt",
            status="completed",
            processing_progress=100,
            chunk_count=2,
            total_characters=0,
            owner_id="owner",
            access_mode=None,
            doc_metadata={"active_pipeline_hash": "v2", "pipeline_hash": "v2"},
        )
    )
    for pipeline_hash, chunk_index in [("v1", 0), ("v1", 1), ("v2", 2)]:
        pg_session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=chunk_index,
                content=f"chunk-{pipeline_hash}-{chunk_index}",
                doc_metadata={
                    "pipeline_hash": pipeline_hash,
                    "doc_pipeline_key": f"{document_id}:{pipeline_hash}",
                    "content_len": 8,
                },
            )
        )
    pg_session.commit()

    class _FakeIndexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            self._db = _db

        def delete_document_chunk_vectors(self, **kwargs) -> None:  # noqa: ANN003
            helper_calls.append({"op": "delete_vectors", **kwargs})

        def delete_event_indexes_for_chunks(self, **kwargs) -> None:  # noqa: ANN003
            helper_calls.append({"op": "delete_events", **kwargs})

    monkeypatch.setattr(
        indexer_module,
        "get_vector_store",
        lambda: pytest.fail("document version deletion must not hit the default vector store directly"),
        raising=True,
    )
    monkeypatch.setattr(document_versions, "Indexer", _FakeIndexer, raising=True)
    monkeypatch.setattr(document_versions.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(document_versions, "assert_document_writable_for_lifecycle", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(document_versions, "audit_log_event", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        retriever_module.hybrid_retriever,
        "remove_from_bm25_index_by_metadata_filter",
        lambda **_kwargs: None,
        raising=True,
    )

    response = document_versions.delete_document_version(
        document_id=document_id,
        pipeline_hash="v1",
        tenant_id=tenant_id,
        account_id="owner",
        db=pg_session,
    )

    assert response.status_code == 204
    assert helper_calls[0] == {
        "op": "delete_vectors",
        "document_id": document_id,
        "tenant_id": tenant_id,
        "metadata_filter": {"doc_pipeline_key": {"$eq": f"{document_id}:v1"}},
    }
    assert helper_calls[1]["op"] == "delete_events"
    remaining_hashes = {
        str((chunk.doc_metadata or {}).get("pipeline_hash") or "")
        for chunk in pg_session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).all()
    }
    assert remaining_hashes == {"v2"}


def test_retention_cleanup_routes_vector_cleanup_through_indexer_helper(
    pg_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentChunk
    from app.services import indexer as indexer_module
    from app.services import retention_policy as rp

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    helper_calls: list[dict[str, object]] = []

    pg_session.add(
        DBDocument(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=None,
            filename="doc.txt",
            file_type="txt",
            file_size=3,
            file_path="uploads/doc.txt",
            status="completed",
            processing_progress=100,
            chunk_count=2,
            total_characters=0,
            owner_id="owner",
            access_mode=None,
            doc_metadata={"active_pipeline_hash": "v2", "pipeline_hash": "v2"},
        )
    )
    for pipeline_hash, chunk_index in [("v1", 0), ("v1", 1), ("v2", 2)]:
        pg_session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=chunk_index,
                content=f"chunk-{pipeline_hash}-{chunk_index}",
                doc_metadata={
                    "pipeline_hash": pipeline_hash,
                    "doc_pipeline_key": f"{document_id}:{pipeline_hash}",
                    "content_len": 8,
                },
            )
        )
    pg_session.commit()

    class _FakeIndexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            self._db = _db

        def delete_document_chunk_vectors(self, **kwargs) -> None:  # noqa: ANN003
            helper_calls.append({"op": "delete_vectors", **kwargs})

        def delete_event_indexes_for_chunks(self, **kwargs) -> None:  # noqa: ANN003
            helper_calls.append({"op": "delete_events", **kwargs})

    monkeypatch.setattr(
        indexer_module,
        "get_vector_store",
        lambda: pytest.fail("retention cleanup must not hit the default vector store directly"),
        raising=True,
    )
    monkeypatch.setattr(indexer_module, "Indexer", _FakeIndexer, raising=True)
    monkeypatch.setattr(rp, "audit_log_event", lambda *_a, **_k: None, raising=True)

    result = rp.delete_document_version_best_effort(
        pg_session,
        tenant_id=tenant_id,
        document_id=document_id,
        pipeline_hash="v1",
        actor_id="system:retention",
        commit=True,
    )

    assert result == {"ok": True, "deleted_chunk_count": 2}
    assert helper_calls[0] == {
        "op": "delete_vectors",
        "document_id": document_id,
        "tenant_id": tenant_id,
        "metadata_filter": {"doc_pipeline_key": {"$eq": f"{document_id}:v1"}},
    }
    assert helper_calls[1]["op"] == "delete_events"
    remaining_hashes = {
        str((chunk.doc_metadata or {}).get("pipeline_hash") or "")
        for chunk in pg_session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).all()
    }
    assert remaining_hashes == {"v2"}
