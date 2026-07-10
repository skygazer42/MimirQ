
from typing import Any

from app.rag.core.claim_verifier import verify_claim
from app.rag.core.text import is_claim_supported, split_into_claims

_DUMMY_EVIDENCE_TOKENS = "dummy evidence tokens"


def _is_informative_claim(claim: str) -> bool:
    raw = str(claim or "").strip()
    if not raw:
        return False
    try:
        res = verify_claim(raw, _DUMMY_EVIDENCE_TOKENS, mode="token_overlap", enable_contradiction_check=False)
        rc = str((res.diagnostics or {}).get("reason_code") or "")
    except Exception:
        return True
    if rc in {"no_claim_tokens", "uncertainty_claim"}:
        return False
    return True


def compute_chunk_diagnostics(
    *,
    answer: str,
    retrieved_contexts: list[str],
    context_relevance: list[bool] | None = None,
    reference_evidence_text: str | None = None,
    max_claims: int = 24,
    max_context_chars: int = 12_000,
    max_reference_chars: int = 24_000,
) -> dict[str, Any]:
    """
    Chunk-level diagnostics (best-effort, deterministic, bounded).

    This helper is designed to produce PII-minimal numeric metrics (plus small counts)
    for regression runs and offline gates. It does NOT store raw claims or chunk text.
    """
    max_claims = max(1, int(max_claims or 0))
    max_context_chars = max(0, int(max_context_chars or 0))
    max_reference_chars = max(0, int(max_reference_chars or 0))

    raw_answer = str(answer or "").strip()
    if not raw_answer:
        return {
            "chunk_utilization": None,
            "chunk_attribution": None,
            "noise_sensitivity": None,
            "self_knowledge_ratio": None,
            "counts": {
                "claims_total": 0,
                "claims_supported": 0,
                "claims_noisy": 0,
                "claims_correct_total": 0,
                "claims_correct_uncited": 0,
                "chunks_total": int(len(retrieved_contexts or [])),
                "chunks_used": 0,
            },
        }

    # Keep only non-empty contexts and align relevance flags when possible.
    contexts: list[str] = []
    rel: list[bool] | None = [] if context_relevance is not None else None
    for i, ctx in enumerate(retrieved_contexts or []):
        t = str(ctx or "").strip()
        if not t:
            continue
        if max_context_chars > 0 and len(t) > max_context_chars:
            t = t[:max_context_chars]
        contexts.append(t)
        if rel is not None:
            rel.append(bool(context_relevance[i]) if i < len(context_relevance or []) else False)

    claims = [c for c in split_into_claims(raw_answer, max_claims=max_claims) if _is_informative_claim(c)]
    if not claims:
        return {
            "chunk_utilization": None,
            "chunk_attribution": None,
            "noise_sensitivity": None,
            "self_knowledge_ratio": None,
            "counts": {
                "claims_total": 0,
                "claims_supported": 0,
                "claims_noisy": 0,
                "claims_correct_total": 0,
                "claims_correct_uncited": 0,
                "chunks_total": int(len(contexts)),
                "chunks_used": 0,
            },
        }

    ref_text = str(reference_evidence_text or "").strip() or None
    if ref_text and max_reference_chars > 0 and len(ref_text) > max_reference_chars:
        ref_text = ref_text[:max_reference_chars]

    claims_supported = 0
    claims_noisy = 0
    claims_correct_total = 0
    claims_correct_uncited = 0

    used_chunks: set[int] = set()

    for claim in claims:
        claim_raw = str(claim or "").strip()
        if not claim_raw:
            continue

        first_support: int | None = None
        first_relevant_support: int | None = None

        for j, ctx in enumerate(contexts):
            # Use strict overlap to reduce false positives when attributing to a specific chunk.
            if not is_claim_supported(claim_raw, ctx, verifier_mode="strict"):
                continue
            if first_support is None:
                first_support = j
            if rel is not None and j < len(rel) and bool(rel[j]):
                first_relevant_support = j
                break

        supported = first_support is not None
        if supported:
            claims_supported += 1
            used_chunks.add(int(first_relevant_support if first_relevant_support is not None else first_support))
            if rel is not None and first_relevant_support is None:
                claims_noisy += 1

        if ref_text:
            try:
                correct = bool(is_claim_supported(claim_raw, ref_text, verifier_mode="strict"))
            except Exception:
                correct = False
            if correct:
                claims_correct_total += 1
                if not supported:
                    claims_correct_uncited += 1

    chunks_total = int(len(contexts))
    chunks_used = int(len(used_chunks))
    claims_total = int(len(claims))

    chunk_utilization: float | None = None
    if chunks_total > 0:
        chunk_utilization = round(float(chunks_used) / float(chunks_total), 4)

    chunk_attribution: float | None = None
    if claims_total > 0:
        chunk_attribution = round(float(claims_supported) / float(claims_total), 4)

    noise_sensitivity: float | None = None
    if rel is not None and claims_supported > 0:
        noise_sensitivity = round(float(claims_noisy) / float(claims_supported), 4)

    self_knowledge_ratio: float | None = None
    if ref_text and claims_correct_total > 0:
        self_knowledge_ratio = round(float(claims_correct_uncited) / float(claims_correct_total), 4)

    return {
        "chunk_utilization": chunk_utilization,
        "chunk_attribution": chunk_attribution,
        "noise_sensitivity": noise_sensitivity,
        "self_knowledge_ratio": self_knowledge_ratio,
        "counts": {
            "claims_total": claims_total,
            "claims_supported": int(claims_supported),
            "claims_noisy": int(claims_noisy),
            "claims_correct_total": int(claims_correct_total),
            "claims_correct_uncited": int(claims_correct_uncited),
            "chunks_total": chunks_total,
            "chunks_used": chunks_used,
        },
    }


__all__ = ["compute_chunk_diagnostics"]
