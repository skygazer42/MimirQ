from __future__ import annotations

import uuid

import pytest


class _EmptyRetriever:
    def __init__(self) -> None:
        self._last_debug_metrics: dict = {
            "requested_k": 5,
            "search_k": 20,
            "query_normalization": {
                "original": "ORIGINAL",
                "normalized": "NORMALIZED",
                "applied_rules": ["rule_a"],
            },
            "enrich_pass2": {
                "input_results": 10,
                "output_results": 0,
                "filtered_acl": 7,
                "filtered_metadata_filter": 3,
                "filtered_pipeline_version": 0,
            },
        }

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return []


def test_orchestrator_emits_empty_retrieval_reasons_when_no_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: disable any LLM-dependent query transforms.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Avoid KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion interfering with trace/metrics.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    assert out.get("citations") == []

    metrics = out.get("metrics") or {}
    empty = metrics.get("empty_retrieval") or {}
    assert "metadata_filter" in (empty.get("reasons") or [])
    assert "acl" in (empty.get("reasons") or [])
    assert (empty.get("signals") or {}).get("filtered_metadata_filter") == 3
    assert (empty.get("signals") or {}).get("filtered_acl") == 7

    qd = out.get("query_debug") or {}
    assert (qd.get("empty_retrieval") or {}).get("reasons") == empty.get("reasons")

