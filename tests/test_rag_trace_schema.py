from __future__ import annotations

import json
import time
import uuid


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
    scope = item.retrieval.per_query[0].retriever_debug.get("scope") or {}
    assert scope.get("account_id_present") is True
    assert scope.get("dataset_id_present") is True
    assert "tenant_id" not in scope
    assert "dataset_id" not in scope

    assert item.citations and item.citations[0].retrieval_role == "main"
    assert item.citations and item.citations[0].neighbor_of == "chunk-0"
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
