from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langchain_core.documents import Document
from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, Text, Uuid, create_engine
from sqlalchemy.orm import Session

from tests.test_milvus_bm25_cutover import Store


@pytest.fixture
def corpus_db(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table(
        "datasets",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid),
        Column("updated_at", DateTime(timezone=True)),
        Column("metadata", JSON, key="dataset_metadata"),
    )
    documents = Table(
        "documents",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid),
        Column("dataset_id", Uuid),
        Column("status", String),
        Column("publication_status", String),
        Column("updated_at", DateTime(timezone=True)),
        Column("archived_at", DateTime),
        Column("disabled_at", DateTime),
        Column("metadata", JSON, key="doc_metadata"),
    )
    chunks = Table(
        "document_chunks",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid),
        Column("document_id", Uuid),
        Column("chunk_index", Integer),
        Column("page_number", Integer),
        Column("content", Text),
        Column("metadata", JSON, key="doc_metadata"),
        Column("disabled_at", DateTime),
    )
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db, documents, chunks
    engine.dispose()


def _document(db, table, tenant, dataset, *, published=True):
    datasets = table.metadata.tables["datasets"]
    if db.scalar(datasets.select().where(datasets.c.id == dataset)) is None:
        db.execute(
            datasets.insert().values(
                id=dataset, tenant_id=tenant, updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc), dataset_metadata={}
            )
        )
    document = uuid4()
    db.execute(
        table.insert().values(
            id=document,
            tenant_id=tenant,
            dataset_id=dataset,
            status="completed",
            publication_status="published" if published else "draft",
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    return document


def test_native_upsert_uses_authoritative_database_dataset_and_document_scope(corpus_db):
    from app.rag.retrieval.corpus_index import CorpusIndex

    db, table, _ = corpus_db
    tenant, dataset = uuid4(), uuid4()
    document = _document(db, table, tenant, dataset)
    db.commit()
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    corpus.upsert(
        db,
        tenant_id=tenant,
        documents=[
            Document(
                id=str(uuid4()),
                page_content="text",
                metadata={"tenant_id": str(tenant), "document_id": str(document), "dataset_id": str(uuid4())},
            )
        ],
    )
    assert store.calls[0][1][0].metadata["dataset_id"] == str(dataset)
    with pytest.raises(ValueError, match="document"):
        corpus.upsert(
            db,
            tenant_id=uuid4(),
            documents=[Document(id=str(uuid4()), page_content="text", metadata={"document_id": str(document)})],
        )
    assert len(store.calls) == 1


def test_backfill_counts_and_writes_only_published_chunks_in_the_requested_scope(corpus_db):
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    db, documents, chunks = corpus_db
    tenant, dataset = uuid4(), uuid4()
    expected = None
    for row_tenant, row_dataset, published in [
        (tenant, dataset, True),
        (tenant, dataset, False),
        (uuid4(), dataset, True),
        (tenant, uuid4(), True),
    ]:
        document = _document(db, documents, row_tenant, row_dataset, published=published)
        chunk = uuid4()
        db.execute(
            chunks.insert().values(
                id=chunk,
                tenant_id=row_tenant,
                document_id=document,
                chunk_index=0,
                page_number=1,
                content="published source",
                doc_metadata={"dataset_id": "spoofed-metadata-dataset"},
            )
        )
        if row_tenant == tenant and row_dataset == dataset and published:
            expected = str(chunk)
    db.commit()
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    assert corpus.rebuild(db, scope=CorpusScope(tenant, (dataset,)), batch_size=1) == 1
    doc = store.calls[0][1][0]
    assert doc.id == expected
    assert doc.metadata["dataset_id"] == str(dataset)


def test_legacy_chunk_identity_lookup_is_limited_to_actual_missing_candidates(corpus_db, monkeypatch):
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    db, documents, chunks = corpus_db
    tenant, dataset = uuid4(), uuid4()
    document = _document(db, documents, tenant, dataset)
    chunk = uuid4()
    db.execute(
        chunks.insert().values(
            id=chunk,
            tenant_id=tenant,
            document_id=document,
            chunk_index=7,
            page_number=1,
            content="text",
            doc_metadata={},
        )
    )
    db.commit()
    corpus = CorpusIndex(bm25_store=Store())
    monkeypatch.setattr(corpus, "_open_session", lambda: db)
    scope = CorpusScope(tenant, (dataset,))
    assert corpus.chunk_id_lookup(scope, candidates=[]) == {}
    lookup = corpus.chunk_id_lookup(scope, candidates=[{"metadata": {"document_id": str(document), "chunk_index": 7}}])
    assert lookup == {f"{document}:7": str(chunk)}


def test_native_backfill_dry_run_performs_no_milvus_mutation(corpus_db):
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope
    from scripts.backfill_milvus_bm25 import run_backfill

    db, _, _ = corpus_db
    store = Store()
    result = run_backfill(
        db=db, corpus_index=CorpusIndex(bm25_store=store), scope=CorpusScope(uuid4()), apply=False, batch_size=2
    )
    assert result["mode"] == "dry-run"
    assert result["published_chunks"] == 0
    assert store.calls == []


def test_backfill_does_not_restore_disabled_archived_or_old_pipeline_chunks(corpus_db):
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    db, documents, chunks = corpus_db
    tenant, dataset = uuid4(), uuid4()
    expected = None
    for state in ["active", "old_pipeline", "disabled_chunk", "disabled_document", "archived_document"]:
        document = _document(db, documents, tenant, dataset)
        updates = {"doc_metadata": {"active_pipeline_hash": "active"}}
        if state == "disabled_document":
            updates["disabled_at"] = datetime.now(timezone.utc)
        if state == "archived_document":
            updates["archived_at"] = datetime.now(timezone.utc)
        db.execute(documents.update().where(documents.c.id == document).values(**updates))
        chunk = uuid4()
        db.execute(
            chunks.insert().values(
                id=chunk,
                tenant_id=tenant,
                document_id=document,
                chunk_index=0,
                content="text",
                doc_metadata={"pipeline_hash": "old" if state == "old_pipeline" else "active"},
                disabled_at=datetime.now(timezone.utc) if state == "disabled_chunk" else None,
            )
        )
        if state == "active":
            expected = str(chunk)
    db.commit()
    store = Store()
    assert CorpusIndex(bm25_store=store).rebuild(db, scope=CorpusScope(tenant, (dataset,))) == 1
    assert [doc.id for doc in store.calls[0][1]] == [expected]


@pytest.mark.parametrize("scope_kind", ["dataset", "document", "multi_dataset", "tenant"])
def test_successful_backfill_rotates_all_affected_cache_scopes_without_committing(corpus_db, scope_kind):
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    db, documents, chunks = corpus_db
    tenant, first_dataset, second_dataset, foreign_tenant, foreign_dataset = (uuid4() for _ in range(5))
    ids = []
    for owner, dataset in [(tenant, first_dataset), (tenant, second_dataset), (foreign_tenant, foreign_dataset)]:
        document = _document(db, documents, owner, dataset)
        ids.append(document)
        db.execute(
            chunks.insert().values(
                id=uuid4(), tenant_id=owner, document_id=document, chunk_index=0, content="source", doc_metadata={}
            )
        )
    db.commit()
    corpus = CorpusIndex(bm25_store=Store())
    tracked = [
        CorpusScope(tenant, (first_dataset,)),
        CorpusScope(tenant, document_ids=(ids[0],)),
        CorpusScope(tenant, (second_dataset,)),
        CorpusScope(tenant, document_ids=(ids[1],)),
        CorpusScope(foreign_tenant, (foreign_dataset,)),
        CorpusScope(foreign_tenant, document_ids=(ids[2],)),
    ]
    before = [corpus.resolve_version(item, db=db) for item in tracked]
    assert all(before)
    scopes = {
        "dataset": CorpusScope(tenant, (first_dataset,)),
        "document": CorpusScope(tenant, document_ids=(ids[0],)),
        "multi_dataset": CorpusScope(tenant, (first_dataset, second_dataset)),
        "tenant": CorpusScope(tenant),
    }
    corpus.rebuild(db, scope=scopes[scope_kind], batch_size=1)
    after = [corpus.resolve_version(item, db=db) for item in tracked]
    assert after[0] != before[0] and after[1] != before[1]
    assert (after[2] != before[2]) is (scope_kind in {"multi_dataset", "tenant"})
    assert (after[3] != before[3]) is (scope_kind in {"multi_dataset", "tenant"})
    assert after[4:] == before[4:]
    db.rollback()
    assert [corpus.resolve_version(item, db=db) for item in tracked] == before


def test_failed_native_backfill_does_not_publish_cache_revisions(corpus_db):
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    db, documents, chunks = corpus_db
    tenant, dataset = uuid4(), uuid4()
    document = _document(db, documents, tenant, dataset)
    for index in range(2):
        db.execute(
            chunks.insert().values(
                id=uuid4(), tenant_id=tenant, document_id=document, chunk_index=index, content="source", doc_metadata={}
            )
        )
    db.commit()
    store = Store()
    calls = []

    def fail_second(rows, **kwargs):
        calls.append(rows)
        if len(calls) == 2:
            raise RuntimeError("native batch failed")

    store.upsert = fail_second
    corpus = CorpusIndex(bm25_store=store)
    scope = CorpusScope(tenant, (dataset,))
    before = corpus.resolve_version(scope, db=db)
    with pytest.raises(RuntimeError, match="native batch failed"):
        corpus.rebuild(db, scope=scope, batch_size=1)
    assert len(calls) == 2
    assert corpus.resolve_version(scope, db=db) == before


def test_empty_persisted_rebuild_initializes_the_real_native_schema(corpus_db):
    pytest.importorskip("pymilvus")
    from app.rag.retrieval.corpus_index import CorpusIndex
    from app.storage.bm25.milvus import MilvusBM25Store
    from tests.test_milvus_native_bm25 import Client

    db, _, _ = corpus_db
    client = Client(exists=False)
    result = CorpusIndex(bm25_store=MilvusBM25Store(client=client)).rebuild_persisted_retrieval_indexes(
        db, tenant_id=uuid4()
    )
    assert result["bm25_rebuilt"] is True
    assert client.exists is True
    assert any(name == "create" for name, _ in client.calls)


@pytest.mark.parametrize("apply", [False, True])
def test_backfill_cli_commits_only_explicit_apply(apply, monkeypatch, capsys):
    from app.core import database
    from scripts import backfill_milvus_bm25 as cli

    class Session:
        commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def commit(self):
            self.commits += 1

    db = Session()
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(cli, "run_backfill", lambda **kwargs: {"mode": "apply" if kwargs["apply"] else "dry-run"})
    assert cli.main(["--tenant-id", str(uuid4()), *(["--apply"] if apply else [])]) == 0
    assert db.commits == int(apply)


def test_legacy_persisted_rebuild_cli_commits_its_owned_revision_transaction(monkeypatch):
    from app.core import database
    from app.rag.retriever import HybridRetriever
    from scripts import rebuild_retrieval_indexes as cli

    class Session:
        commits = 0
        closed = False

        def commit(self):
            self.commits += 1

        def close(self):
            self.closed = True

    db = Session()
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        HybridRetriever, "rebuild_persisted_retrieval_indexes", lambda *_args, **_kwargs: {"doc_count": 0}
    )
    monkeypatch.setattr("sys.argv", ["rebuild_retrieval_indexes.py", "--tenant-id", str(uuid4())])
    assert cli.main() == 0
    assert db.commits == 1 and db.closed
