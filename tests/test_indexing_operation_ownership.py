import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app.models.registry  # noqa: F401


def test_vector_write_support_imports_without_the_indexer() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
class NoIndexer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.ingestion.indexing.indexer':
            raise AssertionError('Domain operation imports Indexer')
sys.meta_path.insert(0, NoIndexer())
from app.rag.ingestion.indexing.vector_writer import dual_write_shadow_vectors_best_effort
assert callable(dual_write_shadow_vectors_best_effort)
assert 'app.rag.ingestion.indexing.indexer' not in sys.modules
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_document_runtime_database_failure_cannot_select_default_embedding_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.ingestion.indexing import indexer

    failure = RuntimeError("document lookup unavailable")

    class DB:
        def query(self, *_args):
            raise failure

    monkeypatch.setattr(
        indexer, "resolve_dataset_embedding_runtime", lambda _metadata: pytest.fail("default space was selected")
    )
    service = indexer.Indexer.__new__(indexer.Indexer)
    service._db = DB()
    with pytest.raises(indexer.DatasetScopedEmbeddingRuntimeResolutionError) as caught:
        service._embedding_runtime_for_document(tenant_id=uuid4(), document_id=uuid4())
    assert caught.value.__cause__ is failure


@pytest.fixture(params=[False, True], ids=["default-space", "dataset-space"])
def chunk_write(monkeypatch: pytest.MonkeyPatch, request):
    from app.rag.ingestion.indexing import indexer
    from app.rag.ingestion.indexing import indexer as chunks
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig
    from app.storage.vector import factory

    class Embeddings:
        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(factory, "create_langchain_embeddings_from_config", lambda **_kwargs: Embeddings())
    store = factory.MemoryVectorStore()
    monkeypatch.setattr(indexer, "get_vector_store", lambda: store)
    monkeypatch.setattr(chunks, "_enforce_embedding_quota_gate", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(indexer, "transition_document_index_channel", lambda *_args, **_kwargs: None)
    tenant_id, document_id, dataset_id = uuid4(), uuid4(), uuid4()
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="local-test",
        api_base="",
        api_key="",
        embedding_space_hash="space",
        collection_name="documents",
        dataset_scoped=request.param,
    )
    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(indexer, "create_embeddings_for_runtime", lambda _runtime: Embeddings())

    class DatasetAdapter:
        def add_vectors(self, items, **_kwargs):
            return store.add_documents(items, document_id, tenant_id)

        def delete_by_document_id_and_filter(self, **kwargs):
            store.delete_by_document_id_and_filter(**kwargs)

    monkeypatch.setattr(indexer, "get_milvus_adapter", lambda *_args, **_kwargs: DatasetAdapter())
    monkeypatch.setattr(indexer, "resolve_collection_name", lambda name: name)
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_type="txt",
        doc_metadata={},
    )
    monkeypatch.setattr(
        chunks.Indexer,
        "_resolve_chunk_index_context",
        lambda self, **_kwargs: {
            "embedding_runtime": runtime,
            "embedding_space": runtime.embedding_space_hash,
            "db_document": document,
            "dataset_uuid": dataset_id,
            "dataset_id_str": str(dataset_id),
            "file_type_str": "txt",
            "document_title": "Guide",
            "document_retrieval_metadata": {},
        },
    )
    monkeypatch.setattr(chunks.Indexer, "_touch_chunk_retrieval_scope", lambda self, **_kwargs: None)

    class DB:
        def __init__(self):
            self.failure = None
            self.commits = 0
            self.flushes = 0
            self.added = []

        def add_all(self, items):
            self.added.extend(items)

        def flush(self):
            self.flushes += 1
            if self.failure is not None:
                raise self.failure

        def commit(self):
            self.commits += 1

    db = DB()
    service = indexer.Indexer(db)
    return service, db, store, tenant_id, document_id


def test_event_commit_false_flushes_without_publishing_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.ingestion.indexing import indexer as events
    from app.types.indexing import EventEntityInput, EventInput, IndexingOptions

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class DB:
        def __init__(self):
            self.added = []
            self.commits = 0
            self.flushes = 0

        def add(self, item):
            self.added.append(item)

        def query(self, *_args):
            return Query()

        def flush(self):
            self.flushes += 1
            for item in self.added:
                if item.id is None:
                    item.id = uuid4()

        def commit(self):
            self.commits += 1

    class NoVectorWrites:
        def add_vectors(self, *_args, **_kwargs):
            pytest.fail("commit=False published event/entity vectors")

    monkeypatch.setattr(events, "get_milvus_adapter", lambda **_kwargs: NoVectorWrites())
    db = DB()
    result = events.Indexer(db).index_events(
        tenant_id=uuid4(),
        commit=False,
        options=IndexingOptions(event_vector_enabled=True, entity_vector_enabled=True),
        events=[
            EventInput(
                title="event",
                summary="summary",
                content="content",
                document_id=None,
                chunk_id=None,
                vector=[1.0],
                entities=[
                    EventEntityInput(
                        name="entity", normalized_name="entity", type="concept", vector=[1.0], evidence_start_char=0
                    )
                ],
            )
        ],
    )
    assert db.commits == 0 and db.flushes >= 1
    assert len(result.events) == len(result.entities) == 1
    assert result.event_vector_ids == result.entity_vector_ids == []
    link = next(item for item in db.added if isinstance(item, events.KgEventEntity))
    assert link.extra_data["evidence_start_char"] == 0


def test_database_failure_after_vector_write_cleans_only_attempted_chunks(chunk_write) -> None:
    from app.types.indexing import ChunkInput, IndexingOptions

    service, db, store, tenant_id, document_id = chunk_write
    previous_id = str(uuid4())
    store.add_documents(
        [
            {"content": "previous pipeline", "metadata": {"chunk_id": previous_id, "pipeline_hash": "old"}},
        ],
        document_id,
        tenant_id,
    )
    failure = RuntimeError("chunk persistence failed")
    db.failure = failure
    with pytest.raises(RuntimeError, match="chunk persistence failed") as caught:
        service.index_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="new content", metadata={"pipeline_hash": "new"})],
            commit=False,
            options=IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=False),
        )
    assert caught.value is failure
    assert db.commits == 0
    assert [metadata["chunk_id"] for _, metadata in store.storage] == [previous_id]


def test_database_failure_preserves_reused_chunk_id_from_an_older_pipeline(chunk_write) -> None:
    from app.types.indexing import ChunkInput, IndexingOptions

    service, db, store, tenant_id, document_id = chunk_write
    shared_id = str(uuid4())
    store.add_documents(
        [{"content": "older pipeline", "metadata": {"chunk_id": shared_id, "pipeline_hash": "old"}}],
        document_id,
        tenant_id,
    )
    failure = RuntimeError("chunk persistence failed")
    db.failure = failure

    with pytest.raises(RuntimeError) as caught:
        service.index_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="new attempt", metadata={"chunk_id": shared_id, "pipeline_hash": "new"})],
            commit=False,
            options=IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=False),
        )

    assert caught.value is failure
    assert [(metadata["chunk_id"], metadata["pipeline_hash"]) for _, metadata in store.storage] == [(shared_id, "old")]


def test_vector_cleanup_failure_keeps_the_original_persistence_error(chunk_write, monkeypatch) -> None:
    from app.types.indexing import ChunkInput, IndexingOptions

    service, db, store, tenant_id, document_id = chunk_write
    failure = RuntimeError("chunk persistence failed")
    db.failure = failure

    def failed_cleanup(**_kwargs):
        raise OSError("vector cleanup unavailable")

    monkeypatch.setattr(store, "delete_by_document_id_and_filter", failed_cleanup)
    with pytest.raises(RuntimeError) as caught:
        service.index_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="new attempt", metadata={"pipeline_hash": "new"})],
            commit=False,
            options=IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=False),
        )

    assert caught.value is failure
    assert failure.__notes__ == ["Chunk vector cleanup failed: OSError"]


@pytest.mark.parametrize("chunk_write", [False], indirect=True)
@pytest.mark.parametrize("commit_fails", [False, True])
def test_committing_chunk_write_preserves_order_and_does_not_guess_a_failed_commit(
    chunk_write, monkeypatch, commit_fails
) -> None:
    from app.types.indexing import ChunkInput, IndexingOptions

    service, db, store, tenant_id, document_id = chunk_write
    events = []
    original_flush = db.flush
    original_commit = db.commit
    failure = RuntimeError("commit outcome unavailable")

    def flush():
        events.append("flush")
        original_flush()

    def commit():
        events.append("commit")
        original_commit()
        if commit_fails:
            raise failure

    monkeypatch.setattr(db, "flush", flush)
    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(service, "_update_bm25_with_tracking", lambda **_kwargs: events.append("bm25"))

    def write():
        return service.index_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="committed content", metadata={})],
            commit=True,
            options=IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=False),
        )

    if commit_fails:
        with pytest.raises(RuntimeError) as caught:
            write()
        assert caught.value is failure
        assert events == ["flush", "commit"]
    else:
        result = write()
        assert result.chunk_ids == [db.added[0].id]
        assert events == ["flush", "commit", "bm25"]
    assert db.flushes == db.commits == 1
    assert len(store.storage) == 1


@pytest.mark.parametrize("chunk_write", [False], indirect=True)
def test_default_vector_batch_failure_cleans_earlier_batches_and_preserves_old_pipeline(
    chunk_write, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rag.ingestion.indexing import indexer
    from app.types.indexing import ChunkInput, IndexingOptions

    service, db, store, tenant_id, document_id = chunk_write
    previous_id = str(uuid4())
    store.add_documents(
        [
            {"content": "previous pipeline", "metadata": {"chunk_id": previous_id, "pipeline_hash": "old"}},
        ],
        document_id,
        tenant_id,
    )
    monkeypatch.setattr(indexer, "_vector_write_batch_size", lambda: 1)
    monkeypatch.setattr(indexer, "_vector_write_retry_policy", lambda: (0, 0.0))
    encode = store.emb.embed_documents
    failure = RuntimeError("second vector batch failed")
    batches = 0

    def embed(texts):
        nonlocal batches
        batches += 1
        if batches == 2:
            raise failure
        return encode(texts)

    monkeypatch.setattr(store.emb, "embed_documents", embed)
    with pytest.raises(RuntimeError, match="second vector batch failed") as caught:
        service.index_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="new first", metadata={}), ChunkInput(content="new second", metadata={})],
            commit=False,
            options=IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=False),
        )
    assert caught.value is failure
    assert db.commits == db.flushes == 0
    assert [metadata["chunk_id"] for _, metadata in store.storage] == [previous_id]


def test_chunk_commit_false_flushes_without_committing_the_callers_session(chunk_write) -> None:
    from app.types.indexing import ChunkInput, IndexingOptions

    service, db, store, tenant_id, document_id = chunk_write
    result = service.index_chunks(
        document_id=document_id,
        tenant_id=tenant_id,
        chunks=[ChunkInput(content="new content", metadata={})],
        commit=False,
        options=IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=False),
    )
    assert db.commits == 0 and db.flushes == 1
    assert len(result.db_chunks) == len(result.vector_ids) == len(store.storage) == 1
    assert result.db_chunks[0].tenant_id == tenant_id
    assert result.db_chunks[0].document_id == document_id
    assert UUID(store.storage[0][1]["chunk_id"]) == result.chunk_ids[0]
