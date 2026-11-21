"""Split answer claims and verify their support against retrieved evidence."""

import re
from dataclasses import dataclass
from typing import Any

from app.rag.safety.claim_nli import verify_claim_with_nli

_CLAIM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


_UNCERTAINTY_RE = re.compile(
    r"(unable to answer|cannot determine|can't determine|insufficient evidence|"
    r"not enough (?:info|information)|unknown|unsure|not sure|"
    r"证据不足|材料不足|无法(确定|判断|回答)|不确定|未知)",
    flags=re.IGNORECASE,
)


_NEGATION_RE = re.compile(r"\b(?:not|no|never|without|none|n't)\b|不|无|未|没有", flags=re.IGNORECASE)


_EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class ClaimVerificationResult:
    supported: bool
    mode: str
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class ClaimSpan:
    """Normalized claim text and its real removal window in the input answer."""

    text: str
    start: int
    end: int


def claim_token_set(text: str) -> set[str]:
    """Return the shared claim tokens used for verification and evidence ranking."""
    tokens: set[str] = set()
    for m in _CLAIM_TOKEN_RE.finditer(text):
        t = (m.group(0)).strip()
        if not t:
            continue
        if t.isascii():
            folded = t.casefold()
            if folded in _EN_STOPWORDS:
                continue
            tokens.add(folded)
        else:
            tokens.add(t)
    return tokens


def is_uncertainty_claim(claim: str) -> bool:
    return bool(_UNCERTAINTY_RE.search(claim))


def _numbers(text: str) -> set[str]:
    return {m.group(0).strip() for m in _NUMBER_RE.finditer(text) if m.group(0).strip()}


def _normalize_mode(value: Any) -> str:
    raw = str(value or "token_overlap").strip().lower()
    if raw in {"overlap", "token", "token_overlap"}:
        return "token_overlap"
    if raw in {"semantic", "semantic_heuristic", "heuristic"}:
        return "semantic_heuristic"
    if raw in {"strict", "strict_overlap"}:
        return "strict"
    return "token_overlap"


def _overlap_supported(shared_n: int, claim_n: int, *, mode: str) -> bool:
    if shared_n <= 0:
        return False

    if mode == "strict":
        return shared_n >= 2 and (shared_n / float(max(1, claim_n))) >= 0.5

    if claim_n <= 3:
        return shared_n >= 1
    if claim_n <= 8:
        return shared_n >= 2 or (shared_n / float(claim_n)) >= 0.34
    return shared_n >= 2 and (shared_n / float(claim_n)) >= 0.2


def _result(mode: str, *, supported: bool, reason_code: str, contradiction_type: str | None) -> ClaimVerificationResult:
    return ClaimVerificationResult(
        supported=supported,
        mode=mode,
        diagnostics={
            "reason": reason_code,
            "reason_code": reason_code,
            "contradiction_type": contradiction_type,
        },
    )


def _early_result(mode: str, claim: str, evidence: str) -> ClaimVerificationResult | None:
    if not claim:
        return _result(mode, supported=True, reason_code="empty_claim", contradiction_type=None)
    if is_uncertainty_claim(claim):
        return _result(mode, supported=True, reason_code="uncertainty_claim", contradiction_type=None)
    if not evidence:
        return _result(mode, supported=False, reason_code="empty_evidence", contradiction_type=None)
    return None


def _token_result(
    mode: str,
    *,
    claim_tokens: set[str],
    evidence_tokens: set[str],
) -> ClaimVerificationResult | None:
    if claim_tokens:
        if evidence_tokens:
            return None
        return _result(mode, supported=False, reason_code="no_evidence_tokens", contradiction_type=None)
    return _result(mode, supported=True, reason_code="no_claim_tokens", contradiction_type=None)


def _contradiction_flags(claim: str, evidence: str, *, shared_n: int, enabled: bool) -> tuple[bool, bool]:
    if not enabled:
        return False, False
    claim_nums = _numbers(claim)
    evidence_nums = _numbers(evidence) if claim_nums else set()
    numeric_mismatch = bool(claim_nums) and not claim_nums.issubset(evidence_nums)
    claim_neg = bool(_NEGATION_RE.search(claim))
    evidence_neg = bool(_NEGATION_RE.search(evidence))
    negation_conflict = (claim_neg != evidence_neg) and shared_n >= 2
    return numeric_mismatch, negation_conflict


def _contradiction_type(*, numeric_mismatch: bool, negation_conflict: bool) -> str | None:
    if numeric_mismatch and negation_conflict:
        return "numeric_and_negation"
    if numeric_mismatch:
        return "numeric_mismatch"
    if negation_conflict:
        return "negation_conflict"
    return None


def _reason_code(*, supported: bool, contradiction_type: str | None, overlap_ok: bool) -> str:
    if supported:
        return "supported"
    if contradiction_type == "numeric_and_negation":
        return "contradiction_numeric_and_negation"
    if contradiction_type == "numeric_mismatch":
        return "contradiction_numeric_mismatch"
    if contradiction_type == "negation_conflict":
        return "contradiction_negation_conflict"
    if not overlap_ok:
        return "overlap_insufficient"
    return "unsupported"


def verify_claim(
    claim: str,
    evidence: str,
    *,
    mode: str = "token_overlap",
    enable_contradiction_check: bool = True,
) -> ClaimVerificationResult:
    m = _normalize_mode(mode)
    c = claim.strip()
    e = evidence.strip()

    early = _early_result(m, c, e)
    if early is not None:
        return early

    c_tokens = claim_token_set(c)
    e_tokens = claim_token_set(e)
    token_result = _token_result(m, claim_tokens=c_tokens, evidence_tokens=e_tokens)
    if token_result is not None:
        return token_result

    shared_n = len(c_tokens.intersection(e_tokens))
    claim_n = len(c_tokens)
    overlap_ratio = shared_n / claim_n
    overlap_ok = _overlap_supported(shared_n, claim_n, mode=m)

    numeric_mismatch, negation_conflict = _contradiction_flags(
        c,
        e,
        shared_n=shared_n,
        enabled=bool(enable_contradiction_check),
    )

    supported = bool(overlap_ok)
    if m in {"semantic_heuristic", "strict"}:
        if numeric_mismatch or negation_conflict:
            supported = False

    contradiction_type = _contradiction_type(
        numeric_mismatch=numeric_mismatch,
        negation_conflict=negation_conflict,
    )
    reason_code = _reason_code(
        supported=supported,
        contradiction_type=contradiction_type,
        overlap_ok=overlap_ok,
    )

    diagnostics = {
        "mode": m,
        "reason": reason_code,
        "reason_code": reason_code,
        "contradiction_type": contradiction_type,
        "claim_tokens": claim_n,
        "evidence_tokens": len(e_tokens),
        "shared_tokens": shared_n,
        "overlap_ratio": round(overlap_ratio, 4),
        "numeric_mismatch": bool(numeric_mismatch),
        "negation_conflict": bool(negation_conflict),
        "contradiction_check_enabled": bool(enable_contradiction_check),
    }
    return ClaimVerificationResult(supported=bool(supported), mode=m, diagnostics=diagnostics)


_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)


def _parse_claim_list_item(raw: str) -> str | None:
    text = (raw).lstrip()
    if not text:
        return None

    if text[0] in ("-", "*", "•"):
        return _parse_bullet_claim(text)

    marker_index = _numbered_claim_marker_index(text)
    if marker_index is None:
        return None
    return _claim_after_numbered_marker(text, marker_index)


def _parse_bullet_claim(text: str) -> str | None:
    if len(text) < 2 or not text[1].isspace():
        return None
    return text[1:].strip() or None


def _numbered_claim_marker_index(text: str) -> int | None:
    index = 0
    while index < len(text) and text[index].isdigit():
        index += 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index <= 0 or index >= len(text) or text[index] not in (".", ")"):
        return None
    return index


def _claim_after_numbered_marker(text: str, marker_index: int) -> str | None:
    content_index = marker_index + 1
    if content_index >= len(text) or not text[content_index].isspace():
        return None
    return text[content_index:].strip() or None


def split_claim_spans(text: str, *, max_claims: int = 24) -> list[ClaimSpan]:
    """Apply the existing claim grammar while tracking actual source windows.

    Paragraph line joins map to their original whitespace. A list item's removal
    window includes its authored marker and line ending, so removing it leaves
    no orphaned list marker. Unprocessed source after the budget remains outside
    every returned window.
    """
    max_claims = max(1, int(max_claims or 0))
    claims: list[ClaimSpan] = []
    paragraph_lines: list[tuple[str, int]] = []

    def flush_paragraph() -> bool:
        if not paragraph_lines:
            return False
        parts: list[str] = []
        source_indices: list[int] = []
        previous_end = 0
        for line, start in paragraph_lines:
            if parts:
                parts.append(" ")
                source_indices.append(previous_end)
            parts.append(line)
            source_indices.extend(range(start, start + len(line)))
            previous_end = start + len(line)
        paragraph_lines.clear()
        paragraph = "".join(parts)
        for match in _SENTENCE_RE.finditer(paragraph):
            raw = match.group(0)
            sentence = raw.strip()
            if not sentence:
                continue
            start = match.start() + len(raw) - len(raw.lstrip())
            end = match.end() - (len(raw) - len(raw.rstrip()))
            claims.append(ClaimSpan(sentence, source_indices[start], source_indices[end - 1] + 1))
            if len(claims) >= max_claims:
                return True
        return False

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        start = offset
        offset += len(raw_line)
        line = raw_line.strip()
        if not line:
            if flush_paragraph():
                break
            continue
        item = _parse_claim_list_item(raw_line)
        if item is not None:
            if flush_paragraph():
                break
            claims.append(ClaimSpan(item, start, offset))
            if len(claims) >= max_claims:
                break
        else:
            paragraph_lines.append((line, start + len(raw_line) - len(raw_line.lstrip())))
    if len(claims) < max_claims:
        flush_paragraph()
    return claims


def split_into_claims(text: str, *, max_claims: int = 24) -> list[str]:
    """
    Split assistant answers into simple atomic claims for post-processing.

    Heuristics:
    - Sentence-level splitting for paragraphs
    - Markdown list items become individual claims
    - Preserve original order, drop empty claims, bound to `max_claims`
    """
    return [claim.text for claim in split_claim_spans(text, max_claims=max_claims)]


def verify_claim_with_fallback(
    claim: str,
    evidence: str,
    *,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
) -> ClaimVerificationResult:
    result = verify_claim(
        claim,
        evidence,
        mode=verifier_mode,
        enable_contradiction_check=bool(verifier_enable_contradiction_check),
    )
    if bool(result.supported) or not bool(use_nli_fallback):
        return result

    nli_result = verify_claim_with_nli(
        claim,
        evidence,
        enabled=True,
        provider=nli_provider,
        model_name=nli_model_name,
        timeout_sec=nli_timeout_sec,
    )
    diagnostics = dict(result.diagnostics)
    diagnostics["nli_fallback"] = {
        "available": bool(nli_result.available),
        "label": nli_result.label,
        "provider": dict(nli_result.provider_status),
        "reason_code": nli_result.diagnostics["reason_code"],
    }
    if not bool(nli_result.available) or nli_result.supported is None:
        return result.__class__(supported=result.supported, mode=result.mode, diagnostics=diagnostics)

    diagnostics["reason"] = nli_result.diagnostics["reason_code"]
    diagnostics["reason_code"] = nli_result.diagnostics["reason_code"]
    diagnostics["contradiction_type"] = None
    return result.__class__(
        supported=bool(nli_result.supported),
        mode=f"{result.mode}+nli",
        diagnostics=diagnostics,
    )


def is_claim_supported(
    claim: str,
    evidence: str,
    *,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
) -> bool:
    """
    Deterministic baseline: token-overlap check between a claim and evidence text.

    Notes:
    - Always keep "uncertainty/insufficient evidence" phrasing (do not delete refusals).
    - Heuristic only; designed to be safe and bounded.
    """
    result = verify_claim_with_fallback(
        claim,
        evidence,
        verifier_mode=verifier_mode,
        verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
        use_nli_fallback=bool(use_nli_fallback),
        nli_provider=nli_provider,
        nli_model_name=nli_model_name,
        nli_timeout_sec=nli_timeout_sec,
    )
    return bool(result.supported)


__all__ = [
    "ClaimVerificationResult",
    "ClaimSpan",
    "claim_token_set",
    "is_uncertainty_claim",
    "verify_claim",
    "split_into_claims",
    "split_claim_spans",
    "verify_claim_with_fallback",
    "is_claim_supported",
]
