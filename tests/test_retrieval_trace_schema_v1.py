from __future__ import annotations

import uuid

import langchain
import pytest
from langchain_core.documents import Document


@pytest.fixture(autouse=True)
def _stub_langchain_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langchain, "debug", False, raising=False)
    monkeypatch.setattr(langchain, "verbose", False, raising=False)


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        # Include a debug payload with normalized text so the trace sanitizer can prove it strips it.
        self._last_debug_metrics: dict = {
            "requested_k": 5,
            "search_k": 5,
            "query_normalization": {
                "original": "ORIGINAL",
                "normalized": "NORMALIZED",
                "applied_rules": ["rule_a"],
            },
            "diversity": {
                "max_chunks_per_doc": 3,
                "max_chunks_per_page": 1,
                "min_distinct_docs": 0,
                "pre_unique_docs": 1,
                "post_unique_docs": 1,
                "pre_unique_pages": 1,
                "post_unique_pages": 1,
                "moved_out": 0,
                "moved_in": 0,
            },
        }

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_emits_stable_retrieval_trace_schema(monkeypatch: pytest.MonkeyPatch) -> None:
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

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    retriever = _FakeRetriever(
        docs=[
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
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(doc_id)],
            "top_k": 5,
            "retrieval_mode": "vector",
            "enable_hierarchy_recall": True,
            "hierarchy_family_collapse": True,
            "hierarchy_family_aggregation": "combined",
            "hierarchy_tree_dedup": True,
            "hierarchy_parent_depth": 1,
            "hierarchy_sibling_window": 2,
            "hierarchy_overfetch_factor": 4,
            "parse_repair_actions": {
                "run_id": "parse-repair-001",
                "actions": [
                    {"document_id": str(doc_id), "action": "reparse_document", "status": "scheduled", "priority": "high"}
                ],
            },
            "metrics": {},
        }
    )

    trace = out.get("retrieval_trace")
    assert isinstance(trace, dict)
    assert trace.get("schema") == "mimirq.retrieval_trace_pass.v1"

    # Lock the stable top-level sections.
    for key in (
        "contract_diagnostics",
        "adaptive_router",
        "router_layers",
        "contextual_followup",
        "iterative_pass",
        "hard_fallback",
        "rewrite",
        "expansions",
        "retrieval",
        "query_variant_fusion",
        "post_rerank",
        "abstain",
        "citations",
        "parse_quality",
        "parse_repair_actions",
    ):
        assert key in trace

    hierarchy = trace.get("hierarchy_recall") or {}
    assert hierarchy.get("enabled") is True
    assert hierarchy.get("family_collapse") is True
    assert hierarchy.get("family_aggregation") == "combined"
    assert hierarchy.get("tree_dedup") is True
    assert hierarchy.get("parent_depth") == 1
    assert hierarchy.get("sibling_window") == 2
    assert hierarchy.get("overfetch_factor") == 4

    # Retrieval trace is intentionally separate from query_debug: no raw question text.
    assert "original" not in trace

    # Sanitizer should strip normalized query text from retriever_debug payloads.
    per_query = (trace.get("retrieval") or {}).get("per_query") or []
    assert per_query
    dbg = (per_query[0] or {}).get("retriever_debug") or {}
    qn = dbg.get("query_normalization") or {}
    assert "normalized" not in qn

    # Diversity caps should be preserved (PII-safe; numeric only).
    div = dbg.get("diversity") or {}
    assert div.get("max_chunks_per_page") == 1

    contract_diag = trace.get("contract_diagnostics") or {}
    assert isinstance(contract_diag, dict)
    must_recall = contract_diag.get("must_recall") or {}
    assert isinstance(must_recall, dict)
    assert "status" in must_recall
    assert "second_pass" in must_recall
    proof = must_recall.get("proof") or {}
    assert isinstance(proof, dict)
    assert proof.get("schema") == "mimirq.must_recall_proof.v1"
    ledger = proof.get("obligation_ledger") or {}
    assert isinstance(ledger, dict)
    assert ledger.get("schema") == "mimirq.recall_obligation_ledger.v1"

    metrics = out.get("metrics") or {}
    assert isinstance(metrics.get("must_recall_proof"), dict)

    qd = out.get("query_debug") or {}
    assert isinstance((qd.get("parse_repair_actions") if isinstance(qd, dict) else {}), dict)
    rc = (qd.get("retrieval_contract") if isinstance(qd, dict) else {}) or {}
    assert isinstance((rc.get("must_recall_proof") if isinstance(rc, dict) else {}), dict)

    repair = trace.get("parse_repair_actions") or {}
    assert repair.get("actions_total") == 1
    assert repair.get("run_id") == "parse-repair-001"

    contextual = trace.get("contextual_followup") or {}
    assert isinstance(contextual, dict)
    assert "enabled" in contextual
    assert "attempted" in contextual
    assert "used" in contextual

    router_layers = trace.get("router_layers") or {}
    assert router_layers.get("schema") == "mimirq.router_layers.v1"
    assert "entity" in router_layers
    assert "intent" in router_layers
    assert "composite" in router_layers
