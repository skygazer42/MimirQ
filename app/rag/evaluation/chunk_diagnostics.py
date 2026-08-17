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


def _empty_diagnostics(*, chunks_total: int) -> dict[str, Any]:
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
            "chunks_total": int(chunks_total),
            "chunks_used": 0,
        },
    }


def _prepare_contexts(
    retrieved_contexts: list[str],
    context_relevance: list[bool] | None,
    *,
    max_context_chars: int,
) -> tuple[list[str], list[bool] | None]:
    contexts: list[str] = []
    relevance: list[bool] | None = [] if context_relevance is not None else None
    for index, context in enumerate(retrieved_contexts or []):
        text = str(context or "").strip()
        if not text:
            continue
        if max_context_chars > 0 and len(text) > max_context_chars:
            text = text[:max_context_chars]
        contexts.append(text)
        if relevance is not None:
            relevance.append(bool(context_relevance[index]) if index < len(context_relevance or []) else False)
    return contexts, relevance


def _prepare_reference_text(value: str | None, *, max_chars: int) -> str | None:
    text = str(value or "").strip() or None
    if text and max_chars > 0 and len(text) > max_chars:
        return text[:max_chars]
    return text


def _supporting_chunk_indices(
    claim: str,
    contexts: list[str],
    relevance: list[bool] | None,
) -> tuple[int | None, int | None]:
    first_support: int | None = None
    first_relevant_support: int | None = None
    for index, context in enumerate(contexts):
        if not is_claim_supported(claim, context, verifier_mode="strict"):
            continue
        if first_support is None:
            first_support = index
        if relevance is not None and index < len(relevance) and relevance[index]:
            first_relevant_support = index
            break
    return first_support, first_relevant_support


def _claim_matches_reference(claim: str, reference_text: str) -> bool:
    try:
        return bool(is_claim_supported(claim, reference_text, verifier_mode="strict"))
    except Exception:
        return False


def _evaluate_claims(
    claims: list[str],
    contexts: list[str],
    relevance: list[bool] | None,
    reference_text: str | None,
) -> tuple[dict[str, int], set[int]]:
    counts = {
        "claims_supported": 0,
        "claims_noisy": 0,
        "claims_correct_total": 0,
        "claims_correct_uncited": 0,
    }
    used_chunks: set[int] = set()
    for claim in claims:
        claim_text = str(claim or "").strip()
        if not claim_text:
            continue
        first_support, relevant_support = _supporting_chunk_indices(claim_text, contexts, relevance)
        supported = first_support is not None
        if supported:
            counts["claims_supported"] += 1
            used_chunks.add(int(relevant_support if relevant_support is not None else first_support))
            if relevance is not None and relevant_support is None:
                counts["claims_noisy"] += 1
        if reference_text and _claim_matches_reference(claim_text, reference_text):
            counts["claims_correct_total"] += 1
            if not supported:
                counts["claims_correct_uncited"] += 1
    return counts, used_chunks


def _ratio(numerator: int, denominator: int, *, enabled: bool = True) -> float | None:
    if not enabled or denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _diagnostics_result(
    *,
    claims_total: int,
    chunks_total: int,
    used_chunks: set[int],
    counts: dict[str, int],
    has_relevance: bool,
    has_reference: bool,
) -> dict[str, Any]:
    chunks_used = len(used_chunks)
    claims_supported = counts["claims_supported"]
    claims_correct_total = counts["claims_correct_total"]
    return {
        "chunk_utilization": _ratio(chunks_used, chunks_total),
        "chunk_attribution": _ratio(claims_supported, claims_total),
        "noise_sensitivity": _ratio(counts["claims_noisy"], claims_supported, enabled=has_relevance),
        "self_knowledge_ratio": _ratio(
            counts["claims_correct_uncited"],
            claims_correct_total,
            enabled=has_reference,
        ),
        "counts": {
            "claims_total": claims_total,
            "claims_supported": claims_supported,
            "claims_noisy": counts["claims_noisy"],
            "claims_correct_total": claims_correct_total,
            "claims_correct_uncited": counts["claims_correct_uncited"],
            "chunks_total": chunks_total,
            "chunks_used": chunks_used,
        },
    }


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
        return _empty_diagnostics(chunks_total=len(retrieved_contexts or []))

    contexts, relevance = _prepare_contexts(
        retrieved_contexts,
        context_relevance,
        max_context_chars=max_context_chars,
    )

    claims = [c for c in split_into_claims(raw_answer, max_claims=max_claims) if _is_informative_claim(c)]
    if not claims:
        return _empty_diagnostics(chunks_total=len(contexts))

    reference_text = _prepare_reference_text(reference_evidence_text, max_chars=max_reference_chars)
    counts, used_chunks = _evaluate_claims(claims, contexts, relevance, reference_text)
    return _diagnostics_result(
        claims_total=len(claims),
        chunks_total=len(contexts),
        used_chunks=used_chunks,
        counts=counts,
        has_relevance=relevance is not None,
        has_reference=bool(reference_text),
    )


__all__ = ["compute_chunk_diagnostics"]
