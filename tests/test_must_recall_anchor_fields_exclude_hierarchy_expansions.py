from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _StaticRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs or [])
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_must_recall_anchor_field_validation_ignores_hierarchy_context_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When hierarchy recall adds parent/sibling context chunks, those context citations
    should not cause must-recall anchor-field validation to fail.

    Example: TAG citations include row_source_* keys, but hierarchy siblings do not.
    We exclude retrieval_role prefixes like "hierarchy_" from anchor-field validation.
    """
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)

    tenant_id = uuid.uuid4()
    tag_doc_id = uuid.uuid4()
    tag_chunk_id = uuid.uuid4()

    # Evidence anchor: TAG result (has row_source_* keys).
    tag_doc = Document(
        page_content='{"kind":"tag_table_store","rows":[["ok"]]}',
        id=str(tag_chunk_id),
        metadata={
            "retrieval_role": "tag",
            "chunk_role": "tag_sql_result",
            "chunk_id": str(tag_chunk_id),
            "document_id": str(tag_doc_id),
            "source": "sales.xlsx",
            "table_id": f"doc:{tag_doc_id}:sheet:0",
            "row_source_table": "demo.sales",
            "row_source_sync_token": "tok-sales-v1",
            "row_source_pk_hashes": ["pkhash-1"],
            "score": 0.9,
            "retrieval_score": 0.9,
        },
    )

    # Context-only expansion chunk: lacks TAG-specific keys like row_source_table.
    sib_chunk_id = uuid.uuid4()
    sibling = Document(
        page_content="some context that should not be treated as TAG evidence",
        id=str(sib_chunk_id),
        metadata={
            "retrieval_role": "hierarchy_sibling",
            "neighbor_of": str(tag_chunk_id),
            "chunk_id": str(sib_chunk_id),
            "document_id": str(tag_doc_id),
            "source": "sales.xlsx",
            "start_char": 0,
            "end_char": 10,
            "score": 0.2,
            "retrieval_score": 0.2,
        },
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _StaticRetriever(docs=[tag_doc, sibling]), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(tenant_id),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "hybrid",
            "retrieval_contract_mode": "must_recall_strict",
            "must_recall": True,
            "must_recall_expected_source_keys": [],
            "must_recall_required_anchor_fields": [
                "chunk_id",
                "document_id",
                "row_source_table",
                "row_source_sync_token",
                "row_source_pk_hashes",
            ],
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    assert bool(metrics.get("must_recall_enabled")) is True
    assert bool(metrics.get("must_recall_passed")) is True
    assert str(metrics.get("must_recall_status") or "") == "passed"

    # Ensure we actually had hierarchy_* citations present, and that they were skipped
    # in anchor validation (otherwise this test is meaningless).
    assert int(metrics.get("must_recall_anchor_skipped_citations") or 0) >= 1
    skipped_by_role = metrics.get("must_recall_anchor_skipped_by_role") or {}
    assert isinstance(skipped_by_role, dict)
    assert int(skipped_by_role.get("hierarchy_sibling") or 0) >= 1

