from __future__ import annotations

import uuid


class _EmptyRetriever:
    def __init__(self) -> None:
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return []


def _patch_common(monkeypatch) -> None:  # noqa: ANN001
    import langchain

    from app.core.config import settings

    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "mock", raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", True, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )


def test_out_of_scope_live_guard_upgrades_orchestrator_abstain_reason(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retrieval.orchestrator as orch_mod

    _patch_common(monkeypatch)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)
    monkeypatch.setattr(orch_mod, "build_citations_from_docs", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(
        orch_mod,
        "run_default_out_of_scope_live_guard",
        lambda **_kwargs: {
            "schema": "mimirq.out_of_scope_live_guard.v1",
            "verdict": "out_of_scope",
            "l1_keyword_hit": False,
            "l2_top1_sim": 0.12,
            "l3_hyde_hit": False,
        },
        raising=True,
    )

    out = orch_mod.run_retrieval(
        {
            "question": "新型号 X200 怎么接线",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": str(uuid.uuid4()),
            "document_ids": None,
            "top_k": 5,
            "retrieval_mode": "hybrid",
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    assert metrics.get("abstain_triggered") is True
    assert metrics.get("abstain_reason") == "out_of_scope"
    assert (metrics.get("out_of_scope_guard") or {}).get("verdict") == "out_of_scope"
