"""
Evidence helpers for KG extraction.

We persist evidence (quote + best-effort char span) for:
- event -> entity links (kg_event_entities.extra_data)
- entity -> entity relations (kg_relations.references)

This module is intentionally dependency-light and deterministic.
"""


import re
import unicodedata
from dataclasses import dataclass

_WS_RE = re.compile(r"\s+")
_SENTENCE_BREAK_RE = re.compile(r"[。！？!?\n\r]")
_EDGE_STRIP_CHARS = " \t\r\n,.;:!?，。；：！？、\"'`“”‘’()（）[]【】"


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", _clean(text)).strip()


def _ascii_case_insensitive_match(pattern: str, hay: str) -> tuple[int, int] | None:
    try:
        match = re.search(pattern, hay, flags=re.IGNORECASE | re.MULTILINE)
    except re.error:
        return None
    if not match:
        return None
    return int(match.start()), int(match.end())


def _can_use_ascii_fallback(needle: str) -> bool:
    return needle.isascii() and len(needle) >= 6 and any(ch.isalpha() for ch in needle)


@dataclass(frozen=True)
class EvidenceSpan:
    quote: str
    start_char: int
    end_char: int
    # Evidence origin:
    # - "quote": span was matched from an explicit evidence_quote string.
    # - "mention": span was derived by locating a mention surface and expanding to a sentence-ish window.
    source: str


def find_evidence_span(text: str, quote: str) -> tuple[int, int] | None:
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
        # Best-effort: allow ASCII case-insensitive matching for short single-token quotes.
        if _can_use_ascii_fallback(needle):
            return _ascii_case_insensitive_match(re.escape(needle), hay)
        return None
    pat = r"\s+".join(re.escape(p) for p in parts)
    try:
        m = re.search(pat, hay, flags=re.MULTILINE)
    except re.error:
        return None
    if not m:
        # ASCII case-insensitive fallback: helps when the model changes casing in evidence_quote.
        if _can_use_ascii_fallback(needle):
            return _ascii_case_insensitive_match(pat, hay)
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
) -> EvidenceSpan | None:
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

    return EvidenceSpan(quote=quote, start_char=int(left2), end_char=int(right2), source="mention")


def coerce_evidence(
    *,
    text: str,
    evidence_quote: str | None,
    fallback_mention: str | None,
    max_quote_chars: int = 240,
) -> EvidenceSpan | None:
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
            return EvidenceSpan(quote=q, start_char=int(s), end_char=int(e), source="quote")

    mention = str(fallback_mention or "").strip()
    if mention:
        return derive_evidence_from_mention(text=hay, mention=mention, max_quote_chars=max_quote_chars)

    return None


def normalize_surface_for_match(text: str) -> str:
    """
    Normalize a surface/quote for substring matching (not for persistence).

    This is used for deterministic checks like:
    - "does evidence quote mention the entity surface?"
    - "does a tag/category label appear in the quote?"
    """
    s = _collapse_ws(text)
    if not s:
        return ""
    s = s.strip(_EDGE_STRIP_CHARS)
    return s.casefold()


def surface_mentioned(*, quote: str, surface: str) -> bool:
    """
    Best-effort check whether `surface` is mentioned in `quote` after lightweight normalization.
    """
    q = normalize_surface_for_match(quote)
    s = normalize_surface_for_match(surface)
    if not q or not s:
        return False
    return s in q


__all__ = [
    "EvidenceSpan",
    "coerce_evidence",
    "derive_evidence_from_mention",
    "find_evidence_span",
    "normalize_surface_for_match",
    "surface_mentioned",
]
