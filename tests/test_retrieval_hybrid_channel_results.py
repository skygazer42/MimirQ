import uuid
from types import SimpleNamespace

import pytest


def _embedding_runtime():
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    return DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )


def _configure_retrieval_test(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    for name, value in {
        "BM25_INDEX_ENABLED": True,
        "COLBERT_RETRIEVAL_ENABLED": False,
        "COLPALI_RETRIEVAL_ENABLED": False,
        "LEXICAL_DB_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
        "RAG_CONTEXT_STITCHING_ENABLED": False,
        "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY": False,
        "RETRIEVAL_GOVERNANCE_PREFER_LATEST": False,
        "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED": False,
        "RETRIEVAL_METADATA_EXACT_PRE_FUSION_ENABLED": True,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)


def _build_retriever(monkeypatch: pytest.MonkeyPatch, **overrides):
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    runtime = _embedding_runtime()
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_document_dataset_scope",
        lambda self, *, tenant_id, document_ids: ((), True),  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(
        HybridRetriever, "_enrich_results_with_db_metadata", lambda self, results, **kwargs: list(results)
    )
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, results: list(results))
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, results: list(results))

    vector_store = SimpleNamespace(search=lambda **kwargs: [])
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: vector_store)

    defaults = {
        "k": 3,
        "document_ids": [uuid.uuid4()],
        "retrieval_mode": "hybrid",
        "sparse_enabled": False,
        "enable_reranker": False,
        "dedup_enabled": False,
        "max_chunks_per_doc": 0,
        "max_chunks_per_page": 0,
        "min_distinct_docs": 0,
    }
    defaults.update(overrides)
    return HybridRetriever(**defaults), vector_store


def test_hybrid_search_normalizes_vector_candidates_and_exact_anchor_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retriever, vector_store = _build_retriever(
        monkeypatch,
        retrieval_mode="vector",
        metadata_filter_enabled=True,
        metadata_filter={"region": "east"},
    )
    tenant_id = uuid.uuid4()
    document_id = retriever.document_ids[0]
    tenant_key = retriever._tenant_key(tenant_id)
    retriever._chunk_id_lookup[tenant_key] = {f"{document_id}:2": "chunk-2"}

    vector_store.search = lambda **kwargs: [  # noqa: ARG005
        {
            "content": "filtered doc mismatch",
            "score": 0.95,
            "metadata": {"document_id": str(uuid.uuid4()), "chunk_index": 0, "region": "east"},
        },
        {
            "content": "filtered region mismatch",
            "score": 0.9,
            "metadata": {"document_id": str(document_id), "chunk_index": 1, "region": "west"},
        },
        {
            "content": "allowed anchor",
            "score": 0.4,
            "metadata": {
                "document_id": str(document_id),
                "chunk_index": 2,
                "region": "east",
                "document_title": "常州市市场监督管理局",
            },
        },
    ]

    results = retriever._hybrid_search(
        "常州市市场监督管理局地址",
        top_k=3,
        score_threshold=0.0,
        document_ids=[document_id],
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter={"region": "east"},
    )

    assert [item["content"] for item in results] == ["filtered region mismatch", "allowed anchor"]
    assert results[1]["chunk_id"] == "chunk-2"
    assert results[1]["metadata"]["chunk_id"] == "chunk-2"
    assert results[1]["metadata_exact_match_field"] == "document_title"
    assert retriever._last_channel_metrics["counts"]["vector_candidates"] == 2
    assert retriever._last_channel_metrics["metadata_exact_pre_fusion"] == {
        "enabled": True,
        "annotated": 1,
        "promoted": 1,
        "vector": {"annotated": 1, "promoted": 1},
    }
    assert retriever._last_channel_metrics["retrieval_degraded"] is False
    assert retriever._last_channel_metrics["degraded_reasons"] == []


def test_bm25_candidates_preserve_active_pipeline_identity() -> None:
    from app.rag.retriever import HybridRetriever

    metadata = HybridRetriever._candidate_metadata_from_doc(
        {
            "document_id": "doc-1",
            "pipeline_hash": "pipeline-v2",
            "doc_pipeline_key": "doc-1:pipeline-v2",
            "active_pipeline_hash": "pipeline-v2",
        },
        chunk_id="chunk-1",
    )

    assert metadata["pipeline_hash"] == "pipeline-v2"
    assert metadata["doc_pipeline_key"] == "doc-1:pipeline-v2"
    assert metadata["active_pipeline_hash"] == "pipeline-v2"


def test_invoke_preserves_debug_degradation_contract_with_bm25_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retriever, vector_store = _build_retriever(monkeypatch, k=1)

    def fail_vector(**kwargs):  # noqa: ANN003
        raise ConnectionError("milvus unavailable")

    vector_store.search = fail_vector
    monkeypatch.setattr(
        type(retriever),
        "_search_bm25",
        lambda self, **kwargs: [  # noqa: ANN001,ARG005
            {
                "chunk_id": "chunk-1",
                "content": "fallback result",
                "score": 0.8,
                "metadata": {"document_id": "doc-1"},
            }
        ],
    )

    docs = retriever.invoke("fallback query")

    assert [doc.page_content for doc in docs] == ["fallback result"]
    assert retriever._last_debug_metrics["retrieval_degraded"] is True
    assert retriever._last_debug_metrics["retrieval_degraded_reasons"] == [
        {"channel": "vector", "error_type": "ConnectionError"}
    ]
    assert retriever._last_debug_metrics["all_retrieval_channels_failed"] is False
    assert retriever._last_debug_metrics["channels"]["attempted_channels"] == ["bm25", "vector"]
    assert retriever._last_debug_metrics["channels"]["successful_channels"] == ["bm25"]
    assert retriever._last_debug_metrics["scope"]["kind"] == "document_ids"
