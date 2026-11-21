import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import pytest


def _runtime(name):
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig

    return DatasetEmbeddingRuntimeConfig("openai_compatible", name, "", "", name, "documents_" + name, True)


def _request():
    from app.rag.retrieval.recall.runtime_scope import RetrievalScope
    from app.rag.retrieval.recall.vector_search import VectorSearchRequest

    return VectorSearchRequest(
        query="query",
        top_k=4,
        score_threshold=0.0,
        scope=RetrievalScope(tenant_id=uuid4(), account_id="actor", document_ids=(uuid4(),)),
    )


def test_parallel_vector_shards_preserve_scope_and_owned_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import vector_search
    from app.rag.retrieval.recall.common import _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY
    from app.rag.retrieval.recall.runtime_scope import RuntimeShard

    request = _request()
    runtimes = [_runtime("first"), _runtime("second")]
    barrier = threading.Barrier(2)
    source = {runtime.model: {"content": runtime.model, "score": 0.8, "metadata": {}} for runtime in runtimes}
    source["second"]["score"] = 0.9
    shards = tuple(RuntimeShard(runtime, (uuid4(),)) for runtime in runtimes)
    datasets_by_collection = {shard.runtime.collection_name: str(shard.dataset_ids[0]) for shard in shards}

    class Embeddings:
        def embed_query(self, query):
            return [1.0]

    class Adapter:
        def __init__(self, name):
            self.name = name

        def search(self, **kwargs):
            assert kwargs["metadata_filter"]["tenant_id"] == str(request.scope.tenant_id)
            assert kwargs["metadata_filter"]["document_id"] == {"$in": [str(request.scope.document_ids[0])]}
            assert kwargs["metadata_filter"]["dataset_id"] == datasets_by_collection[self.name]
            barrier.wait(timeout=3)
            return [source[self.name.removeprefix("documents_")]]

    monkeypatch.setattr(vector_search.settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(vector_search.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2)
    monkeypatch.setattr(vector_search, "create_embeddings_for_runtime", lambda runtime: Embeddings())
    monkeypatch.setattr(vector_search, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(vector_search, "get_milvus_adapter", lambda name: Adapter(name))
    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    batch = vector_search.search_runtime_shards(
        request,
        shards=shards,
        vector_store=object(),
    )
    assert batch.failures == () and batch.successful_shards == 2
    first, second = batch.shards
    assert first.shard is shards[0] and second.shard is shards[1]
    assert first.records[0]["content"] == "first" and second.records[0]["content"] == "second"
    assert [item["content"] for item in batch.records] == ["second", "first"]
    assert {item["metadata"][_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY] for item in batch.records} == {
        "first",
        "second",
    }
    assert all(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY not in item["metadata"] for item in source.values())


def test_partial_vector_failure_preserves_the_original_error_and_successful_shard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retrieval.recall import vector_search
    from app.rag.retrieval.recall.runtime_scope import RuntimeShard

    failure = RuntimeError("second dataset unavailable")

    def search(request, *, runtime):
        if runtime.model == "failed":
            raise failure
        return [{"content": "kept", "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(vector_search, "search_dataset_vectors", search)
    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    batch = vector_search.search_runtime_shards(
        _request(),
        shards=(RuntimeShard(_runtime("kept"), (uuid4(),)), RuntimeShard(_runtime("failed"), (uuid4(),))),
        vector_store=object(),
    )
    assert [item["content"] for item in batch.records] == ["kept"]
    assert batch.failures == (failure,) and batch.successful_shards == 1


def test_vector_operation_runs_without_importing_the_reader_adapter() -> None:
    script = """
import importlib.abc
import sys
from uuid import uuid4
class NoReader(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retrieval.recall.retriever':
            raise AssertionError('Vector operation imports reader')
sys.meta_path.insert(0, NoReader())
from app.rag.retrieval.recall import vector_search
from app.rag.retrieval.recall.runtime_scope import RetrievalScope, RuntimeShard
from app.rag.retrieval.recall.vector_search import VectorSearchRequest, search_runtime_shards
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig

vector_search.run_with_retrieval_backend_budget_sync = lambda call, *args: call(*args)
tenant_id, dataset_id, document_id = uuid4(), uuid4(), uuid4()
runtime = DatasetEmbeddingRuntimeConfig('openai_compatible', 'test', '', '', 'space', 'documents', False)
class Store:
    def search(self, **kwargs):
        assert kwargs['tenant_id'] == tenant_id
        assert kwargs['document_ids'] == [document_id]
        assert kwargs['metadata_filter']['dataset_id'] == str(dataset_id)
        return [{'content': 'hit', 'score': 1.0, 'metadata': {'document_id': str(document_id)}}]
batch = search_runtime_shards(
    VectorSearchRequest('query', 1, 0.0, RetrievalScope(tenant_id, 'actor', document_ids=(document_id,))),
    shards=(RuntimeShard(runtime, (dataset_id,)),), vector_store=Store(),
)
assert batch.records[0]['content'] == 'hit'
assert batch.failures == () and batch.successful_shards == 1
assert 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
