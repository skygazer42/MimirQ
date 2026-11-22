import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.documents import Document


class _NativeStore:
    def __init__(self):
        self.documents_by_tenant = {}

    def upsert(self, documents, *, tenant_id):
        records = self.documents_by_tenant.setdefault(tenant_id, {})
        for document in documents:
            assert document.metadata["tenant_id"] == str(tenant_id)
            records[document.id] = document

    def search(self, query, *, tenant_id, dataset_ids, document_ids, metadata_filter, top_k):
        assert not document_ids and metadata_filter is None
        documents = self.documents_by_tenant.get(tenant_id, {}).values()
        datasets = {str(dataset_id) for dataset_id in dataset_ids}
        selected = [
            document
            for document in documents
            if (not datasets or document.metadata["dataset_id"] in datasets) and query in document.page_content
        ]
        return [{"chunk_id": document.id, "metadata": document.metadata} for document in selected[:top_k]]

    def delete(self, *, tenant_id, metadata_filter):
        documents = self.documents_by_tenant[tenant_id]
        removed = [
            document_id
            for document_id, document in documents.items()
            if document.metadata["dataset_id"] == metadata_filter["dataset_id"]
        ]
        for document_id in removed:
            del documents[document_id]
        return len(removed)


def test_corpus_scope_is_an_immutable_explicit_identity() -> None:
    from app.rag.retrieval.corpus import CorpusScope

    scope = CorpusScope(tenant_id=uuid4(), dataset_ids=(uuid4(),), document_ids=())
    with pytest.raises(FrozenInstanceError):
        scope.tenant_id = uuid4()


def test_corpus_upsert_search_delete_keeps_tenant_and_dataset_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.corpus import CorpusIndex, CorpusScope

    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    corpus = CorpusIndex(bm25_store=_NativeStore())
    tenants, datasets = (uuid4(), uuid4()), (uuid4(), uuid4())
    expected = {}
    for tenant_id in tenants:
        for dataset_id in datasets:
            documents = [
                Document(
                    page_content=text,
                    id=str(uuid4()),
                    metadata={
                        "tenant_id": str(tenant_id),
                        "dataset_id": str(dataset_id),
                        "document_id": str(uuid4()),
                        "chunk_index": 0,
                    },
                )
                for text in ("orchard apple", "winter river", "stone mountain")
            ]
            expected[(tenant_id, dataset_id)] = documents[0].id
            corpus.upsert(None, tenant_id=tenant_id, documents=documents)

    for tenant_id in tenants:
        for dataset_id in datasets:
            result = corpus.search(
                "orchard",
                scope=CorpusScope(tenant_id=tenant_id, dataset_ids=(dataset_id,), document_ids=()),
                top_k=1,
                metadata_filter=None,
            )
            assert result.records[0]["chunk_id"] == expected[(tenant_id, dataset_id)]
            assert result.records[0]["metadata"]["tenant_id"] == str(tenant_id)
            assert result.records[0]["metadata"]["dataset_id"] == str(dataset_id)

    removed = corpus.remove(tenant_id=tenants[0], metadata_filter={"dataset_id": str(datasets[0])})
    assert removed == 3
    assert (
        corpus.search(
            "orchard",
            scope=CorpusScope(tenant_id=tenants[0], dataset_ids=(datasets[0],), document_ids=()),
            top_k=1,
            metadata_filter=None,
        ).records
        == []
    )
    remaining = corpus.search(
        "orchard",
        scope=CorpusScope(tenant_id=tenants[1], dataset_ids=(datasets[0],), document_ids=()),
        top_k=1,
        metadata_filter=None,
    )
    assert remaining.records[0]["chunk_id"] == expected[(tenants[1], datasets[0])]


def test_indexer_import_does_not_load_the_query_retriever() -> None:
    code = """
import importlib.abc
import sys
class NoQueryRetriever(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retrieval.recall.retriever':
            raise AssertionError('Indexer imports the query retriever')
sys.meta_path.insert(0, NoQueryRetriever())
from app.rag.ingestion.indexing.indexer import Indexer
from app.rag.retrieval.corpus import get_corpus_index
assert get_corpus_index() is get_corpus_index()
assert 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_streaming_corpus_query_error_is_not_replaced_by_an_unbounded_read() -> None:
    from app.rag.retrieval.corpus import CorpusIndex

    failure = TypeError("database streaming failed")

    class Query:
        def yield_per(self, _batch_size):
            raise failure

        def all(self):
            return []

    with pytest.raises(TypeError, match="database streaming failed") as result:
        CorpusIndex._iter_query_rows(Query(), batch_size=32)
    assert result.value is failure


def test_writer_session_version_is_not_published_into_the_shared_reader_token_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.rag.retrieval import corpus as corpus_index
    from app.rag.retrieval.corpus import CorpusIndex, CorpusScope
    from app.services.retrieval import corpus_tokens as corpus_cache_tokens

    class Session:
        def __init__(self, token):
            self.token = token
            self.closed = False

        def close(self):
            self.closed = True

    writer = Session("uncommitted-version")
    reader = Session("committed-version")
    owner = CorpusIndex()
    scope = CorpusScope(tenant_id=uuid4(), dataset_ids=(uuid4(),))
    monkeypatch.setattr(corpus_index, "time", SimpleNamespace(monotonic=lambda: 42.0))
    monkeypatch.setattr(owner, "_open_session", lambda: reader)
    monkeypatch.setattr(corpus_cache_tokens, "resolve_corpus_cache_token", lambda db, **_kwargs: db.token)
    assert owner.resolve_version(scope, db=writer) == "uncommitted-version"
    assert owner.resolve_version(scope) == "committed-version"
    assert reader.closed and not writer.closed


def test_upsert_refreshes_existing_tenant_and_multi_dataset_views_with_call_local_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.corpus import CorpusIndex, CorpusScope

    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    tenant_id, dataset_a, dataset_b = uuid4(), uuid4(), uuid4()
    owner = CorpusIndex(bm25_store=_NativeStore())
    documents = [
        Document(
            page_content=text,
            id=str(uuid4()),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(uuid4()),
                "chunk_index": 0,
            },
        )
        for dataset_id, text in [(dataset_a, "old orchard"), (dataset_b, "winter river"), (dataset_b, "stone mountain")]
    ]
    scopes = [CorpusScope(tenant_id=tenant_id), CorpusScope(tenant_id=tenant_id, dataset_ids=(dataset_a, dataset_b))]
    owner.upsert(None, tenant_id=tenant_id, documents=documents)
    for scope in scopes:
        assert owner.search("cobalt", scope=scope, top_k=1, metadata_filter=None).records == []
    incoming = Document(
        page_content="cobalt orchard",
        id=str(uuid4()),
        metadata={
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_a),
            "document_id": str(uuid4()),
            "chunk_index": 0,
        },
    )
    owner.upsert(None, tenant_id=tenant_id, documents=[incoming])
    results = [owner.search("cobalt", scope=scope, top_k=1, metadata_filter=None) for scope in scopes]
    assert [result.records[0]["chunk_id"] for result in results] == [incoming.id, incoming.id]
    assert results[0].status is not results[1].status
    results[1].status["reason"] = "changed by caller"
    assert results[0].status["reason"] == "ok"
