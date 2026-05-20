from pathlib import Path
from uuid import UUID


def test_dataset_scope_retriever_does_not_raise_overfetch_name_error(monkeypatch) -> None:
    from app.rag.retriever import HybridRetriever

    retriever = HybridRetriever(
        k=6,
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        account_id="production-readiness",
        dataset_id=UUID("11111111-1111-1111-1111-111111111111"),
        retrieval_mode="hybrid",
        enable_reranker=False,
    )

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", lambda self, **_: [])

    assert retriever._get_relevant_documents("What does WCAG say?", run_manager=None) == []  # type: ignore[arg-type]
    debug = retriever._last_debug_metrics
    assert debug["requested_k"] == 6
    assert debug["search_k"] == 6
    assert debug["overfetch_enabled"] is False
    assert debug["overfetch_reasons"] == []


def test_dataset_scope_does_not_trigger_open_scope_overfetch() -> None:
    src = Path("app/rag/retriever.py").read_text(encoding="utf-8")

    assert "metadata_filter_requested = bool" in src
    assert "if self.dataset_id is None and self.tenant_id" in src
    assert 'overfetch_reasons.append("open_scope_acl")' in src
    assert 'overfetch_reasons.append("metadata_filter")' in src
    assert '"overfetch_reasons": overfetch_reasons' in src
