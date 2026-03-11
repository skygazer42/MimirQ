from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.core.config import settings
from app.rag.retriever import HybridRetriever


class _StubVectorStore:
    def __init__(self, *, results):  # noqa: ANN001
        self._results = list(results)

    def search(self, **_kwargs):  # noqa: ANN003
        return list(self._results)


def _vector_hit(
    *,
    document_id: str,
    chunk_id: str,
    chunk_index: int,
    score: float,
    dataset_id: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "embedding_space_hash": "",
    }
    if dataset_id:
        metadata["dataset_id"] = dataset_id

    return {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "content": f"hit:{document_id}",
        "score": score,
        "metadata": metadata,
    }


def test_field_aware_recall_boost_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RETRIEVAL_FIELD_AWARE_RECALL_ENABLED", False, raising=False)

    retriever = HybridRetriever()
    vector_results = [
        _vector_hit(document_id="doc-low", chunk_id="cid-low", chunk_index=0, score=0.50),
        _vector_hit(document_id="doc-title", chunk_id="cid-title:title", chunk_index=0, score=0.78),
        _vector_hit(document_id="doc-body", chunk_id="cid-body", chunk_index=0, score=0.80),
    ]

    merged = retriever._merge_results(vector_results, bm25_results=[], lexical_results=[], sparse_results=[])

    assert merged
    assert merged[0].get("document_id") == "doc-body"
    assert float(merged[0].get("field_aware_boost") or 0.0) == 0.0


def test_field_aware_recall_boost_is_applied_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RETRIEVAL_FIELD_AWARE_RECALL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_FIELD_AWARE_TITLE_BOOST", 0.08, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_FIELD_AWARE_HEADING_BOOST", 0.05, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_FIELD_AWARE_MAX_BOOST", 0.10, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)

    retriever = HybridRetriever(retrieval_mode="vector", k=3)
    retriever.tenant_id = uuid4()
    retriever.dataset_id = uuid4()
    dsid = str(retriever.dataset_id)

    vector_results = [
        _vector_hit(document_id="doc-low", chunk_id="cid-low", chunk_index=0, score=0.50, dataset_id=dsid),
        _vector_hit(document_id="doc-title", chunk_id="cid-title:title", chunk_index=0, score=0.78, dataset_id=dsid),
        _vector_hit(document_id="doc-body", chunk_id="cid-body", chunk_index=0, score=0.80, dataset_id=dsid),
    ]
    stub_store = _StubVectorStore(results=vector_results)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    # Keep this unit test focused on ranking/trace behavior.
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    docs = retriever._get_relevant_documents(
        "where is title hint",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert docs
    assert docs[0].metadata.get("document_id") == "doc-title"
    assert float(docs[0].metadata.get("field_aware_boost") or 0.0) > 0.0
    assert docs[0].metadata.get("field_aware_signal") == "title"

    channels = (retriever._last_debug_metrics or {}).get("channels") or {}
    field_aware = channels.get("field_aware") or {}
    assert field_aware.get("enabled") is True
    assert int(field_aware.get("boosted_candidates") or 0) >= 1
    assert int((field_aware.get("signals") or {}).get("title") or 0) >= 1
