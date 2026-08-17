import uuid

import langchain
import pytest
from langchain_core.documents import Document


@pytest.fixture(autouse=True)
def _stub_langchain_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langchain, "debug", False, raising=False)
    monkeypatch.setattr(langchain, "verbose", False, raising=False)


class _FakeRetriever:
    def __init__(self, *, docs: list[Document], debug_metrics: dict | None = None) -> None:
        self._docs = list(docs)
        # Include a debug payload with normalized text so the trace sanitizer can prove it strips it.
        self._last_debug_metrics: dict = debug_metrics or {
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
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
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
    monkeypatch.setattr(
        orch_mod,
        "get_rag_engine",
        lambda: pytest.fail("retrieval-only paths must not initialize the LLM engine"),
        raising=True,
    )

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
                    {
                        "document_id": str(doc_id),
                        "action": "reparse_document",
                        "status": "scheduled",
                        "priority": "high",
                    }
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
    query_metrics = metrics.get("retrieval_per_query") or []
    assert query_metrics[0]["query_chars"] == 1
    assert query_metrics[0]["query_tokens"] > 0

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


def test_orchestrator_preserves_degradation_contract_in_query_debug_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

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
                page_content="degraded hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "degraded.md",
                    "score": 0.8,
                },
            )
        ],
        debug_metrics={
            "query_normalization": {
                "original": "ORIGINAL",
                "normalized": "NORMALIZED",
                "applied_rules": ["rule_a"],
            },
            "channels": {
                "attempted_channels": ["vector", "sparse"],
                "successful_channels": ["vector"],
                "retrieval_degraded": True,
                "degraded_reasons": [
                    {"channel": "sparse", "error_type": "timeout", "detail": "ignored by public contract"}
                ],
                "all_retrieval_channels_failed": False,
            },
        },
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
            "metrics": {},
        }
    )

    query_debug = out.get("query_debug") or {}
    assert query_debug.get("retrieval_degraded") is True
    assert query_debug.get("retrieval_degraded_reasons") == ["main:sparse:timeout"]
    channel_health = query_debug.get("channel_health") or {}
    assert channel_health.get("attempted_channels") == ["vector", "sparse"]
    assert channel_health.get("successful_channels") == ["vector"]
    assert channel_health.get("all_retrieval_channels_failed") is False

    trace = out.get("retrieval_trace") or {}
    retrieval = trace.get("retrieval") or {}
    assert retrieval.get("retrieval_degraded") is True
    assert retrieval.get("retrieval_degraded_reasons") == ["main:sparse:timeout"]
    assert (retrieval.get("channel_health") or {}).get("queries") == [
        {
            "kind": "main",
            "attempted_channels": ["vector", "sparse"],
            "successful_channels": ["vector"],
            "retrieval_degraded": True,
            "degraded_reasons": [
                {"channel": "sparse", "error_type": "timeout", "detail": "ignored by public contract"}
            ],
            "all_retrieval_channels_failed": False,
        }
    ]


def test_orchestrator_preserves_query_contract_defaults_and_hash_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestration.query_contract as contract_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )
    monkeypatch.setattr(contract_mod, "guess_retrieval_mode", lambda _q: "vector", raising=True)

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    retriever = _FakeRetriever(
        docs=[
            Document(
                page_content="contract hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "contract.md",
                    "score": 0.7,
                },
            )
        ]
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    def _run(dataset_id: str, document_id: str) -> dict:
        return orch_mod.run_retrieval(
            {
                "question": "q",
                "history": [],
                "tenant_id": str(uuid.uuid4()),
                "account_id": "u",
                "dataset_id": dataset_id,
                "document_ids": [document_id],
                "top_k": 5,
                "retrieval_mode": "auto",
                "retrieval_profile": " Grounded_Strict ",
                "enable_reranker": False,
                "reranker_provider": "none",
                "reranker_top_n": 5,
                "enable_weight_rerank": True,
                "rag_config_template": {
                    "template_key": "baseline",
                    "version": "2",
                    "ab_variant": "B",
                    "patch_hash": "patch-01",
                    "ignored": "not-in-hash-contract",
                },
                "metrics": {},
            }
        )

    out_a = _run(str(uuid.uuid4()), str(uuid.uuid4()))
    out_b = _run(str(uuid.uuid4()), str(uuid.uuid4()))

    metrics = out_a.get("metrics") or {}
    assert metrics.get("retrieval_mode_requested") == "auto"
    assert metrics.get("retrieval_mode") == "vector"
    assert metrics.get("retrieval_mode_auto_routed") is True
    assert metrics.get("retrieval_profile_requested") == "grounded_strict"
    assert metrics.get("retrieval_profile") == "grounded_strict"
    assert metrics.get("retrieval_contract_mode") == "evidence_strict"

    trace = out_a.get("retrieval_trace") or {}
    retrieval_config = trace.get("retrieval_config") or {}
    assert retrieval_config.get("hash") == metrics.get("retrieval_config_hash")
    config = retrieval_config.get("config") or {}
    assert config.get("requested_retrieval_mode") == "auto"
    assert config.get("retrieval_mode") == "vector"
    assert config.get("retrieval_profile") == "grounded_strict"
    assert config.get("retrieval_contract_mode") == "evidence_strict"
    assert config.get("rag_config_template") == {
        "template_key": "baseline",
        "version": 2,
        "ab_variant": "B",
        "patch_hash": "patch-01",
    }
    assert "dataset_id" not in config
    assert "document_ids" not in config

    trace_b = out_b.get("retrieval_trace") or {}
    assert retrieval_config.get("hash") == (trace_b.get("retrieval_config") or {}).get("hash")
