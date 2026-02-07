from __future__ import annotations

from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForRetrieverRun


def test_retriever_overfetches_when_metadata_filter_present_without_account_id(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    # Ensure deterministic numbers for the test.
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 4, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 50, raising=False)

    captured: dict[str, object] = {}

    def _fake_hybrid_search(self, *, query: str, top_k: int, **_kw):  # noqa: ANN001
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    r = HybridRetriever(
        k=5,
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        account_id=None,
        document_ids=None,
        metadata_filter={"source": "x"},
    )
    _ = r._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert captured.get("top_k") == 20


def test_retriever_does_not_overfetch_when_document_ids_provided(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 4, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 50, raising=False)

    captured: dict[str, object] = {}

    def _fake_hybrid_search(self, *, query: str, top_k: int, **_kw):  # noqa: ANN001
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    r = HybridRetriever(
        k=5,
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        account_id=None,
        document_ids=[uuid4()],
        metadata_filter={"source": "x"},
    )
    _ = r._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert captured.get("top_k") == 5

