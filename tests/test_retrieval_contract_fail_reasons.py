
import uuid

import pytest
from langchain_core.documents import Document

from app.rag.policy.must_recall import MUST_RECALL_FAIL_REASON_TAXONOMY_V1


class _ModeRetriever:
    def __init__(self, *, docs_by_mode: dict[str, list[Document]], mode: str = "vector") -> None:
        self._docs_by_mode = {str(k): list(v or []) for k, v in (docs_by_mode or {}).items()}
        self._mode = str(mode or "vector")
        self._last_debug_metrics: dict = {}

    def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
        update = kwargs.get("update")
        update = update if isinstance(update, dict) else {}
        mode = str(update.get("retrieval_mode") or self._mode or "vector")
        return _ModeRetriever(docs_by_mode=self._docs_by_mode, mode=mode)

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs_by_mode.get(self._mode, []))


def _mk_doc(*, table_id: str) -> Document:
    chunk_id = uuid.uuid4()
    document_id = uuid.uuid4()
    return Document(
        page_content="hit",
        id=str(chunk_id),
        metadata={
            "retrieval_role": "tag",
            "chunk_role": "tag_sql_result",
            "table_id": table_id,
            "chunk_id": str(chunk_id),
            "document_id": str(document_id),
            "source": "table",
            "score": 0.8,
            "retrieval_score": 0.8,
        },
    )


def test_must_recall_failed_includes_fail_taxonomy_and_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
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

    # Main and second pass both miss required source key -> must_recall failed.
    retriever = _ModeRetriever(
        docs_by_mode={
            "vector": [_mk_doc(table_id="sales")],
            "keyword": [_mk_doc(table_id="orders")],
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
    assert str(metrics.get("must_recall_status") or "") == "failed"
    assert bool(metrics.get("must_recall_passed")) is False
    assert str(metrics.get("contract_fail_reason_taxonomy") or "") == MUST_RECALL_FAIL_REASON_TAXONOMY_V1
    reasons = list(metrics.get("must_recall_fail_reasons") or [])
    assert "missing_required_source_keys" in reasons
    assert "secondary_pass_no_effect" in reasons

    trace = out.get("retrieval_trace") or {}
    contract_diag = trace.get("contract_diagnostics") if isinstance(trace, dict) else {}
    contract_diag = contract_diag if isinstance(contract_diag, dict) else {}
    assert str(contract_diag.get("contract_fail_reason_taxonomy") or "") == MUST_RECALL_FAIL_REASON_TAXONOMY_V1


def test_must_recall_auto_source_keys_are_inferred_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_INFER_FROM_METADATA_FILTER", True, raising=False)

    retriever = _ModeRetriever(
        docs_by_mode={
            "vector": [_mk_doc(table_id="inventory")],
        },
        mode="vector",
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "请给我 inventory 的统计结果",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "metadata_filter": {"table_id": "inventory"},
            "top_k": 5,
            "retrieval_mode": "vector",
            "retrieval_contract_mode": "must_recall_strict",
            "must_recall": True,
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    assert bool(metrics.get("must_recall_auto_expected_source_keys_applied")) is True
    assert "inventory" in list(metrics.get("must_recall_expected_source_keys") or [])
