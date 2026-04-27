from __future__ import annotations


def test_build_chunk_type_subindex_payload_routes_formula_chunks() -> None:
    from app.rag.chunking.roles import build_chunk_type_subindex_payload

    out = build_chunk_type_subindex_payload(
        chunk_id="chunk-f",
        content="$$ a^2 + b^2 = c^2 $$",
        meta={"content_type": "formula"},
    )

    assert out == {
        "schema": "mimirq.chunk_type_subindex.v1",
        "chunk_id": "chunk-f",
        "chunk_type": "formula",
        "subindex_key": "formula",
        "subindex_id": "chunk-f@formula",
    }


def test_build_chunk_type_subindex_payload_routes_code_chunks() -> None:
    from app.rag.chunking.roles import build_chunk_type_subindex_payload

    out = build_chunk_type_subindex_payload(
        chunk_id="chunk-c",
        content="```sql\nselect 1;\n```",
        meta={},
    )

    assert out["chunk_type"] == "code"
    assert out["subindex_key"] == "code"


def test_build_chunk_type_subindex_payload_defaults_other_chunks_to_text() -> None:
    from app.rag.chunking.roles import build_chunk_type_subindex_payload

    out = build_chunk_type_subindex_payload(
        chunk_id="chunk-t",
        content="Deployment overview and prerequisites.",
        meta={},
    )

    assert out["chunk_type"] == "text"
    assert out["subindex_key"] == "text"
