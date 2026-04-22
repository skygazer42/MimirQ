from __future__ import annotations

from app.rag.retrieval.neighbor_expand import expand_neighbors_by_score


def test_expand_neighbors_by_score_uses_score_threshold_bands() -> None:
    expanded = expand_neighbors_by_score(
        ranked_items=[
            {"id": "c10", "score": 0.85},
            {"id": "c20", "score": 0.45},
            {"id": "c30", "score": 0.2},
        ],
        get_adjacent_ids=lambda chunk_id, span: [f"{chunk_id}-L{span}", f"{chunk_id}-R{span}"],
        high_threshold=0.7,
        mid_threshold=0.4,
        high_span=3,
        mid_span=1,
    )

    assert expanded["expanded_ids"] == {
        "c10",
        "c20",
        "c30",
        "c10-L3",
        "c10-R3",
        "c20-L1",
        "c20-R1",
    }
    assert expanded["expansion_map"]["c10"] == 3
    assert expanded["expansion_map"]["c20"] == 1
    assert "c30" not in expanded["expansion_map"]
