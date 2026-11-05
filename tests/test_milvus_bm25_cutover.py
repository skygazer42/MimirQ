import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.documents import Document


class Store:
    def __init__(self):
        self.calls = []
        self.records = []

    def upsert(self, documents, *, tenant_id):
        self.calls.append(("upsert", documents, tenant_id))
        return len(documents)

    def search(self, query, **kwargs):
        self.calls.append(("search", query, kwargs))
        return list(self.records)

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return 4


def test_shared_corpus_reads_and_writes_native_storage_without_local_bm25(monkeypatch):
    from app.core.config import settings
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    tenant, dataset, document, chunk = uuid4(), uuid4(), uuid4(), uuid4()
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    doc = Document(
        id=str(chunk),
        page_content="正文",
        metadata={"tenant_id": str(tenant), "dataset_id": str(dataset), "document_id": str(document)},
    )
    corpus.upsert(None, tenant_id=tenant, documents=[doc])
    store.records = [{"chunk_id": str(chunk), "content": "changed on server", "metadata": {}, "score": 3.0}]
    result = corpus.search(
        "查询", scope=CorpusScope(tenant, (dataset,), (document,)), top_k=3, metadata_filter={"kind": "faq"}
    )
    assert result.records == store.records
    assert result.status["provider"] == "milvus_bm25"
    assert store.calls[-1][2]["dataset_ids"] == (dataset,)
    assert store.calls[-1][2]["document_ids"] == (document,)
    store.records = []
    assert corpus.search("查询", scope=CorpusScope(tenant), top_k=3, metadata_filter=None).records == []
    assert not hasattr(corpus, "_bm25_retrievers")
    assert not hasattr(corpus, "_bm25_docs")
    assert corpus.remove(tenant_id=tenant, metadata_filter={"document_id": str(document)}) == 4


@pytest.mark.parametrize("backend", ["chroma", "faiss", "memory"])
def test_non_milvus_backend_disables_bm25_without_contacting_milvus(backend, monkeypatch):
    from app.core.config import settings
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope
    from app.rag.retriever import HybridRetriever
    from app.services.indexer import Indexer

    monkeypatch.setattr(settings, "VECTOR_BACKEND", backend)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    store = Store()
    result = CorpusIndex(bm25_store=store).search("text", scope=CorpusScope(uuid4()), top_k=3, metadata_filter=None)
    assert result.records == [] and result.status["reason"] == "requires_milvus"
    assert not store.calls
    assert HybridRetriever()._hybrid_channel_policy().bm25_enabled is False
    indexer = object.__new__(Indexer)
    assert indexer._resolve_bm25_enabled(None) is False


def test_actual_index_writer_import_does_not_load_query_retriever():
    code = """
import importlib.abc
import sys
class NoRetriever(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retriever':
            raise AssertionError('Writer still imports the query retriever')
sys.meta_path.insert(0, NoRetriever())
from app.services.indexer import Indexer
assert 'app.rag.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    assert result.returncode == 0, result.stderr


def test_rebuild_published_corpus_batches_native_upserts_and_keeps_dataset_ids(monkeypatch):
    monkeypatch.setattr(
        "app.services.corpus_cache_tokens.invalidate_corpus_cache_scope", lambda *_args, **_kwargs: None
    )
    from app.core.config import settings
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    store = Store()
    corpus = CorpusIndex(bm25_store=store)
    docs = [
        Document(
            id=str(uuid4()),
            page_content="published text",
            metadata={"tenant_id": str(tenant), "dataset_id": str(dataset), "document_id": str(document)},
        )
        for _ in range(5)
    ]
    monkeypatch.setattr(corpus, "_load_retrieval_docs_for_rebuild", lambda *_args, **_kwargs: docs)
    assert corpus.rebuild(object(), scope=CorpusScope(tenant, (dataset,)), batch_size=2) == 5
    calls = [call for call in store.calls if call[0] == "upsert"]
    assert [len(call[1]) for call in calls] == [2, 2, 1]
    assert all(doc.metadata["dataset_id"] == str(dataset) for call in calls for doc in call[1])


def test_corpus_native_error_is_not_converted_into_a_healthy_empty_response(monkeypatch):
    from app.core.config import settings
    from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    store = Store()

    def fail(*_args, **_kwargs):
        raise RuntimeError("native store unavailable")

    store.search = fail
    with pytest.raises(RuntimeError, match="native store unavailable"):
        CorpusIndex(bm25_store=store).search("text", scope=CorpusScope(uuid4()), top_k=3, metadata_filter=None)


def test_missing_native_index_reaches_the_real_channel_caller(monkeypatch):
    from types import SimpleNamespace

    from app.core.config import settings
    from app.rag.retrieval.corpus_index import CorpusIndex
    from app.rag.retrieval.hybrid.channel_collection import ChannelRequest, collect_channels
    from app.rag.retrieval.retriever_options import HybridSearchOptions
    from app.rag.retriever import HybridRetriever
    from app.storage.bm25.milvus import BM25IndexNotReadyError

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)
    store = Store()

    def unavailable(*_args, **_kwargs):
        raise BM25IndexNotReadyError("native index needs backfill")

    store.search = unavailable
    request = ChannelRequest(
        "question",
        HybridSearchOptions(retrieval_mode="keyword"),
        SimpleNamespace(scope=SimpleNamespace(tenant_id=uuid4(), dataset_ids=(), document_ids=()), keyword_filter={}),
    )
    with pytest.raises(BM25IndexNotReadyError):
        collect_channels(
            request, policy=HybridRetriever()._hybrid_channel_policy(), corpus_index=CorpusIndex(bm25_store=store)
        )


def test_native_readiness_error_has_an_actionable_http_contract():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.exceptions import register_exception_handlers
    from app.storage.bm25.milvus import BM25IndexNotReadyError

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/native-index")
    def check():
        raise BM25IndexNotReadyError("Native full-text index needs backfill")

    response = TestClient(app, raise_server_exceptions=False).get("/native-index")
    assert response.status_code == 503
    assert response.json()["error"] == "BM25_INDEX_NOT_READY"
