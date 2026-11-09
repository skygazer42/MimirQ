from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize(
    "field,value", [("MILVUS_BM25_COLLECTION_NAME", "new_full_text_index"), ("MILVUS_BM25_MAX_CANDIDATES", 1234)]
)
def test_native_collection_and_candidate_limit_partition_retrieval_caches(field, value, monkeypatch):
    from app.core.config import settings
    from app.rag.retrieval.retriever_options import HybridSearchOptions, _build_retrieval_cache_behavior_hash
    from app.rag.retriever import HybridRetriever

    reader = HybridRetriever(tenant_id=uuid4())
    options = HybridSearchOptions()
    first = _build_retrieval_cache_behavior_hash(retriever=reader, options=options)
    assert first == _build_retrieval_cache_behavior_hash(retriever=reader, options=options)
    monkeypatch.setattr(settings, field, value)
    assert first != _build_retrieval_cache_behavior_hash(retriever=reader, options=options)


@pytest.mark.parametrize("parallelism", [1, 2])
def test_native_readiness_error_escapes_actual_serial_and_parallel_orchestration(parallelism):
    from app.rag.retrieval.orchestrator import RetrievalRuntimeState, _run_retrieval_plan
    from app.storage.bm25.milvus import BM25IndexNotReadyError

    def unavailable(_query):
        raise BM25IndexNotReadyError("native index needs backfill")

    reader = SimpleNamespace(invoke=unavailable)
    ctx = RetrievalRuntimeState(state={}, question="question", history_text="")
    ctx.retrieval_parallelism = parallelism
    ctx.retrieval_plan = [("main", "first query", reader), ("rewrite", "second query", reader)]
    with pytest.raises(BM25IndexNotReadyError):
        _run_retrieval_plan(ctx)


@pytest.mark.parametrize("backend", ["chroma", "qdrant"])
def test_non_milvus_generic_rebuild_keeps_other_index_kinds_running(backend, monkeypatch):
    from app.core.config import settings
    from app.services import indexer as module

    monkeypatch.setattr(settings, "VECTOR_BACKEND", backend)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)

    def forbidden():
        pytest.fail("Non-Milvus maintenance must not reach native BM25 storage")

    monkeypatch.setattr(module, "get_corpus_index", forbidden)
    owner = object.__new__(module.Indexer)
    events = []
    owner.rebuild_event_indexes = lambda **kwargs: events.append(kwargs)
    tenant = uuid4()
    owner.rebuild_tenant(tenant_id=tenant)
    assert events == [{"tenant_id": tenant, "document_ids": None}]


@pytest.mark.parametrize(
    "field,value", [("MILVUS_BM25_COLLECTION_NAME", "new_answer_index"), ("MILVUS_BM25_MAX_CANDIDATES", 1200)]
)
def test_native_settings_also_partition_the_outer_chat_response_cache(field, value, monkeypatch):
    from app.core.config import settings
    from app.services.chat_response_cache import build_chat_cache_key

    args = dict(
        tenant_id=str(uuid4()),
        account_id="member",
        dataset_id=str(uuid4()),
        document_ids=[],
        question="question",
        rag_config={},
        prompt_config={},
        structured_output=False,
        structured_preset=None,
        use_graph=False,
        corpus_cache_token="same-corpus",
    )
    first = build_chat_cache_key(**args)
    assert first == build_chat_cache_key(**args)
    monkeypatch.setattr(settings, field, value)
    assert first != build_chat_cache_key(**args)
