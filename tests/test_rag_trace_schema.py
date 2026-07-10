
import json
import time
import uuid

import pytest


def test_list_rag_traces_filters_and_normalizes(monkeypatch, tmp_path):  # noqa: ANN001
    """
    Task 27 contract: history/graph UI needs a stable, PII-safe RAG trace schema.

    We read from the metrics JSONL log (bounded tail), filter by tenant+conversation,
    and return a normalized structure with steps/timings and safe citations.
    """
    from app.core.config import settings
    from app.services.rag_trace_service import list_rag_traces

    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    conversation_id = uuid.uuid4()
    other_conversation = uuid.uuid4()
    now_ms = int(time.time() * 1000)

    metrics_path = tmp_path / "rag_metrics.jsonl"
    records = [
        # Wanted (tenant+conversation match).
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation_id),
            "request_id": "req-1",
            "question": "should-not-leak",
            "query_for_retrieval": "should-not-leak",
            "retrieval": {
                "mode": "hybrid",
                "retrieval_config_hash": "cfg-123",
                "enable_reranker": True,
                "reranker_provider": "cohere",
                "reranker_top_n": 10,
                "query_count": 1,
                "per_query": [
                    {
                        "kind": "main",
                        "query_chars": 12,
                        "elapsed_sec": 0.12,
                        "ok": True,
                        "retriever_debug": {
                            "requested_k": 5,
                            "search_k": 10,
                            "overfetch_enabled": True,
                            "channels": {
                                "timing": {"vector_ms": 12.3, "colbert_ms": 8.7, "bm25_ms": 4.5, "fusion_ms": 1.2},
                                "counts": {"vector_candidates": 10, "colbert_candidates": 4, "bm25_candidates": 8, "sparse_candidates": 6},
                                "retrieval_mode": "hybrid",
                                "fusion_strategy": "rrf",
                                "rrf_k": 60,
                                "fusion_weights": {"vector": 0.6, "keyword": 0.4},
                                "vector_backend": "milvus",
                                "vector": {"enabled": True, "candidates": 10, "filter_applied": False},
                                "colbert_ann": {
                                    "enabled": True,
                                    "used": True,
                                    "provider": "deterministic",
                                    "candidates": 4,
                                    "skipped_reason": "too_many_docs",
                                    "docs_n": 1200,
                                    "max_docs": 1000,
                                },
                                "bm25": {"enabled": True, "candidates": 8, "index_enabled": True, "filter_applied": True},
                                "lexical_db": {
                                    "enabled": False,
                                    "candidates": 0,
                                    "fts_config": "simple",
                                    "trgm_enabled": True,
                                    "pg_trgm_available": True,
                                    "methods": {"fts": 0, "trgm": 0},
                                },
                                "sparse": {"enabled": True, "candidates": 6, "provider": "splade"},
                                "merged_pre_dedup": 20,
                                "merged_post_dedup": 18,
                                "merged_post_rerank": 18,
                                "returned_top_k": 5,
                                "rerank": {
                                    "enabled": True,
                                    "provider": "cohere",
                                    "top_n_config": 10,
                                    "candidates_n": 18,
                                    "used": False,
                                    "elapsed_sec": 0.45,
                                    "model_used": "rerank-v3",
                                    "error": None,
                                    "skip_reason": "provider_disabled",
                                },
                                "attribution": {"vector": 3, "bm25": 2, "lexical_db": 1, "multi": 2},
                                "diversity": {"before": 18, "after": 5, "dropped": 13},
                                "dedup": {
                                    "near_dedup_enabled": True,
                                    "near_dedup_dropped": 2,
                                    "near_dedup_hamming_threshold": 3,
                                    "near_dedup_max_compare": 10,
                                },
                                "cache": {"hit": True, "store_ok": True},
                            },
                            "scope": {
                                "tenant_id": str(tenant_id),
                                "dataset_id": str(uuid.uuid4()),
                                "account_id_present": True,
                                "document_ids_count": 0,
                                "kind": "open",
                            },
                            "enrich_pass1": {"filtered_acl": 2, "output_results": 7},
                        },
                    }
                ],
                "errors": [],
            },
            "citations": [
                {
                    "document_id": str(uuid.uuid4()),
                    "chunk_id": str(uuid.uuid4()),
                    "page_number": 1,
                    "relevance_score": 0.9,
                    "vector_score": 0.123,
                    "bm25_score": 0.456,
                    "lexical_score": 0.789,
                    "sparse_score": 0.314,
                    "colbert_score": 0.271,
                    "retrieval_elapsed_sec": 0.12,
                    "rerank_elapsed_sec": 0.45,
                    "retrieval_role": "main",
                    "neighbor_of": "chunk-0",
                    "kg_path_provenance": {
                        "schema": "mimirq.kg_path_provenance.v1",
                        "kind": "entity_relation",
                        "hops": 1,
                        "nodes": [
                            {"kind": "entity", "entity_id": "e1", "type": "Skill", "name": "should-not-leak"},
                            {"kind": "entity", "entity_id": "e2", "type": "Tool"},
                        ],
                        "edges": [
                            {
                                "kind": "relation",
                                "relation_id": str(uuid.uuid4()),
                                "predicate": "related_to",
                                "confidence": 0.6,
                                "confidence_bucket": "mid",
                                "document_id": str(uuid.uuid4()),
                                "chunk_id": str(uuid.uuid4()),
                                "evidence_quote": "should-not-leak",
                            }
                        ],
                    },
                    "chunk_content": "should-not-leak",
                }
            ],
        },
        # Different conversation => ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "conversation_id": str(other_conversation),
            "retrieval": {"mode": "vector"},
            "citations": [],
        },
        # Different tenant => ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(other_tenant),
            "conversation_id": str(conversation_id),
            "retrieval": {"mode": "vector"},
            "citations": [],
        },
        # Other event => ignored.
        {"event": "reranker_api", "ts_ms": now_ms, "tenant_id": str(tenant_id)},
    ]
    metrics_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(settings, "METRICS_LOG_PATH", str(metrics_path), raising=False)

    res = list_rag_traces(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        limit=20,
        window_minutes=60,
        max_bytes=5000000,
    )

    assert res.enabled is True
    assert res.returned == 1
    assert len(res.items) == 1

    item = res.items[0]
    assert item.request_id == "req-1"
    assert item.citations_count == 1
    assert item.retrieval.mode == "hybrid"
    assert item.retrieval.retrieval_config_hash == "cfg-123"
    assert item.retrieval.per_query and item.retrieval.per_query[0].retriever_debug is not None
    assert item.retrieval.per_query[0].retriever_debug.get("requested_k") == 5
    channels = item.retrieval.per_query[0].retriever_debug.get("channels")
    assert isinstance(channels, dict)
    assert (channels.get("timing") or {}).get("vector_ms") == pytest.approx(12.3)
    assert (channels.get("timing") or {}).get("colbert_ms") == pytest.approx(8.7)
    assert (channels.get("counts") or {}).get("colbert_candidates") == 4
    assert (channels.get("counts") or {}).get("bm25_candidates") == 8
    colbert = channels.get("colbert_ann") or {}
    assert colbert.get("provider") == "deterministic"
    assert colbert.get("skipped_reason") == "too_many_docs"
    assert colbert.get("max_docs") == 1000
    assert (channels.get("rerank") or {}).get("skip_reason") == "provider_disabled"
    scope = item.retrieval.per_query[0].retriever_debug.get("scope") or {}
    assert scope.get("account_id_present") is True
    assert scope.get("dataset_id_present") is True
    assert "tenant_id" not in scope
    assert "dataset_id" not in scope

    assert item.citations and item.citations[0].retrieval_role == "main"
    assert item.citations and item.citations[0].neighbor_of == "chunk-0"
    assert item.citations and item.citations[0].vector_score == pytest.approx(0.123)
    assert item.citations and item.citations[0].bm25_score == pytest.approx(0.456)
    assert item.citations and item.citations[0].lexical_score == pytest.approx(0.789)
    assert item.citations and item.citations[0].sparse_score == pytest.approx(0.314)
    assert item.citations and item.citations[0].colbert_score == pytest.approx(0.271)
    prov = (item.citations[0] or {}).kg_path_provenance
    assert isinstance(prov, dict)
    assert prov.get("schema") == "mimirq.kg_path_provenance.v1"
    assert prov.get("kind") == "entity_relation"
    assert prov.get("hops") == 1
    nodes = prov.get("nodes") or []
    edges = prov.get("edges") or []
    assert isinstance(nodes, list) and len(nodes) == 2
    assert isinstance(edges, list) and len(edges) == 1
    assert "name" not in (nodes[0] or {})
    assert "evidence_quote" not in (edges[0] or {})
    assert any(s.key == "retrieve" for s in item.steps)
    assert any(s.key == "rerank" for s in item.steps)
    assert any(s.key == "citations" for s in item.steps)

    dumped = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
    assert "should-not-leak" not in dumped
    assert "chunk_content" not in dumped


def test_list_rag_traces_disabled_returns_empty(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.rag_trace_service import list_rag_traces

    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", False, raising=False)

    res = list_rag_traces(
        tenant_id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        limit=20,
        window_minutes=60,
        max_bytes=5000000,
    )
    assert res.enabled is False
    assert res.returned == 0
    assert res.items == []
