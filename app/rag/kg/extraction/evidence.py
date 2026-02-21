"""
Evidence helpers for KG extraction.

We persist evidence (quote + best-effort char span) for:
- event -> entity links (kg_event_entities.extra_data)
- entity -> entity relations (kg_relations.references)

This module is intentionally dependency-light and deterministic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_WS_RE = re.compile(r"\s+")
_SENTENCE_BREAK_RE = re.compile(r"[。！？!?。\n\r]")


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", _clean(text)).strip()


@dataclass(frozen=True)
class EvidenceSpan:
    quote: str
    start_char: int
    end_char: int


def find_evidence_span(text: str, quote: str) -> Optional[tuple[int, int]]:
    """
    Find (start,end) for `quote` inside `text`.

    Best-effort strategy:
    - exact substring match
    - whitespace-flex regex match (quote tokens joined by \\s+)
    """
    hay = str(text or "")
    needle = str(quote or "")
    if not hay or not needle:
        return None

    idx = hay.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)

    # Whitespace-flex match: split needle by any whitespace and allow \\s+ between parts.
    parts = [p for p in needle.split() if p]
    if len(parts) <= 1:
        return None
    pat = r"\s+".join(re.escape(p) for p in parts)
    try:
        m = re.search(pat, hay, flags=re.MULTILINE)
    except re.error:
        return None
    if not m:
        return None
    return int(m.start()), int(m.end())


def _expand_to_sentence_bounds(text: str, start: int, end: int, *, max_chars: int) -> tuple[int, int]:
    """
    Expand a span to nearby sentence boundaries (best-effort), staying within max_chars.
    """
    n = len(text)
    if n <= 0:
        return 0, 0
    s = max(0, min(int(start), n))
    e = max(0, min(int(end), n))
    if e < s:
        s, e = e, s

    # Expand left to previous boundary within budget.
    left = s
    budget = max(0, int(max_chars))
    while left > 0 and (s - left) < budget:
        if _SENTENCE_BREAK_RE.match(text[left - 1]):
            break
        left -= 1

    # Expand right to next boundary within budget.
    right = e
    while right < n and (right - left) < budget:
        if _SENTENCE_BREAK_RE.match(text[right]):
            right += 1
            break
        right += 1

    # Clamp again.
    right = min(n, right)
    left = max(0, min(left, right))
    return left, right


def derive_evidence_from_mention(
    *,
    text: str,
    mention: str,
    max_quote_chars: int = 240,
    window_chars: int = 200,
) -> Optional[EvidenceSpan]:
    """
    Build an evidence quote for a mention surface by locating the mention in the text.

    Returns None if the mention isn't found.
    """
    hay = str(text or "")
    m = str(mention or "").strip()
    if not hay or not m:
        return None

    idx = hay.find(m)
    if idx < 0 and m.isascii():
        # ASCII case-insensitive fallback.
        try:
            pat = re.compile(re.escape(m), flags=re.IGNORECASE)
            mm = pat.search(hay)
            if mm:
                idx = int(mm.start())
        except re.error:
            idx = -1

    if idx < 0:
        return None

    start = int(idx)
    end = int(idx + len(m))

    # Expand to a small sentence-ish quote window to provide human-readable evidence.
    win = max(40, int(window_chars or 0))
    left = max(0, start - win // 2)
    right = min(len(hay), end + win // 2)

    left2, right2 = _expand_to_sentence_bounds(hay, left, right, max_chars=win)
    quote = hay[left2:right2].strip()
    if not quote:
        return None

    if len(quote) > int(max_quote_chars):
        quote = quote[: int(max_quote_chars)]
        right2 = left2 + len(quote)

    return EvidenceSpan(quote=quote, start_char=int(left2), end_char=int(right2))


def coerce_evidence(
    *,
    text: str,
    evidence_quote: str | None,
    fallback_mention: str | None,
    max_quote_chars: int = 240,
) -> Optional[EvidenceSpan]:
    """
    Coerce evidence into a quote + span that exists in the given text.

    Preference order:
    1) Use provided evidence_quote if it can be matched in text.
    2) Otherwise, derive evidence from fallback_mention surface.
    """
    hay = str(text or "")
    if not hay:
        return None

    quote_in = str(evidence_quote or "").strip()
    if quote_in:
        span = find_evidence_span(hay, quote_in)
        if span is not None:
            s, e = span
            q = quote_in[: int(max_quote_chars)]
            # If we truncated, re-find span (best-effort); if it fails, keep original span.
            if len(quote_in) > int(max_quote_chars):
                span2 = find_evidence_span(hay, q)
                if span2 is not None:
                    s, e = span2
            return EvidenceSpan(quote=q, start_char=int(s), end_char=int(e))

    mention = str(fallback_mention or "").strip()
    if mention:
        return derive_evidence_from_mention(text=hay, mention=mention, max_quote_chars=max_quote_chars)

    return None


__all__ = [
    "EvidenceSpan",
    "coerce_evidence",
    "derive_evidence_from_mention",
    "find_evidence_span",
]

