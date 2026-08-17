from collections.abc import Iterator
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent


def test_delete_document_minio_images_streams_chunk_img_ids_and_batches_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_lifecycle_service as dls

    tenant_id = uuid4()
    document_id = uuid4()
    query_args: list[object] = []
    captured: dict[str, object] = {}

    class _Query:
        def __init__(self) -> None:
            self.batch_size: int | None = None

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def yield_per(self, batch_size: int):
            self.batch_size = batch_size
            return self

        def __iter__(self):
            return iter(
                [
                    ("img-2",),
                    ("img-1",),
                    ("img-2",),
                    (None,),
                    (" ",),
                ]
            )

        def all(self):
            raise AssertionError("chunk image cleanup should stream instead of materializing all rows")

    query = _Query()

    class _DB:
        def query(self, *args):  # noqa: ANN002
            query_args.extend(args)
            return query

    monkeypatch.setattr(dls.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dls.minio_service,
        "delete_images",
        lambda values, extension="jpg", *, batch_size: captured.update(
            {
                "values": list(values),
                "extension": extension,
                "batch_size": batch_size,
            }
        ),
        raising=True,
    )

    dls._delete_document_minio_images(
        _DB(),
        tenant_id=tenant_id,
        document_id=document_id,
        document=SimpleNamespace(doc_metadata={"img_ids": ["doc-2", "doc-1", "img-1"]}),
    )

    assert len(query_args) == 1
    assert query_args[0] is not dls.DocumentChunk
    assert query.batch_size == dls._CHUNK_METADATA_SCAN_BATCH_SIZE
    assert captured == {
        "values": ["doc-1", "doc-2", "img-1", "img-2"],
        "extension": "jpg",
        "batch_size": dls._MINIO_DELETE_OBJECT_BATCH_SIZE,
    }


def test_minio_delete_images_uses_batch_remove_objects_and_surfaces_aggregated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from minio.deleteobjects import DeleteError

    from app.storage.object.minio import MinIOService

    remove_calls: list[list[str]] = []
    metric_calls: list[tuple[str, bool, str, str | None]] = []

    class _Client:
        def remove_objects(self, *, bucket_name: str, delete_object_list):  # noqa: ANN003
            names = [item.name for item in delete_object_list]
            assert bucket_name == "bucket-a"
            remove_calls.append(names)
            if len(remove_calls) == 2:
                return iter([DeleteError("InternalError", "boom", names[0], None)])
            return iter(())

    service = MinIOService()
    service._bucket_name = "bucket-a"
    monkeypatch.setattr(service, "_get_client", lambda: _Client(), raising=True)
    monkeypatch.setattr(
        service,
        "_log_metric",
        lambda op, ok, elapsed, object_name, error=None: metric_calls.append((op, ok, object_name, error)),
        raising=True,
    )

    with pytest.raises(RuntimeError, match=r"MinIO delete images failed for 1 object\(s\)"):
        service.delete_images(
            ["tenant:dataset:doc:img-1", "tenant:dataset:doc:img-2", "tenant:dataset:doc:img-3"],
            batch_size=2,
        )

    assert remove_calls == [
        [
            "images/tenant/dataset/doc/img-1.jpg",
            "images/tenant/dataset/doc/img-2.jpg",
        ],
        [
            "images/tenant/dataset/doc/img-3.jpg",
        ],
    ]
    assert metric_calls[0][:3] == ("delete", True, "images/tenant/dataset/doc/img-1.jpg")
    assert metric_calls[1][:3] == ("delete", True, "images/tenant/dataset/doc/img-2.jpg")
    assert metric_calls[2] == (
        "delete",
        False,
        "images/tenant/dataset/doc/img-3.jpg",
        "DeleteError(code='InternalError', message='boom', "
        "name='images/tenant/dataset/doc/img-3.jpg', version_id=None)",
    )


def test_dataset_scoped_vector_collections_stream_chunk_metadata_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid4()
    document_id = uuid4()
    query_args: list[object] = []

    class _Row:
        def __init__(self, **mapping: object) -> None:
            self._mapping = mapping

    class _Query:
        def __init__(self) -> None:
            self.batch_size: int | None = None

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def yield_per(self, batch_size: int):
            self.batch_size = batch_size
            return self

        def __iter__(self):
            return iter(
                [
                    _Row(
                        vector_collection_name="",
                        embedding_space_hash="space-a",
                        dataset_scoped="true",
                    ),
                    _Row(
                        vector_collection_name="documents_emb_oldbase_space_b",
                        embedding_space_hash="space-b",
                        dataset_scoped=True,
                    ),
                ]
            )

        def all(self):
            raise AssertionError("dataset-scoped cleanup should stream instead of materializing all rows")

    query = _Query()

    monkeypatch.setattr(
        indexer,
        "resolve_dataset_embedding_runtime",
        lambda _meta: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-default",
            api_base="",
            api_key="",
            embedding_space_hash="space-default",
            collection_name="documents",
            dataset_scoped=False,
        ),
    )

    service = object.__new__(indexer.Indexer)
    service._db = SimpleNamespace(query=lambda *args: query_args.extend(args) or query)

    collections = service._dataset_scoped_vector_collections_for_document(
        tenant_id=tenant_id,
        document_id=document_id,
        assume_dataset_scoped=False,
    )

    assert len(query_args) == 3
    assert query.batch_size == indexer._CHUNK_METADATA_SCAN_BATCH_SIZE
    assert collections == ["documents_emb_oldbase_space_b", "documents_emb_space_a"]


def test_run_bounded_cleanup_batch_aggregates_parallel_failures_without_leaking_values() -> None:
    from app.services import document_lifecycle_service as dls

    values = ["/sensitive/a.pdf", "/sensitive/b.pdf", "/sensitive/c.pdf"]
    seen: list[str] = []
    seen_lock = Lock()
    barrier = Barrier(len(values))

    def _fail(value: str) -> None:
        with seen_lock:
            seen.append(value)
        barrier.wait(timeout=1)
        raise RuntimeError(f"delete failed for {value}")

    with pytest.raises(RuntimeError, match=r"Cleanup batch failed for 3 item\(s\)") as exc_info:
        dls._run_bounded_cleanup_batch(values, _fail, max_workers=len(values))

    assert sorted(seen) == sorted(values)
    assert "/sensitive/" not in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.fixture
def kg_db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            KgEntity.__table__,
            KgSourceEvent.__table__,
            KgEventEntity.__table__,
            KgRelation.__table__,
        ],
    )
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _kg_uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:011x}a")


def _seed_event_graph(db: Session, *, tenant_id: UUID, document_id: UUID, count: int) -> list[UUID]:
    entity_ids: list[UUID] = []
    for index in range(1, count + 1):
        event_id = _kg_uuid(index)
        entity_id = _kg_uuid(index + 100)
        entity_ids.append(entity_id)
        db.add(
            KgSourceEvent(
                id=event_id,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=_kg_uuid(index + 200),
                title=f"event-{index}",
                summary=f"summary-{index}",
                content=f"content-{index}",
            )
        )
        db.add(
            KgEntity(
                id=entity_id,
                tenant_id=tenant_id,
                name=f"entity-{index}",
                normalized_name=f"entity-{index}",
                type="Thing",
            )
        )
        db.add(
            KgEventEntity(
                id=_kg_uuid(index + 300),
                event_id=event_id,
                entity_id=entity_id,
            )
        )
    db.commit()
    return entity_ids


def test_delete_event_indexes_batches_without_committing_caller_transaction(
    kg_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer as indexer_module

    tenant_id = _kg_uuid(1000)
    document_id = _kg_uuid(2000)
    entity_ids = _seed_event_graph(kg_db, tenant_id=tenant_id, document_id=document_id, count=3)

    flushes: list[str] = []
    commits: list[str] = []
    original_flush = kg_db.flush
    original_commit = kg_db.commit
    kg_db.flush = lambda: flushes.append("flush") or original_flush()  # type: ignore[method-assign]
    kg_db.commit = lambda: commits.append("commit") or original_commit()  # type: ignore[method-assign]

    event_batches: list[list[str]] = []
    entity_batches: list[list[str]] = []
    service = indexer_module.Indexer.__new__(indexer_module.Indexer)
    service._db = kg_db
    service._event_vector = SimpleNamespace(delete=lambda ids: event_batches.append(list(ids)))
    service._entity_vector = SimpleNamespace(delete=lambda ids: entity_batches.append(list(ids)))
    monkeypatch.setattr(indexer_module, "_vector_write_batch_size", lambda: 2)

    result = service.delete_event_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        commit=False,
        prune_orphan_entities=True,
        strict=True,
    )

    assert result == {"events_deleted": 3, "entities_pruned": 3}
    assert commits == []
    assert len(flushes) >= 2
    assert event_batches == [
        [str(_kg_uuid(1)), str(_kg_uuid(2))],
        [str(_kg_uuid(3))],
    ]
    assert entity_batches == [
        [str(entity_ids[0]), str(entity_ids[1])],
        [str(entity_ids[2])],
    ]
    assert kg_db.query(KgSourceEvent).count() == 0
    assert kg_db.query(KgEntity).count() == 0
    assert kg_db.query(KgEventEntity).count() == 0


def test_delete_event_indexes_strict_entity_vector_failure_rolls_back_current_batch(
    kg_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer as indexer_module

    tenant_id = _kg_uuid(3000)
    document_id = _kg_uuid(4000)
    _seed_event_graph(kg_db, tenant_id=tenant_id, document_id=document_id, count=1)

    commits: list[str] = []
    rollbacks: list[str] = []
    original_commit = kg_db.commit
    original_rollback = kg_db.rollback
    kg_db.commit = lambda: commits.append("commit") or original_commit()  # type: ignore[method-assign]
    kg_db.rollback = lambda: rollbacks.append("rollback") or original_rollback()  # type: ignore[method-assign]

    service = indexer_module.Indexer.__new__(indexer_module.Indexer)
    service._db = kg_db
    service._event_vector = SimpleNamespace(delete=lambda _ids: None)
    service._entity_vector = SimpleNamespace(
        delete=lambda _ids: (_ for _ in ()).throw(RuntimeError("entity vector down"))
    )
    monkeypatch.setattr(indexer_module, "_vector_write_batch_size", lambda: 1)

    with pytest.raises(RuntimeError, match="entity vector down"):
        service.delete_event_indexes(
            tenant_id=tenant_id,
            document_id=document_id,
            commit=True,
            prune_orphan_entities=True,
            strict=True,
        )

    assert commits == []
    assert rollbacks == ["rollback"]
    assert kg_db.query(KgSourceEvent).count() == 1
    assert kg_db.query(KgEntity).count() == 1
    assert kg_db.query(KgEventEntity).count() == 1


def test_delete_event_indexes_non_strict_vector_failures_still_commit_all_batches(
    kg_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer as indexer_module

    tenant_id = _kg_uuid(4100)
    document_id = _kg_uuid(4200)
    _seed_event_graph(kg_db, tenant_id=tenant_id, document_id=document_id, count=3)

    commits: list[str] = []
    original_commit = kg_db.commit
    kg_db.commit = lambda: commits.append("commit") or original_commit()  # type: ignore[method-assign]

    event_batches: list[list[str]] = []
    entity_batches: list[list[str]] = []

    def _fail_event_vectors(ids: list[str]) -> None:
        event_batches.append(list(ids))
        raise RuntimeError("event vector down")

    def _fail_entity_vectors(ids: list[str]) -> None:
        entity_batches.append(list(ids))
        raise RuntimeError("entity vector down")

    service = indexer_module.Indexer.__new__(indexer_module.Indexer)
    service._db = kg_db
    service._event_vector = SimpleNamespace(delete=_fail_event_vectors)
    service._entity_vector = SimpleNamespace(delete=_fail_entity_vectors)
    monkeypatch.setattr(indexer_module, "_vector_write_batch_size", lambda: 2)

    result = service.delete_event_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        commit=True,
        prune_orphan_entities=True,
        strict=False,
    )

    assert result == {"events_deleted": 3, "entities_pruned": 3}
    assert len(commits) == 2
    assert [len(batch) for batch in event_batches] == [2, 1]
    assert [len(batch) for batch in entity_batches] == [2, 1]
    assert kg_db.query(KgSourceEvent).count() == 0
    assert kg_db.query(KgEntity).count() == 0


def test_delete_event_indexes_strict_later_batch_failure_preserves_resumable_progress(
    kg_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer as indexer_module

    tenant_id = _kg_uuid(4300)
    document_id = _kg_uuid(4400)
    _seed_event_graph(kg_db, tenant_id=tenant_id, document_id=document_id, count=3)

    commits: list[str] = []
    rollbacks: list[str] = []
    original_commit = kg_db.commit
    original_rollback = kg_db.rollback
    kg_db.commit = lambda: commits.append("commit") or original_commit()  # type: ignore[method-assign]
    kg_db.rollback = lambda: rollbacks.append("rollback") or original_rollback()  # type: ignore[method-assign]

    event_delete_calls = 0

    def _fail_second_event_batch(_ids: list[str]) -> None:
        nonlocal event_delete_calls
        event_delete_calls += 1
        if event_delete_calls == 2:
            raise RuntimeError("event vector down on second batch")

    service = indexer_module.Indexer.__new__(indexer_module.Indexer)
    service._db = kg_db
    service._event_vector = SimpleNamespace(delete=_fail_second_event_batch)
    service._entity_vector = SimpleNamespace(delete=lambda _ids: None)
    monkeypatch.setattr(indexer_module, "_vector_write_batch_size", lambda: 2)

    with pytest.raises(RuntimeError, match="second batch"):
        service.delete_event_indexes(
            tenant_id=tenant_id,
            document_id=document_id,
            commit=True,
            prune_orphan_entities=True,
            strict=True,
        )

    assert commits == ["commit"]
    assert rollbacks == ["rollback"]
    assert [row[0] for row in kg_db.query(KgSourceEvent.id).all()] == [_kg_uuid(3)]
    assert [row[0] for row in kg_db.query(KgEntity.id).all()] == [_kg_uuid(103)]

    service._event_vector = SimpleNamespace(delete=lambda _ids: None)
    assert service.delete_event_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        commit=True,
        prune_orphan_entities=True,
        strict=True,
    ) == {"events_deleted": 1, "entities_pruned": 1}
    assert kg_db.query(KgSourceEvent).count() == 0
    assert kg_db.query(KgEntity).count() == 0


def test_delete_event_indexes_batches_respect_excluded_event_ids(
    kg_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer as indexer_module

    tenant_id = _kg_uuid(4500)
    document_id = _kg_uuid(4600)
    _seed_event_graph(kg_db, tenant_id=tenant_id, document_id=document_id, count=3)

    service = indexer_module.Indexer.__new__(indexer_module.Indexer)
    service._db = kg_db
    service._event_vector = SimpleNamespace(delete=lambda _ids: None)
    service._entity_vector = SimpleNamespace(delete=lambda _ids: None)
    monkeypatch.setattr(indexer_module, "_vector_write_batch_size", lambda: 1)

    result = service.delete_event_indexes_for_chunks(
        tenant_id=tenant_id,
        chunk_ids=[_kg_uuid(201), _kg_uuid(202), _kg_uuid(203)],
        exclude_event_ids=[_kg_uuid(2)],
        commit=False,
        prune_orphan_entities=True,
        strict=True,
    )

    assert result == {"events_deleted": 2, "entities_pruned": 2}
    assert [row[0] for row in kg_db.query(KgSourceEvent.id).all()] == [_kg_uuid(2)]
    assert [row[0] for row in kg_db.query(KgEntity.id).all()] == [_kg_uuid(102)]


def test_prune_orphan_entities_batches_candidates_and_keeps_referenced_rows(
    kg_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer as indexer_module

    tenant_id = _kg_uuid(5000)
    referenced_entity_id = _kg_uuid(6000)
    event_id = _kg_uuid(7000)
    kg_db.add(
        KgSourceEvent(
            id=event_id,
            tenant_id=tenant_id,
            document_id=_kg_uuid(8000),
            chunk_id=_kg_uuid(8001),
            title="referenced",
            summary="referenced",
            content="referenced",
        )
    )
    kg_db.add(
        KgEntity(
            id=referenced_entity_id,
            tenant_id=tenant_id,
            name="referenced",
            normalized_name="referenced",
            type="Thing",
        )
    )
    kg_db.add(
        KgEventEntity(
            id=_kg_uuid(8002),
            event_id=event_id,
            entity_id=referenced_entity_id,
        )
    )
    orphan_ids: list[UUID] = []
    for index in range(3):
        orphan_id = _kg_uuid(6100 + index)
        orphan_ids.append(orphan_id)
        kg_db.add(
            KgEntity(
                id=orphan_id,
                tenant_id=tenant_id,
                name=f"orphan-{index}",
                normalized_name=f"orphan-{index}",
                type="Thing",
            )
        )
    kg_db.commit()

    vector_batches: list[list[str]] = []
    service = indexer_module.Indexer.__new__(indexer_module.Indexer)
    service._db = kg_db
    service._entity_vector = SimpleNamespace(delete=lambda ids: vector_batches.append(list(ids)))
    monkeypatch.setattr(indexer_module, "_vector_write_batch_size", lambda: 2)

    deleted = service.prune_orphan_entities(tenant_id=tenant_id, commit=False, strict=True)

    assert deleted == 3
    assert vector_batches == [
        [str(orphan_ids[0]), str(orphan_ids[1])],
        [str(orphan_ids[2])],
    ]
    remaining_ids = {row[0] for row in kg_db.query(KgEntity.id).all()}
    assert remaining_ids == {referenced_entity_id}
