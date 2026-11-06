import uuid
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from app.rag.retrieval.corpus_index import CorpusIndex
from tests.test_milvus_bm25_cutover import Store


def test_rebuild_persisted_retrieval_indexes_blocks_scope_over_cap(monkeypatch):
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    monkeypatch.setattr("app.rag.retrieval.corpus_index.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 2)
    monkeypatch.setattr(corpus, "_count_retrieval_docs_in_db", lambda *_args, **_kwargs: 3)
    monkeypatch.setattr(
        corpus,
        "_load_retrieval_docs_from_db",
        lambda *_args, **_kwargs: pytest.fail("over-cap corpus must not be read"),
    )
    with pytest.raises(RuntimeError, match="RETRIEVAL_REBUILD_MAX_CHUNKS=2"):
        corpus.rebuild_persisted_retrieval_indexes(object(), tenant_id=uuid.uuid4())
    assert store.calls == []


def test_rebuild_persisted_retrieval_indexes_rechecks_cap_after_load(monkeypatch):
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    docs = [Document(page_content="text", id=str(uuid.uuid4())) for _ in range(3)]
    limits = []
    monkeypatch.setattr("app.rag.retrieval.corpus_index.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 2)
    monkeypatch.setattr(corpus, "_count_retrieval_docs_in_db", lambda *_args, **_kwargs: 2)

    def load(*_args, **kwargs):
        limits.append(kwargs["max_chunks"])
        return docs

    monkeypatch.setattr(corpus, "_load_retrieval_docs_from_db", load)
    with pytest.raises(RuntimeError, match="RETRIEVAL_REBUILD_MAX_CHUNKS=2"):
        corpus.rebuild_persisted_retrieval_indexes(object(), tenant_id=uuid.uuid4())
    assert limits == [3] and store.calls == []


def test_disabled_rebuild_cap_skips_the_count_query(monkeypatch):
    corpus = CorpusIndex(bm25_store=Store())
    monkeypatch.setattr("app.rag.retrieval.corpus_index.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 0)
    monkeypatch.setattr(
        corpus, "_count_retrieval_docs_in_db", lambda *_args, **_kwargs: pytest.fail("count should be skipped")
    )
    monkeypatch.setattr(corpus, "_load_retrieval_docs_from_db", lambda *_args, **_kwargs: [])
    assert corpus._load_retrieval_docs_for_rebuild(object(), tenant_id=uuid.uuid4()) == []


def test_rebuild_persisted_retrieval_indexes_builds_under_cap(monkeypatch):
    monkeypatch.setattr(
        "app.services.corpus_cache_tokens.invalidate_corpus_cache_scope", lambda *_args, **_kwargs: None
    )
    from app.core.config import settings

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)
    monkeypatch.setattr(settings, "RETRIEVAL_REBUILD_MAX_CHUNKS", 2)
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    docs = [Document(page_content="text", id=str(uuid.uuid4())) for _ in range(2)]
    tenant = uuid.uuid4()
    monkeypatch.setattr(corpus, "_count_retrieval_docs_in_db", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(corpus, "_load_retrieval_docs_from_db", lambda *_args, **_kwargs: docs)
    result = corpus.rebuild_persisted_retrieval_indexes(object(), tenant_id=tenant, batch_size=8)
    assert result["doc_count"] == 2 and result["bm25_rebuilt"] is True
    assert store.calls == [("upsert", docs, tenant)]


def test_indexer_rebuild_chunk_indexes_uses_operational_rebuild_helper(monkeypatch):
    import app.services.indexer as module

    tenant = uuid.uuid4()
    document_ids = [uuid.uuid4(), uuid.uuid4()]
    touched, calls = [], []
    indexer = module.Indexer.__new__(module.Indexer)
    indexer._db = SimpleNamespace(flush=lambda: None)
    indexer._touch_chunk_retrieval_scope = lambda **kwargs: touched.append(kwargs["document_id"])
    monkeypatch.setattr(module.settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(
        module,
        "get_corpus_index",
        lambda: SimpleNamespace(
            rebuild_bm25_index_for_operational_scope=lambda db, **kwargs: calls.append(kwargs) or 2
        ),
    )
    indexer.rebuild_chunk_indexes(tenant_id=tenant, document_ids=document_ids)
    assert calls == [{"tenant_id": tenant, "document_ids": document_ids, "batch_size": 2000}]
    assert touched == document_ids
