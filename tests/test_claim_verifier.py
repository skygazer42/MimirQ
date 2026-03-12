from __future__ import annotations


def test_verify_claim_detects_numeric_mismatch() -> None:
    from app.rag.core.claim_verifier import verify_claim

    result = verify_claim(
        "The order contains 42 items.",
        "The order contains 24 items.",
        mode="semantic_heuristic",
    )
    assert result.supported is False
    assert result.diagnostics.get("numeric_mismatch") is True


def test_verify_claim_detects_negation_contradiction() -> None:
    from app.rag.core.claim_verifier import verify_claim

    result = verify_claim(
        "Bananas are red.",
        "Bananas are not red in this dataset.",
        mode="semantic_heuristic",
    )
    assert result.supported is False
    assert result.diagnostics.get("negation_conflict") is True


def test_build_claim_evidence_map_respects_semantic_verifier_mode() -> None:
    from app.rag.core.claim_evidence import build_claim_evidence_map

    out = build_claim_evidence_map(
        "Bananas are red.",
        evidence_chunks=[
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "text": "Bananas are not red in this dataset.",
            }
        ],
        verifier_mode="semantic_heuristic",
    )
    assert out
    assert out[0]["claim"] == "Bananas are red."
    assert out[0]["evidence"] == []

