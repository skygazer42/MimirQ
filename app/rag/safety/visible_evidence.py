"""Scrub unsupported claims from structured answers within the configured traversal budget."""

from typing import Any, NotRequired, TypedDict

from app.rag.safety.claim_verification import (
    ClaimVerificationResult,
    split_claim_spans,
    verify_claim_with_fallback,
)

_VISIBLE_EVIDENCE_SKIP_KEYS = frozenset(
    {
        "citations",
        "document_id",
        "chunk_id",
        "page_number",
        "page",
        "relevance_score",
        "retrieval_score",
        "vector_score",
        "bm25_score",
        "keyword_score",
        "rerank_score",
        "reranker_provider",
        "rerank_model_used",
    }
)


class _VisibleEvidenceMeta(TypedDict):
    strings_scrubbed: int
    strings_changed: int
    claims_total: int
    claims_removed: int
    claim_check_removed_reasons: list[dict[str, Any]]
    max_claims: int
    max_depth: int
    max_items: int
    visited_items: NotRequired[int]
    claims_remaining: NotRequired[int]


class _VisibleEvidenceState(TypedDict):
    evidence_text: str
    max_items: int
    meta: _VisibleEvidenceMeta
    nli_model_name: str | None
    nli_provider: str | None
    nli_timeout_sec: float | None
    remaining_claims: int
    use_nli_fallback: bool
    verifier_enable_contradiction_check: bool
    verifier_mode: str
    visited_items: int


def _visible_evidence_meta(*, max_claims: int, max_depth: int, max_items: int) -> _VisibleEvidenceMeta:
    return {
        "strings_scrubbed": 0,
        "strings_changed": 0,
        "claims_total": 0,
        "claims_removed": 0,
        "claim_check_removed_reasons": [],
        "max_claims": max_claims,
        "max_depth": max_depth,
        "max_items": max_items,
    }


def _append_removed_claim_reason(
    meta: _VisibleEvidenceMeta, claim: str, verification_result: ClaimVerificationResult
) -> None:
    reasons = meta["claim_check_removed_reasons"]
    if len(reasons) >= 64:
        return
    diagnostics = verification_result.diagnostics
    contradiction = diagnostics.get("contradiction_type")
    reasons.append(
        {
            "claim": claim[:300],
            "reason_code": str(diagnostics.get("reason_code") or diagnostics.get("reason") or "unsupported")[:120],
            "contradiction_type": str(contradiction)[:120] if contradiction is not None else None,
        }
    )


def _scrub_visible_evidence_string(
    raw: str,
    *,
    evidence_text: str,
    remaining_claims: int,
    meta: _VisibleEvidenceMeta,
    verifier_mode: str,
    verifier_enable_contradiction_check: bool,
    use_nli_fallback: bool,
    nli_provider: str | None,
    nli_model_name: str | None,
    nli_timeout_sec: float | None,
) -> tuple[str, int]:
    text = raw
    if not text.strip() or remaining_claims <= 0:
        return text, 0

    claims = split_claim_spans(text, max_claims=remaining_claims)
    meta["claims_total"] += len(claims)

    kept: list[str] = []
    cursor = 0
    removed = 0
    for span in claims:
        claim = span.text
        verification = verify_claim_with_fallback(
            claim,
            evidence_text,
            verifier_mode=verifier_mode,
            verifier_enable_contradiction_check=verifier_enable_contradiction_check,
            use_nli_fallback=bool(use_nli_fallback),
            nli_provider=nli_provider,
            nli_model_name=nli_model_name,
            nli_timeout_sec=nli_timeout_sec,
        )
        if bool(verification.supported):
            continue
        kept.append(text[cursor : span.start])
        cursor = span.end
        removed += 1
        _append_removed_claim_reason(meta, claim, verification)
    if removed:
        meta["claims_removed"] += removed
        kept.append(text[cursor:])
        return "".join(kept), len(claims)
    return text, len(claims)


def _walk_visible_evidence_dict(obj: dict[Any, Any], state: _VisibleEvidenceState, *, depth: int) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for key, value in obj.items():
        key_str = str(key)
        out[key] = (
            value if key_str in _VISIBLE_EVIDENCE_SKIP_KEYS else _walk_visible_evidence(value, state, depth=depth - 1)
        )
    return out


def _walk_visible_evidence_list(obj: list[Any], state: _VisibleEvidenceState, *, depth: int) -> list[Any]:
    out: list[Any] = []
    for item in obj:
        value = _walk_visible_evidence(item, state, depth=depth - 1)
        if isinstance(value, str) and not value.strip():
            continue
        out.append(value)
    return out


def _walk_visible_evidence(obj: Any, state: _VisibleEvidenceState, *, depth: int) -> Any:
    if state["visited_items"] >= state["max_items"]:
        return obj
    state["visited_items"] += 1

    if depth <= 0:
        return obj
    if isinstance(obj, dict):
        return _walk_visible_evidence_dict(obj, state, depth=depth)
    if isinstance(obj, list):
        return _walk_visible_evidence_list(obj, state, depth=depth)
    if not isinstance(obj, str):
        return obj

    meta = state["meta"]
    meta["strings_scrubbed"] += 1
    cleaned, consumed = _scrub_visible_evidence_string(
        obj,
        evidence_text=state["evidence_text"],
        remaining_claims=state["remaining_claims"],
        meta=meta,
        verifier_mode=state["verifier_mode"],
        verifier_enable_contradiction_check=state["verifier_enable_contradiction_check"],
        use_nli_fallback=state["use_nli_fallback"],
        nli_provider=state["nli_provider"],
        nli_model_name=state["nli_model_name"],
        nli_timeout_sec=state["nli_timeout_sec"],
    )
    state["remaining_claims"] -= consumed
    if cleaned != obj:
        meta["strings_changed"] += 1
    return cleaned


def scrub_structured_output_visible_evidence_only(
    data: Any,
    *,
    evidence_text: str,
    max_claims: int = 24,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
    max_depth: int = 6,
    max_items: int = 500,
) -> tuple[Any, _VisibleEvidenceMeta]:
    """
    Best-effort structured-output scrubbing for strict grounding.

    This keeps the JSON shape, but removes unsupported natural-language claims inside string fields.
    The traversal and claim budgets bound verification work. Explicitly enabled
    NLI fallback may use the configured model; the default verifier is local.

    Notes:
    - We intentionally do NOT scrub common identifier/citation keys (UUIDs, ids) because they are
      not "claims" and would almost always be removed by evidence checks.
    - We apply a global max_claims budget across all visited string fields to keep it bounded.
    """
    max_claims = max(1, int(max_claims or 0))
    max_depth = max(1, int(max_depth or 0))
    max_items = max(1, int(max_items or 0))
    meta = _visible_evidence_meta(max_claims=max_claims, max_depth=max_depth, max_items=max_items)
    state: _VisibleEvidenceState = {
        "evidence_text": evidence_text,
        "max_items": max_items,
        "meta": meta,
        "nli_model_name": nli_model_name,
        "nli_provider": nli_provider,
        "nli_timeout_sec": nli_timeout_sec,
        "remaining_claims": max_claims,
        "use_nli_fallback": bool(use_nli_fallback),
        "verifier_enable_contradiction_check": bool(verifier_enable_contradiction_check),
        "verifier_mode": verifier_mode,
        "visited_items": 0,
    }
    scrubbed = _walk_visible_evidence(data, state, depth=max_depth)
    meta["visited_items"] = state["visited_items"]
    meta["claims_remaining"] = state["remaining_claims"]
    return scrubbed, meta


__all__ = ["scrub_structured_output_visible_evidence_only"]
