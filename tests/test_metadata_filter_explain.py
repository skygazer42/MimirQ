from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.documents import Document


def test_summarize_metadata_filter_counts_ops_and_keys_without_values() -> None:
    from app.rag.core.filters import summarize_metadata_filter

    spec = {
        "$and": [
            {"department": {"$in": ["hr", "it"]}},
            {"level": {"$gte": 3}},
        ],
        "document_user.tags": {"$contains": "secret"},
        "active": {"$eq": True},
    }

    summary = summarize_metadata_filter(spec)
    assert isinstance(summary, dict)

    assert summary.get("keys_count") == 4
    ops = summary.get("ops") or {}
    assert ops.get("$and") == 1
    assert ops.get("$in") == 1
    assert ops.get("$gte") == 1
    assert ops.get("$contains") == 1
    assert ops.get("$eq") == 1

    dumped = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    # Do not leak filter values.
    for leaked in ("hr", "it", "secret", "3", "True"):
        assert leaked not in dumped


class _FakeRetriever:
    def __init__(self) -> None:
        # Include filter-like values in the raw debug payload to prove sanitizers don't leak them.
        self._last_debug_metrics: dict = {
            "requested_k": 5,
            "search_k": 10,
            "query_normalization": {
                "original": "ORIGINAL",
                "normalized": "NORMALIZED",
                "applied_rules": ["rule_a"],
            },
            "enrich_pass2": {
                "input_results": 3,
                "output_results": 1,
                "filtered_metadata_filter": 2,
                "metadata_filter_blocked": 2,
                "metadata_filter_matched": 1,
                "metadata_filter": {
                    "keys_count": 2,
                    "keys_sample": ["department", "document_user.tags"],
                    "ops": {"$in": 1, "$contains": 1},
                },
                # This field must never survive sanitization.
                "metadata_filter_raw": {"department": {"$in": ["hr"]}},
            },
        }

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        return [
            Document(
                page_content="hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "t.md",
                    "score": 0.9,
                },
            )
        ]


def test_orchestrator_retriever_debug_includes_metadata_filter_explain(monkeypatch: pytest.MonkeyPatch) -> None:
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

    # Avoid dict expansion interfering with trace shape.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(), raising=True)

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

    per_q = (out.get("metrics") or {}).get("retrieval_per_query") or []
    assert per_q
    dbg = (per_q[0] or {}).get("retriever_debug") or {}
    ep2 = (dbg.get("enrich_pass2") or {}) if isinstance(dbg, dict) else {}
    mf = ep2.get("metadata_filter") or {}
    assert mf.get("keys_count") == 2
    assert (mf.get("ops") or {}).get("$in") == 1

    dumped = json.dumps(dbg, ensure_ascii=False, sort_keys=True)
    assert "hr" not in dumped

