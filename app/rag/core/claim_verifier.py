import re
from dataclasses import dataclass
from typing import Any

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


def _token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for m in _CLAIM_TOKEN_RE.finditer(text or ""):
        t = (m.group(0) or "").strip()
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


def _numbers(text: str) -> set[str]:
    return {str(m.group(0) or "").strip() for m in _NUMBER_RE.finditer(text or "") if str(m.group(0) or "").strip()}


def _normalize_mode(value: Any) -> str:
    raw = str(value or "token_overlap").strip().lower()
    if raw in {"overlap", "token", "token_overlap"}:
        return "token_overlap"
    if raw in {"semantic", "semantic_heuristic", "heuristic"}:
        return "semantic_heuristic"
    if raw in {"strict", "strict_overlap"}:
        return "strict"
    return "token_overlap"


def _overlap_supported(claim_tokens: set[str], evidence_tokens: set[str], *, mode: str) -> bool:
    shared_n = len(claim_tokens.intersection(evidence_tokens))
    if shared_n <= 0:
        return False

    claim_n = len(claim_tokens)
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
    if _UNCERTAINTY_RE.search(claim):
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
    c = str(claim or "").strip()
    e = str(evidence or "").strip()

    early = _early_result(m, c, e)
    if early is not None:
        return early

    c_tokens = _token_set(c)
    e_tokens = _token_set(e)
    token_result = _token_result(m, claim_tokens=c_tokens, evidence_tokens=e_tokens)
    if token_result is not None:
        return token_result

    shared = c_tokens.intersection(e_tokens)
    shared_n = int(len(shared))
    claim_n = int(len(c_tokens))
    overlap_ratio = float(shared_n) / float(max(1, claim_n))
    overlap_ok = _overlap_supported(c_tokens, e_tokens, mode=m)

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
        "evidence_tokens": int(len(e_tokens)),
        "shared_tokens": shared_n,
        "overlap_ratio": round(float(overlap_ratio), 4),
        "numeric_mismatch": bool(numeric_mismatch),
        "negation_conflict": bool(negation_conflict),
        "contradiction_check_enabled": bool(enable_contradiction_check),
    }
    return ClaimVerificationResult(supported=bool(supported), mode=m, diagnostics=diagnostics)


__all__ = ["ClaimVerificationResult", "verify_claim"]
