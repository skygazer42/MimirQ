import pytest

from app.rag.evaluation.kg_search_diagnostics_metrics import compute_kg_hit_metrics


def test_metrics_rank1_hit() -> None:
    evidence = {"c1", "c2"}
    events = [
        {"id": "e1", "chunk_id": "c1"},
        {"id": "e2", "chunk_id": "x"},
    ]

    m = compute_kg_hit_metrics(events=events, evidence_chunk_ids=evidence, k=10)
    assert m["hit_at_k"] is True
    assert m["mrr"] == pytest.approx(1.0)
    assert m["recall"] == pytest.approx(0.5)
    assert m["matched_evidence_chunks"] == 1
    assert m["total_evidence_chunks"] == 2


def test_metrics_hit_after_k_is_not_counted() -> None:
    evidence = {"c2"}
    events = [
        {"id": "e1", "chunk_id": "x"},
        {"id": "e2", "chunk_id": "c2"},
    ]

    m = compute_kg_hit_metrics(events=events, evidence_chunk_ids=evidence, k=1)
    assert m["hit_at_k"] is False
    assert m["mrr"] == pytest.approx(0.0)
    assert m["recall"] == pytest.approx(0.0)

    m2 = compute_kg_hit_metrics(events=events, evidence_chunk_ids=evidence, k=2)
    assert m2["hit_at_k"] is True
    assert m2["mrr"] == pytest.approx(0.5)
    assert m2["recall"] == pytest.approx(1.0)


def test_metrics_multiple_evidence_chunks_covered() -> None:
    evidence = {"c1", "c2"}
    events = [
        {"id": "e0", "chunk_id": "x"},
        {"id": "e1", "chunk_id": "c2"},
        {"id": "e2", "chunk_id": "c1"},
    ]

    m = compute_kg_hit_metrics(events=events, evidence_chunk_ids=evidence, k=3)
    assert m["hit_at_k"] is True
    assert m["mrr"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(1.0)


def test_metrics_report_ndcg_and_map_at_k() -> None:
    evidence = {"c1", "c2", "c3"}
    events = [
        {"id": "e0", "chunk_id": "x"},
        {"id": "e1", "chunk_id": "c2"},
        {"id": "e2", "chunk_id": "c1"},
        {"id": "e3", "chunk_id": "c3"},
    ]

    m = compute_kg_hit_metrics(events=events, evidence_chunk_ids=evidence, k=3)

    assert m["ndcg"] == pytest.approx(0.5307)
    assert m["map"] == pytest.approx(0.3889)


def test_metrics_empty_results() -> None:
    evidence = {"c1"}
    m = compute_kg_hit_metrics(events=[], evidence_chunk_ids=evidence, k=10)
    assert m["hit_at_k"] is False
    assert m["mrr"] == pytest.approx(0.0)
    assert m["recall"] == pytest.approx(0.0)


def test_metrics_empty_evidence_is_safe() -> None:
    m = compute_kg_hit_metrics(events=[{"id": "e1", "chunk_id": "c1"}], evidence_chunk_ids=set(), k=10)
    assert m["hit_at_k"] is False
    assert m["mrr"] == pytest.approx(0.0)
    assert m["recall"] == pytest.approx(0.0)
    assert m["matched_evidence_chunks"] == 0
    assert m["total_evidence_chunks"] == 0
