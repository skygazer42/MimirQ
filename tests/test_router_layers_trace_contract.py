from __future__ import annotations

from app.rag.trace_schema import RagTraceRetrieval


def test_rag_trace_retrieval_accepts_router_layers_payload() -> None:
    payload = {
        "schema": "mimirq.router_layers.v1",
        "entity": {"decision": "partition_keys", "used": True, "partition_keys": ["ACME"]},
        "intent": {"decision": "general", "used": False, "reason_codes": ["general:short_ascii"]},
        "composite": {"decision": "compare", "used": True, "reason_codes": ["compare_pattern"]},
    }

    retrieval = RagTraceRetrieval(router_layers=payload)
    assert retrieval.router_layers == payload
