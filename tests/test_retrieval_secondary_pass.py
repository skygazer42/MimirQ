
import uuid

import pytest
from langchain_core.documents import Document


class _ModeRetriever:
    def __init__(self, *, docs_by_mode: dict[str, list[Document]], mode: str = "vector") -> None:
        self._docs_by_mode = {str(k): list(v or []) for k, v in (docs_by_mode or {}).items()}
        self._mode = str(mode or "vector")
        self._last_debug_metrics: dict = {
            "query_normalization": {"normalized": "q"},
        }

    def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
        update = kwargs.get("update")
        update = update if isinstance(update, dict) else {}
        mode = str(update.get("retrieval_mode") or self._mode or "vector")
        return _ModeRetriever(docs_by_mode=self._docs_by_mode, mode=mode)

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs_by_mode.get(self._mode, []))


def _mk_tag_doc(*, table_id: str) -> Document:
    chunk_id = uuid.uuid4()
    document_id = uuid.uuid4()
    return Document(
        page_content='{"kind":"tag_table_store","rows":[["ok"]]}',
        id=str(chunk_id),
        metadata={
            "retrieval_role": "tag",
            "chunk_role": "tag_sql_result",
            "chunk_id": str(chunk_id),
            "document_id": str(document_id),
            "source": "table",
            "table_id": table_id,
            "score": 0.9,
            "retrieval_score": 0.9,
        },
    )


def test_orchestrator_secondary_pass_recovers_partial_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE", "keyword", raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K", 20, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)

    # Main retrieval misses required source key; keyword second pass hits it.
    retriever = _ModeRetriever(
        docs_by_mode={
            "vector": [_mk_tag_doc(table_id="sales")],
            "keyword": [_mk_tag_doc(table_id="inventory")],
        },
        mode="vector",
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

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
            "retrieval_contract_mode": "must_recall_strict",
            "must_recall": True,
            "must_recall_expected_source_keys": ["inventory"],
            "must_recall_required_anchor_fields": ["chunk_id", "document_id"],
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    assert str(metrics.get("must_recall_status") or "") == "partial_miss_recovered"
    assert bool(metrics.get("must_recall_second_pass_attempted")) is True
    assert bool(metrics.get("must_recall_second_pass_used")) is True
    diff = metrics.get("must_recall_second_pass_diff") or {}
    assert isinstance(diff, dict)
    assert list(diff.get("before_missing_source_keys") or []) == ["inventory"]
    assert list(diff.get("after_missing_source_keys") or []) == []

    trace = out.get("retrieval_trace") or {}
    contract_diag = trace.get("contract_diagnostics") if isinstance(trace, dict) else {}
    contract_diag = contract_diag if isinstance(contract_diag, dict) else {}
    must_recall = contract_diag.get("must_recall") if isinstance(contract_diag, dict) else {}
    must_recall = must_recall if isinstance(must_recall, dict) else {}
    second_pass = must_recall.get("second_pass") if isinstance(must_recall, dict) else {}
    second_pass = second_pass if isinstance(second_pass, dict) else {}
    assert bool(second_pass.get("attempted")) is True
    assert bool(second_pass.get("used")) is True
    assert isinstance(second_pass.get("diff"), dict)


def test_orchestrator_contextual_followup_adds_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", "keyword", raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K", 20, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS", 3, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS", 3, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS", 2, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS", 2000, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)

    retriever = _ModeRetriever(
        docs_by_mode={
            "vector": [_mk_tag_doc(table_id="sales")],
            "keyword": [_mk_tag_doc(table_id="inventory")],
        },
        mode="vector",
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

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

    metrics = out.get("metrics") or {}
    assert bool(metrics.get("contextual_followup_attempted")) is True
    assert bool(metrics.get("contextual_followup_used")) is True
    assert str(metrics.get("contextual_followup_mode") or "") == "keyword"
    assert int(metrics.get("contextual_followup_added_docs") or 0) >= 1
    assert int(metrics.get("contextual_followup_added_citations") or 0) >= 1
    assert int(metrics.get("iterative_pass_hops_attempted") or 0) >= 1
    assert isinstance(metrics.get("iterative_pass_hops"), list)

    citations = out.get("citations") or []
    assert len([c for c in citations if isinstance(c, dict)]) >= 2

    trace = out.get("retrieval_trace") or {}
    follow = trace.get("contextual_followup") if isinstance(trace, dict) else {}
    follow = follow if isinstance(follow, dict) else {}
    assert bool(follow.get("attempted")) is True
    assert bool(follow.get("used")) is True
    iterative = trace.get("iterative_pass") if isinstance(trace, dict) else {}
    iterative = iterative if isinstance(iterative, dict) else {}
    assert int(iterative.get("hops_attempted") or 0) >= 1
