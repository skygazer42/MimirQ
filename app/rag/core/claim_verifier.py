
import re
from dataclasses import dataclass
from typing import Any

_CLAIM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_UNCERTAINTY_RE = re.compile(
    r"(unable to answer|cannot determine|can't determine|insufficient evidence|not enough (?:info|information)|unknown|unsure|not sure|"
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

    if not c:
        return ClaimVerificationResult(
            supported=True,
            mode=m,
            diagnostics={
                "reason": "empty_claim",
                "reason_code": "empty_claim",
                "contradiction_type": None,
            },
        )
    if _UNCERTAINTY_RE.search(c):
        return ClaimVerificationResult(
            supported=True,
            mode=m,
            diagnostics={
                "reason": "uncertainty_claim",
                "reason_code": "uncertainty_claim",
                "contradiction_type": None,
            },
        )
    if not e:
        return ClaimVerificationResult(
            supported=False,
            mode=m,
            diagnostics={
                "reason": "empty_evidence",
                "reason_code": "empty_evidence",
                "contradiction_type": None,
            },
        )

    c_tokens = _token_set(c)
    e_tokens = _token_set(e)
    if not c_tokens:
        return ClaimVerificationResult(
            supported=True,
            mode=m,
            diagnostics={
                "reason": "no_claim_tokens",
                "reason_code": "no_claim_tokens",
                "contradiction_type": None,
            },
        )
    if not e_tokens:
        return ClaimVerificationResult(
            supported=False,
            mode=m,
            diagnostics={
                "reason": "no_evidence_tokens",
                "reason_code": "no_evidence_tokens",
                "contradiction_type": None,
            },
        )

    shared = c_tokens.intersection(e_tokens)
    shared_n = int(len(shared))
    claim_n = int(len(c_tokens))
    overlap_ratio = float(shared_n) / float(max(1, claim_n))
    overlap_ok = _overlap_supported(c_tokens, e_tokens, mode=m)

    numeric_mismatch = False
    negation_conflict = False
    if bool(enable_contradiction_check):
        claim_nums = _numbers(c)
        if claim_nums:
            evidence_nums = _numbers(e)
            numeric_mismatch = not claim_nums.issubset(evidence_nums)
        # Only fire negation conflict when there is lexical overlap.
        claim_neg = bool(_NEGATION_RE.search(c))
        evidence_neg = bool(_NEGATION_RE.search(e))
        negation_conflict = (claim_neg != evidence_neg) and shared_n >= 2

    supported = bool(overlap_ok)
    if m in {"semantic_heuristic", "strict"}:
        if numeric_mismatch or negation_conflict:
            supported = False

    contradiction_type: str | None = None
    if numeric_mismatch and negation_conflict:
        contradiction_type = "numeric_and_negation"
    elif numeric_mismatch:
        contradiction_type = "numeric_mismatch"
    elif negation_conflict:
        contradiction_type = "negation_conflict"

    if supported:
        reason_code = "supported"
    elif contradiction_type == "numeric_and_negation":
        reason_code = "contradiction_numeric_and_negation"
    elif contradiction_type == "numeric_mismatch":
        reason_code = "contradiction_numeric_mismatch"
    elif contradiction_type == "negation_conflict":
        reason_code = "contradiction_negation_conflict"
    elif not overlap_ok:
        reason_code = "overlap_insufficient"
    else:
        reason_code = "unsupported"

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
