from __future__ import annotations


def test_build_bge_m3_tri_index_payload_routes_table_chunks_to_table_subindex() -> None:
    from app.rag.embedding.bge_m3_triplet import build_bge_m3_tri_index_payload

    out = build_bge_m3_tri_index_payload(
        chunk_id="chunk-1",
        text="| Quarter | Revenue |\n|---|---|\n| Q1 | 100 |\n",
        metadata={"doc_type_kwd": "table"},
        dense_fn=lambda text: [0.1, 0.2],
        sparse_fn=lambda text: {"quarter": 1.0, "revenue": 0.9},
        colbert_fn=lambda text: [[0.1, 0.2], [0.3, 0.4]],
    )

    assert out["schema"] == "mimirq.bge_m3_tri_index.v1"
    assert out["chunk_id"] == "chunk-1"
    assert out["chunk_type"] == "table"
    assert out["subindex_key"] == "table"
    assert [row["view"] for row in out["views"]] == ["dense", "sparse", "colbert"]
    assert out["views"][0]["view_id"] == "chunk-1:dense"
    assert out["views"][1]["subindex_key"] == "table"
    assert out["views"][2]["metadata"]["chunk_type"] == "table"


def test_build_bge_m3_tri_index_payload_routes_code_chunks_to_code_subindex() -> None:
    from app.rag.embedding.bge_m3_triplet import build_bge_m3_tri_index_payload

    out = build_bge_m3_tri_index_payload(
        chunk_id="chunk-2",
        text="```python\nprint('hello')\n```",
        metadata={},
        dense_fn=lambda text: [0.5],
    )

    assert out["chunk_type"] == "code"
    assert out["subindex_key"] == "code"
    assert out["views"] == [
        {
            "view": "dense",
            "view_id": "chunk-2:dense",
            "subindex_key": "code",
            "payload": [0.5],
            "metadata": {"chunk_type": "code"},
        }
    ]


def test_build_bge_m3_tri_index_payload_defaults_non_specialized_chunks_to_text_subindex() -> None:
    from app.rag.embedding.bge_m3_triplet import build_bge_m3_tri_index_payload

    out = build_bge_m3_tri_index_payload(
        chunk_id="chunk-3",
        text="System overview and deployment prerequisites.",
        metadata={},
        dense_fn=lambda text: [0.8, 0.1],
        sparse_fn=lambda text: {"system": 1.0},
    )

    assert out["chunk_type"] == "text"
    assert out["subindex_key"] == "text"
    assert [row["view"] for row in out["views"]] == ["dense", "sparse"]
