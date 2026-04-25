from __future__ import annotations


def test_build_bge_m3_triplet_payload_combines_dense_sparse_and_colbert_views() -> None:
    from app.rag.embedding.bge_m3_triplet import build_bge_m3_triplet_payload

    out = build_bge_m3_triplet_payload(
        text="MQTT broker keepalive configuration",
        dense_fn=lambda text: [0.1, 0.2, 0.3],
        sparse_fn=lambda text: {"mqtt": 1.0, "broker": 0.8},
        colbert_fn=lambda text: [[0.1, 0.2], [0.3, 0.4]],
    )

    assert out["schema"] == "mimirq.bge_m3_triplet.v1"
    assert out["dense"] == [0.1, 0.2, 0.3]
    assert out["sparse"] == {"mqtt": 1.0, "broker": 0.8}
    assert out["colbert"] == [[0.1, 0.2], [0.3, 0.4]]


def test_build_bge_m3_triplet_payload_handles_missing_views() -> None:
    from app.rag.embedding.bge_m3_triplet import build_bge_m3_triplet_payload

    out = build_bge_m3_triplet_payload(
        text="hello",
        dense_fn=lambda text: [0.5],
    )

    assert out["dense"] == [0.5]
    assert out["sparse"] == {}
    assert out["colbert"] == []
