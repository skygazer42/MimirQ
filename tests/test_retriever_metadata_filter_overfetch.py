from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun


def test_retriever_accepts_dataset_metadata_filter_as_explicit_scope(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False, raising=False)

    dataset_ids = [str(uuid4()), str(uuid4())]
    captured: dict[str, object] = {}

    def _fake_hybrid_search(self, *, metadata_filter=None, **_kw):  # noqa: ANN001
        captured["metadata_filter"] = metadata_filter
        return []

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    r = HybridRetriever(
        k=5,
        tenant_id=uuid4(),
        account_id="acct",
        dataset_id=None,
        document_ids=None,
        metadata_filter={"dataset_id": {"$in": dataset_ids}},
    )

    _ = r._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert captured["metadata_filter"] == {"dataset_id": {"$in": dataset_ids}}


def test_retriever_rejects_non_scope_metadata_filter_when_open_scope_disabled(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False, raising=False)

    r = HybridRetriever(
        k=5,
        tenant_id=uuid4(),
        account_id="acct",
        dataset_id=None,
        document_ids=None,
        metadata_filter={"source": "x"},
    )

    with pytest.raises(ValueError, match="dataset_id is required"):
        r._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())


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


def test_hierarchy_recall_profile_overfetches_before_family_collapse(monkeypatch) -> None:  # noqa: ANN001
    from app.rag.retriever import HybridRetriever

    captured: dict[str, object] = {}

    def _fake_hybrid_search(self, *, query: str, top_k: int, **_kw):  # noqa: ANN001
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    r = HybridRetriever(
        k=5,
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        retrieval_profile="hierarchy_recall20",
        enable_hierarchy_recall=True,
        hierarchy_family_collapse=True,
        hierarchy_overfetch_factor=4,
    )
    _ = r._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert captured.get("top_k") == 20


def test_hierarchy_recall_profile_collapses_duplicate_family_hits(monkeypatch) -> None:  # noqa: ANN001
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, results, stats=None: list(results), raising=True)  # noqa: E501
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, results: list(results), raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, results: list(results), raising=True)
    monkeypatch.setattr(HybridRetriever, "_apply_governance_policy", lambda self, results, stats=None: list(results), raising=True)

    doc_id = str(uuid4())

    def _fake_hybrid_search(self, *, query: str, top_k: int, **_kw):  # noqa: ANN001
        assert top_k == 4
        return [
            {
                "chunk_id": "c1",
                "content": "family one / hit one",
                "score": 0.90,
                "metadata": {"document_id": doc_id, "chunk_index": 1, "hierarchy_family_key": "fam-1"},
            },
            {
                "chunk_id": "c2",
                "content": "family one / hit two",
                "score": 0.85,
                "metadata": {"document_id": doc_id, "chunk_index": 2, "hierarchy_family_key": "fam-1"},
            },
            {
                "chunk_id": "c3",
                "content": "family two / hit one",
                "score": 0.80,
                "metadata": {"document_id": doc_id, "chunk_index": 3, "hierarchy_family_key": "fam-2"},
            },
            {
                "chunk_id": "c4",
                "content": "family three / hit one",
                "score": 0.75,
                "metadata": {"document_id": doc_id, "chunk_index": 4, "hierarchy_family_key": "fam-3"},
            },
        ]

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    r = HybridRetriever(
        k=2,
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        retrieval_profile="hierarchy_recall20",
        enable_hierarchy_recall=True,
        hierarchy_family_collapse=True,
        hierarchy_overfetch_factor=2,
    )
    docs = r._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert len(docs) == 2
    assert [doc.id for doc in docs] == ["c1", "c3"]
