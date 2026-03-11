from __future__ import annotations

import pytest


def _mk_result(*, chunk_id: str, document_id: str, content: str, simhash64: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "content": content,
        "metadata": {"document_id": document_id, "simhash64": simhash64},
        "score": 1.0,
    }


def test_retrieval_near_dedup_drops_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    # Enable near-dedup and make it easy to trigger deterministically.
    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_MAX_COMPARE", 50, raising=False)

    r = HybridRetriever()
    r.dedup_enabled = True
    # Disable token Jaccard dedup so only simhash-based near dedup can drop.
    r.dedup_jaccard_threshold = 0.0

    # Two different chunks with simhash distance 1 => treat as near-dup.
    results = [
        _mk_result(chunk_id="c1", document_id="d1", content="Alpha content", simhash64="0000000000000000"),
        _mk_result(chunk_id="c2", document_id="d2", content="Beta content", simhash64="0000000000000001"),
    ]

    out = r._deduplicate_results(results)
    assert len(out) == 1
    assert out[0]["chunk_id"] == "c1"


def test_retrieval_near_dedup_keeps_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD", 1, raising=False)

    r = HybridRetriever()
    r.dedup_enabled = True
    r.dedup_jaccard_threshold = 0.0

    results = [
        _mk_result(chunk_id="c1", document_id="d1", content="Alpha content", simhash64="0000000000000000"),
        _mk_result(chunk_id="c2", document_id="d2", content="Beta content", simhash64="0000000000000001"),
    ]

    out = r._deduplicate_results(results)
    assert len(out) == 2


def test_retrieval_near_dedup_exposes_debug_metadata_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD", 2, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_NEAR_DEDUP_MAX_COMPARE", 10, raising=False)

    r = HybridRetriever()
    r.dedup_enabled = True
    r.dedup_jaccard_threshold = 0.0
    r._last_channel_metrics = {}

    results = [
        _mk_result(chunk_id="c1", document_id="d1", content="Alpha content", simhash64="0000000000000000"),
        _mk_result(chunk_id="c2", document_id="d2", content="Beta content", simhash64="0000000000000001"),
    ]

    _ = r._deduplicate_results(results)
    dedup = (r._last_channel_metrics or {}).get("dedup") if isinstance(r._last_channel_metrics, dict) else {}
    assert isinstance(dedup, dict)
    assert dedup.get("near_dedup_enabled") is False
    assert int(dedup.get("near_dedup_dropped") or 0) == 0
    assert int(dedup.get("near_dedup_hamming_threshold") or 0) == 2
    assert int(dedup.get("near_dedup_max_compare") or 0) == 10
