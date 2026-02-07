from __future__ import annotations


def test_build_claim_evidence_map_picks_supporting_chunks_and_spans():
    from app.rag.core.claim_evidence import build_claim_evidence_map

    answer = "Alpha is enabled. Beta is disabled."
    evidence_chunks = [
        {
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "start_char": 100,
            "text": "Alpha is enabled by default in MimirQ.",
        },
        {
            "document_id": "doc-2",
            "chunk_id": "chunk-2",
            "start_char": 500,
            "text": "Beta is disabled unless you set BETA_ENABLED=true.",
        },
    ]

    out = build_claim_evidence_map(answer, evidence_chunks=evidence_chunks, max_evidence_per_claim=1)
    assert [x["claim"] for x in out] == ["Alpha is enabled.", "Beta is disabled."]

    ev1 = out[0]["evidence"][0]
    assert ev1["chunk_id"] == "chunk-1"
    assert ev1["document_id"] == "doc-1"
    assert isinstance(ev1.get("start_char"), int)
    assert isinstance(ev1.get("end_char"), int)
    assert ev1["end_char"] > ev1["start_char"]
    assert "Alpha" in ev1.get("quote", "")

    ev2 = out[1]["evidence"][0]
    assert ev2["chunk_id"] == "chunk-2"
    assert ev2["document_id"] == "doc-2"
    assert "Beta" in ev2.get("quote", "")


def test_build_claim_evidence_map_keeps_uncertainty_claims_without_evidence():
    from app.rag.core.claim_evidence import build_claim_evidence_map

    out = build_claim_evidence_map(
        "Unable to answer this question based on the available materials.",
        evidence_chunks=[],
    )
    assert out
    assert out[0]["evidence"] == []

