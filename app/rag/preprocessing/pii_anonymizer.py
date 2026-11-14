"""
PII anonymization helpers for governance cleaning.

This is a lightweight, dependency-free anonymizer intended for:
- preview-time cleaning (/pipeline/clean-preview)
- optional ingestion-time governance cleaning

It uses conservative patterns with basic validators to reduce false positives.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

PiiMode = Literal["mask", "token"]


@dataclass(frozen=True)
class PiiAnonymizeResult:
    text: str
    hits: dict[str, int]
    changed: bool


@dataclass(frozen=True)
class PiiMatch:
    kind: str
    start: int
    end: int
    text: str


_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CN_ID18_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

# Very permissive digit runs; validated by Luhn.
_CREDIT_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)\d(?:[ -]*\d){12,18}(?!\d)")

# Phone-ish patterns: validated loosely (length + digit ratio).
_CN_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_PHONE_GENERIC_RE = re.compile(r"(?<!\d)\+?\d[\d\s().-]{7,}\d(?!\d)")


def _valid_ipv4(text: str) -> bool:
    parts = text.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    return all(0 <= n <= 255 for n in nums)


_CN_ID18_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CN_ID18_CHECK = "10X98765432"


def _valid_cn_id18(text: str) -> bool:
    if len(text) != 18:
        return False
    body = text[:17]
    last = text[17].upper()
    if not body.isdigit() or last not in "0123456789X":
        return False

    # Validate birthdate (YYYYMMDD at positions 7-14; zero-based 6-13).
    try:
        year = int(text[6:10])
        month = int(text[10:12])
        day = int(text[12:14])
        if year < 1900 or year > 2100:
            return False
        date(year, month, day)
    except ValueError:
        return False

    # Checksum.
    total = 0
    for idx, ch in enumerate(body):
        total += int(ch) * _CN_ID18_WEIGHTS[idx]
    expect = _CN_ID18_CHECK[total % 11]
    return last == expect


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit():
        return False
    n = len(digits)
    if n < 13 or n > 19:
        return False
    s = 0
    parity = n % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return (s % 10) == 0


def _valid_credit_card(text: str) -> bool:
    digits = re.sub(r"[^\d]", "", text)
    return _luhn_ok(digits)


def _valid_phone_candidate(text: str) -> bool:
    digits = re.sub(r"[^\d]", "", text)
    # Keep it loose: 8-15 digits is a reasonable phone range; avoid long numeric runs.
    if len(digits) < 8 or len(digits) > 15:
        return False
    # Require at least ~60% digits (avoid matching sentences with many separators).
    return (len(digits) / len(text)) >= 0.6


_PII_MATCH_PATTERNS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    ("email", _EMAIL_RE, None),
    ("ip", _IPV4_RE, _valid_ipv4),
    ("ssn", _SSN_RE, None),
    ("cn_id", _CN_ID18_RE, _valid_cn_id18),
    ("credit_card", _CREDIT_CARD_CANDIDATE_RE, _valid_credit_card),
    ("phone", _CN_MOBILE_RE, None),
    ("phone", _PHONE_GENERIC_RE, _valid_phone_candidate),
]


def anonymize_pii(text: str, *, enabled: bool, mode: PiiMode = "mask", mask: str = "[REDACTED]") -> PiiAnonymizeResult:
    original = text
    if not enabled or not original:
        return PiiAnonymizeResult(text=original, hits={}, changed=False)

    hits: dict[str, int] = {}
    token_maps: dict[str, dict[str, str]] = {}

    def make_replacer(kind: str, *, validator: Callable[[str], bool] | None = None) -> Callable[[re.Match[str]], str]:
        token_map = token_maps.setdefault(kind, {})

        def repl(match: re.Match[str]) -> str:
            raw = match.group(0)
            if validator is not None and not validator(raw):
                return raw
            hits[kind] = hits.get(kind, 0) + 1
            if mode == "mask":
                return mask
            existing = token_map.get(raw)
            if existing:
                return existing
            token = f"[PII_{kind.upper()}_{len(token_map) + 1}]"
            token_map[raw] = token
            return token

        return repl

    current = original
    for kind, pattern, validator in _PII_MATCH_PATTERNS:
        current = pattern.sub(make_replacer(kind, validator=validator), current)

    return PiiAnonymizeResult(text=current, hits=hits, changed=(current != original))


def find_pii_matches(text: str, *, max_matches: int = 50) -> list[PiiMatch]:
    """
    Find PII matches with the same (conservative) validators used by anonymize_pii().

    Intended for review-time displays (precheck / governance debug). Results are
    best-effort and may include false positives; callers should show them as
    "needs review" rather than hard conclusions.
    """
    if not text:
        return []

    max_matches = max(0, min(int(max_matches or 0), 200))
    if max_matches == 0:
        return []

    taken: list[tuple[int, int]] = []
    out: list[PiiMatch] = []

    for kind, pattern, validator in _PII_MATCH_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0)
            start, end = match.start(), match.end()
            if any(start < taken_end and end > taken_start for taken_start, taken_end in taken):
                continue
            if validator is not None and not validator(raw):
                continue
            out.append(PiiMatch(kind=kind, start=start, end=end, text=raw))
            taken.append((start, end))
            if len(out) >= max_matches:
                break
        if len(out) >= max_matches:
            break

    out.sort(key=lambda x: (x.start, x.end))
    return out
