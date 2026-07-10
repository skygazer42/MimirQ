
from typing import Any

from app.rag.core.text import split_into_claims, verify_claim_with_fallback


def compute_faithfulness_score(
    *,
    answer: str,
    evidence_text: str,
    max_claims: int = 24,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
) -> dict[str, Any]:
    """
    Deterministic online faithfulness proxy.

    Score definition:
    - Split answer into bounded atomic claims.
    - Check each claim against evidence_text using current verifier policy.
    - faithfulness_score = supported_claims / total_claims (0..1), or None when no claims.
    """
    max_claims = max(1, int(max_claims or 0))
    raw_answer = str(answer or "").strip()
    if not raw_answer:
        return {
            "score": None,
            "supported_claims": 0,
            "total_claims": 0,
            "unsupported_claims": [],
            "method": "claim_support_ratio",
        }

    claims = split_into_claims(raw_answer, max_claims=max_claims)
    if not claims:
        return {
            "score": None,
            "supported_claims": 0,
            "total_claims": 0,
            "unsupported_claims": [],
            "method": "claim_support_ratio",
        }

    evidence = str(evidence_text or "")
    supported = 0
    total = 0
    unsupported_claims: list[str] = []
    for claim in claims:
        c = str(claim or "").strip()
        if not c:
            continue
        total += 1
        vr = verify_claim_with_fallback(
            c,
            evidence,
            verifier_mode=verifier_mode,
            verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
            use_nli_fallback=bool(use_nli_fallback),
            nli_provider=nli_provider,
            nli_model_name=nli_model_name,
            nli_timeout_sec=nli_timeout_sec,
        )
        if bool(vr.supported):
            supported += 1
            continue
        if len(unsupported_claims) < 16:
            unsupported_claims.append(c[:300])

    score = round(float(supported) / float(total), 4) if total > 0 else None
    return {
        "score": score,
        "supported_claims": int(supported),
        "total_claims": int(total),
        "unsupported_claims": unsupported_claims,
        "method": "claim_support_ratio",
    }

