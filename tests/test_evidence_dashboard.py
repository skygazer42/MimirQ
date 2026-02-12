from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest


def test_compute_suite_throughput_counts_and_lead_times() -> None:
    from app.services.evidence_dashboard import compute_suite_throughput

    now = datetime(2026, 2, 12, 12, 0, 0, tzinfo=timezone.utc)
    items = [
        {
            "created_at": now - timedelta(days=1),
            "reviewed_at": now - timedelta(hours=12),
            "approved_at": now - timedelta(hours=1),
        },
        {
            # Outside the 7d window, should not count for throughput window.
            "created_at": now - timedelta(days=10),
            "reviewed_at": None,
            "approved_at": None,
        },
        {
            "created_at": now - timedelta(days=2),
            "reviewed_at": now - timedelta(days=1),
            "approved_at": None,
        },
    ]

    out = compute_suite_throughput(items, now=now, window_days=7)

    assert out["window_days"] == 7
    assert out["last_window"]["created"] == 2
    assert out["last_window"]["reviewed"] == 2
    assert out["last_window"]["approved"] == 1

    assert out["draft_to_reviewed"]["count"] == 2
    assert out["draft_to_reviewed"]["p50_sec"] == 12 * 3600
    assert out["draft_to_reviewed"]["p90_sec"] == 24 * 3600
    assert out["draft_to_reviewed"]["mean_sec"] == pytest.approx((12 * 3600 + 24 * 3600) / 2, abs=1e-6)

    assert out["reviewed_to_approved"]["count"] == 1
    assert out["reviewed_to_approved"]["p50_sec"] == 11 * 3600
    assert out["reviewed_to_approved"]["p90_sec"] == 11 * 3600
    assert out["reviewed_to_approved"]["mean_sec"] == pytest.approx(11 * 3600, abs=1e-6)

    assert out["draft_to_approved"]["count"] == 1
    assert out["draft_to_approved"]["p50_sec"] == 23 * 3600
    assert out["draft_to_approved"]["p90_sec"] == 23 * 3600
    assert out["draft_to_approved"]["mean_sec"] == pytest.approx(23 * 3600, abs=1e-6)


def test_compute_suite_coverage_slices_and_heatmap() -> None:
    from app.services.evidence_dashboard import compute_suite_coverage

    doc1 = uuid4()
    doc2 = uuid4()

    items = [
        {
            "id": uuid4(),
            "reference_sources": [
                {"document_id": str(doc1), "chunk_id": "c1"},
                {"document_id": str(doc2), "chunk_id": "c2"},
            ],
            "retrieval_snapshot": {
                "citations": [
                    {"chunk_id": "c1", "hit_type": "keyword"},
                    {"chunk_id": "c2", "hit_type": "vector"},
                ]
            },
        },
        {
            "id": uuid4(),
            "reference_sources": [
                {"document_id": str(doc1), "chunk_id": "c3"},
            ],
            "retrieval_snapshot": {
                "citations": [
                    {"chunk_id": "c3", "hit_type": "hybrid"},
                ]
            },
        },
    ]

    documents: dict[UUID, dict[str, object]] = {
        doc1: {
            "id": doc1,
            "file_type": "pdf",
            "metadata": {"language": "en", "governance_quality": {"density": 0.2}},
        },
        doc2: {
            "id": doc2,
            "file_type": "html",
            "metadata": {"language": "zh", "governance_quality": {"density": 0.05}},
        },
    }

    out = compute_suite_coverage(items, documents=documents, top_n=12, heatmap_top_n=8)

    assert out["language"] == [
        {"key": "en", "items": 2, "references": 2},
        {"key": "zh", "items": 1, "references": 1},
    ]
    assert out["file_type"] == [
        {"key": "pdf", "items": 2, "references": 2},
        {"key": "html", "items": 1, "references": 1},
    ]
    assert out["quality_bucket"] == [
        {"key": "high_density", "items": 2, "references": 2},
        {"key": "low_density", "items": 1, "references": 1},
    ]
    assert out["channel"] == [
        {"key": "hybrid", "items": 1, "references": 1},
        {"key": "keyword", "items": 1, "references": 1},
        {"key": "vector", "items": 1, "references": 1},
    ]

    hm = out["heatmaps"]["language_x_file_type"]
    assert hm["x"] == ["pdf", "html"]
    assert hm["y"] == ["en", "zh"]
    assert hm["z"] == [[2, 0], [0, 1]]
    assert hm["metric"] == "items"

