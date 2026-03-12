from __future__ import annotations


def test_verify_claim_exposes_reason_code_and_contradiction_type_for_numeric_mismatch() -> None:
    from app.rag.core.claim_verifier import verify_claim

    res = verify_claim(
        "Revenue exceeded 100 in 2025.",
        "Revenue was 90 in 2025.",
        mode="semantic_heuristic",
        enable_contradiction_check=True,
    )
    diag = res.diagnostics

    assert res.supported is False
    assert str(diag.get("reason_code") or "") == "contradiction_numeric_mismatch"
    assert str(diag.get("contradiction_type") or "") == "numeric_mismatch"


def test_verify_claim_exposes_reason_code_and_contradiction_type_for_temporal_negation() -> None:
    from app.rag.core.claim_verifier import verify_claim

    res = verify_claim(
        "The policy was not active in 2020.",
        "The policy was active in 2020.",
        mode="semantic_heuristic",
        enable_contradiction_check=True,
    )
    diag = res.diagnostics

    assert res.supported is False
    assert str(diag.get("reason_code") or "") == "contradiction_negation_conflict"
    assert str(diag.get("contradiction_type") or "") == "negation_conflict"


def test_verify_claim_supported_reason_code() -> None:
    from app.rag.core.claim_verifier import verify_claim

    res = verify_claim("Sky is blue.", "The sky is blue due to Rayleigh scattering.")
    diag = res.diagnostics

    assert res.supported is True
    assert str(diag.get("reason_code") or "") == "supported"
    assert diag.get("contradiction_type") is None
