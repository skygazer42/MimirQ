import asyncio
import builtins
import datetime as _datetime
import uuid
from types import SimpleNamespace

from fastapi import BackgroundTasks, HTTPException
from pydantic import ConfigDict as _PydanticConfigDict

from app.api.schemas.document import (
    DocumentBatchReingestRequest,
    DocumentLifecycleMetadataUpdateRequest,
)

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc
if not hasattr(builtins, "ConfigDict"):
    builtins.ConfigDict = _PydanticConfigDict


class _Query:
    def __init__(
        self,
        *,
        first_result=None,
        all_result=None,
        all_exc: Exception | None = None,
        delete_value: int = 1,
    ) -> None:
        self._first_result = first_result
        self._all_result = list(all_result or [])
        self._all_exc = all_exc
        self._delete_value = delete_value

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execution_options(self, **_kwargs):
        return self

    def enable_eagerloads(self, _enabled):
        return self

    def first(self):
        return self._first_result

    def all(self):
        if self._all_exc is not None:
            raise self._all_exc
        return list(self._all_result)

    def delete(self, **_kwargs):
        return self._delete_value


class _QueuedDB:
    def __init__(self, queries: list[_Query]) -> None:
        self._queries = list(queries)
        self.commit_calls = 0
        self.rollback_calls = 0
        self.refresh_calls: list[object] = []

    def query(self, *_args, **_kwargs):
        if not self._queries:
            raise AssertionError("unexpected query call")
        return self._queries.pop(0)

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)


def _document(*, tenant_id: uuid.UUID, document_id: uuid.UUID, **overrides) -> SimpleNamespace:
    values = {
        "id": document_id,
        "tenant_id": tenant_id,
        "dataset_id": None,
        "status": "completed",
        "doc_metadata": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_batch_reingest_classifies_patch_failures_without_retry(monkeypatch) -> None:
    from app.api.v1 import document_batches

    tenant_id = uuid.uuid4()
    document_ids = [uuid.uuid4() for _ in range(4)]
    retry_ids: list[uuid.UUID] = []

    async def _patch_document_pipeline(**kwargs):
        document_id = kwargs["document_id"]
        if document_id == document_ids[0]:
            raise HTTPException(status_code=404, detail="missing")
        if document_id == document_ids[1]:
            raise HTTPException(status_code=403, detail="denied")
        if document_id == document_ids[2]:
            raise HTTPException(status_code=409, detail="busy")
        return None

    async def _retry_document_processing(**kwargs):
        retry_ids.append(kwargs["document_id"])
        return {"status": "pending"}

    fake_documents_module = SimpleNamespace(
        DatasetService=SimpleNamespace(ensure_member=lambda *_a, **_k: None),
        patch_document_pipeline=_patch_document_pipeline,
        retry_document_processing=_retry_document_processing,
    )
    monkeypatch.setattr(document_batches, "_documents_module", lambda: fake_documents_module, raising=True)

    result = asyncio.run(
        document_batches.batch_reingest_documents(
            payload=DocumentBatchReingestRequest(
                document_ids=document_ids,
                patch={"chunk_size": 256},
                replace=True,
                force=True,
            ),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="acct-1",
            db=object(),
        )
    )

    assert result == {
        "queued": 1,
        "skipped": 0,
        "not_found": [document_ids[0]],
        "denied": [document_ids[1]],
        "conflicts": [document_ids[2]],
    }
    assert retry_ids == [document_ids[3]]


def test_diff_document_versions_falls_back_to_legacy_rows_and_chunk_ids(monkeypatch) -> None:
    from app.api.v1 import document_versions

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    shared_from_chunk_id = uuid.uuid4()
    removed_from_chunk_id = uuid.uuid4()
    to_chunk_id = uuid.uuid4()
    document = _document(tenant_id=tenant_id, document_id=document_id, doc_metadata={})
    db = _QueuedDB(
        [
            _Query(first_result=document),
            _Query(all_exc=RuntimeError("json path unavailable")),
            _Query(
                all_result=[
                    (shared_from_chunk_id, {"doc_pipeline_key": f"{document_id}:v1", "content_hash": "shared"}),
                    (removed_from_chunk_id, {"doc_pipeline_key": f"{document_id}:v1"}),
                    (uuid.uuid4(), {"doc_pipeline_key": f"{document_id}:other", "content_hash": "ignored"}),
                ]
            ),
            _Query(all_exc=RuntimeError("json path unavailable")),
            _Query(
                all_result=[
                    (uuid.uuid4(), {"doc_pipeline_key": f"{document_id}:v2", "content_hash": "shared"}),
                    (to_chunk_id, {"doc_pipeline_key": f"{document_id}:v2"}),
                ]
            ),
        ]
    )

    monkeypatch.setattr(document_versions.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        document_versions,
        "assert_document_readable_for_lifecycle",
        lambda *_a, **_k: None,
        raising=True,
    )

    result = document_versions.diff_document_versions(
        document_id=document_id,
        from_pipeline_hash="v1",
        to_pipeline_hash="v2",
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result["from_chunk_count"] == 2
    assert result["to_chunk_count"] == 2
    assert result["unchanged_chunks"] == 1
    assert result["added_chunks"] == 1
    assert result["removed_chunks"] == 1
    assert result["added_hashes"] == [f"id:{to_chunk_id}"]
    assert result["removed_hashes"] == [f"id:{removed_from_chunk_id}"]


def test_delete_document_version_falls_back_to_metadata_scan_and_restores_current_hash(monkeypatch) -> None:
    from app.api.v1 import document_versions
    from app.rag import retriever as retriever_module

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_ids = [uuid.uuid4(), uuid.uuid4()]
    document = _document(
        tenant_id=tenant_id,
        document_id=document_id,
        status="completed",
        doc_metadata={"pipeline_hash": "v1", "active_pipeline_hash": "v2"},
    )
    db = _QueuedDB(
        [
            _Query(first_result=document),
            _Query(all_exc=RuntimeError("json path unavailable")),
            _Query(
                all_result=[
                    (chunk_ids[0], {"doc_pipeline_key": f"{document_id}:v1"}),
                    (uuid.uuid4(), {"doc_pipeline_key": f"{document_id}:v9"}),
                    (chunk_ids[1], {"doc_pipeline_key": f"{document_id}:v1"}),
                ]
            ),
            _Query(delete_value=2),
            _Query(delete_value=0),
        ]
    )
    helper_calls: list[dict[str, object]] = []

    class _FakeIndexer:
        def __init__(self, _db) -> None:
            self._db = _db

        def delete_document_chunk_vectors(self, **kwargs) -> None:
            helper_calls.append({"op": "delete_vectors", **kwargs})

        def delete_event_indexes_for_chunks(self, **kwargs) -> None:
            helper_calls.append({"op": "delete_events", **kwargs})

    monkeypatch.setattr(document_versions.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        document_versions,
        "assert_document_writable_for_lifecycle",
        lambda *_a, **_k: None,
        raising=True,
    )
    monkeypatch.setattr(document_versions, "Indexer", _FakeIndexer, raising=True)
    monkeypatch.setattr(document_versions, "audit_log_event", lambda *_a, **_k: None, raising=True)
    retriever_cls = type(retriever_module.hybrid_retriever)
    monkeypatch.setattr(
        retriever_cls,
        "remove_from_bm25_index_by_metadata_filter",
        lambda _self, **_kwargs: None,
        raising=False,
    )

    response = document_versions.delete_document_version(
        document_id=document_id,
        pipeline_hash="v1",
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert response.status_code == 204
    assert document.doc_metadata["pipeline_hash"] == "v2"
    assert helper_calls[0] == {
        "op": "delete_vectors",
        "document_id": document_id,
        "tenant_id": tenant_id,
        "metadata_filter": {"doc_pipeline_key": {"$eq": f"{document_id}:v1"}},
    }
    assert helper_calls[1] == {
        "op": "delete_events",
        "tenant_id": tenant_id,
        "chunk_ids": chunk_ids,
        "commit": False,
        "prune_orphan_entities": True,
    }


def test_lifecycle_patch_noop_returns_current_metadata_without_writes(monkeypatch) -> None:
    from app.api.v1 import document_lifecycle

    document_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    document = _document(
        tenant_id=tenant_id,
        document_id=document_id,
        lifecycle_owner="owner@example.com",
        review_due_at=None,
        authority_level=7,
        supersedes_document_id=None,
        publication_status="draft",
    )
    db = _QueuedDB([])
    audit_calls: list[dict[str, object]] = []

    monkeypatch.setattr(document_lifecycle.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(document_lifecycle, "get_document_for_lifecycle", lambda *_a, **_k: document, raising=True)
    monkeypatch.setattr(
        document_lifecycle,
        "assert_document_writable_for_lifecycle",
        lambda *_a, **_k: None,
        raising=True,
    )
    monkeypatch.setattr(
        document_lifecycle,
        "audit_log_event",
        lambda *_a, **kwargs: audit_calls.append(kwargs),
        raising=True,
    )

    result = document_lifecycle.patch_document_lifecycle_metadata(
        document_id=document_id,
        payload=DocumentLifecycleMetadataUpdateRequest(),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result.lifecycle_owner == "owner@example.com"
    assert result.authority_level == 7
    assert result.publication_status == "draft"
    assert db.commit_calls == 0
    assert db.refresh_calls == []
    assert audit_calls == []
