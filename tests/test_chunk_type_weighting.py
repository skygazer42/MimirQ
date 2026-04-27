from __future__ import annotations

import pytest

from app.rag.retriever import HybridRetriever


def _hit(*, chunk_id: str, score: float, chunk_type: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "document_id": chunk_id,
        "content": f"hit:{chunk_id}",
        "score": score,
        "metadata": {
            "document_id": chunk_id,
            "chunk_id": chunk_id,
            "chunk_index": 0,
            "chunk_type": chunk_type,
        },
    }


def test_chunk_type_weighting_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "RETRIEVAL_CHUNK_TYPE_WEIGHTING_ENABLED", False, raising=False)

    retriever = HybridRetriever()
    merged = retriever._merge_results(
        vector_results=[
            _hit(chunk_id="doc-low", score=0.50, chunk_type="text"),
            _hit(chunk_id="doc-text", score=0.80, chunk_type="text"),
            _hit(chunk_id="doc-table", score=0.78, chunk_type="table"),
        ],
        bm25_results=[],
        lexical_results=[],
        sparse_results=[],
        query="哪个表格字段保存波特率？",
    )

    assert merged[0].get("document_id") == "doc-text"
    assert float(merged[0].get("chunk_type_boost") or 0.0) == pytest.approx(0.0)


def test_chunk_type_weighting_boosts_matching_table_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "RETRIEVAL_CHUNK_TYPE_WEIGHTING_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CHUNK_TYPE_MATCH_BOOST", 0.08, raising=False)

    retriever = HybridRetriever()
    merged = retriever._merge_results(
        vector_results=[
            _hit(chunk_id="doc-low", score=0.50, chunk_type="text"),
            _hit(chunk_id="doc-text", score=0.80, chunk_type="text"),
            _hit(chunk_id="doc-table", score=0.78, chunk_type="table"),
        ],
        bm25_results=[],
        lexical_results=[],
        sparse_results=[],
        query="哪个表格字段保存波特率？",
    )

    assert merged[0].get("document_id") == "doc-table"
    assert merged[0].get("chunk_type_signal") == "table"
    assert float(merged[0].get("chunk_type_boost") or 0.0) > 0.0
