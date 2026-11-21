"""
Evidence helpers for KG extraction.

We persist evidence (quote + best-effort char span) for:
- event -> entity links (kg_event_entities.extra_data)
- entity -> entity relations (kg_relations.references)

This module is intentionally dependency-light and deterministic.
"""

import math
import re
import unicodedata
from dataclasses import dataclass

_WS_RE = re.compile(r"\s+")
_EDGE_STRIP_CHARS = " \t\r\n,.;:!?，。；：！？、\"'`“”‘’()（）[]【】"


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", _clean(text)).strip()


def _can_use_ascii_fallback(needle: str) -> bool:
    return needle.isascii() and len(needle) >= 6 and any(ch.isalpha() for ch in needle)


def clamp_confidence(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("confidence must be a number")
    try:
        f = float(value)  # type: ignore[arg-type]
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("confidence must be a finite number") from exc
    if not math.isfinite(f):
        raise ValueError("confidence must be a finite number")
    return max(0.0, min(1.0, f))


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
    if not text or not quote:
        return None

    start = text.find(quote)
    if start >= 0:
        return start, start + len(quote)

    parts = quote.split()
    if len(parts) > 1:
        pattern = r"\s+".join(re.escape(part) for part in parts)
        match = re.search(pattern, text)
        if match is not None:
            return match.span()
    else:
        pattern = re.escape(quote)

    if _can_use_ascii_fallback(quote):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is not None:
            return match.span()
    return None


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
    mention = mention.strip()
    if not text or not mention or len(mention) > max_quote_chars:
        return None

    start = text.find(mention)
    if start < 0 and mention.isascii():
        match = re.search(re.escape(mention), text, flags=re.IGNORECASE)
        if match is not None:
            start = match.start()
    if start < 0:
        return None

    # The bounded window must retain the entire matched mention.
    width = min(max_quote_chars, max(40, window_chars, len(mention)))
    left = max(0, start - (width - len(mention)) // 2)
    right = min(len(text), left + width)
    left = max(0, right - width)
    raw_quote = text[left:right]
    left += len(raw_quote) - len(raw_quote.lstrip())
    quote = raw_quote.strip()
    return EvidenceSpan(quote=quote, start_char=left, end_char=left + len(quote), source="mention")


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
    hay = text
    if not hay or max_quote_chars <= 0:
        return None

    quote_in = evidence_quote.strip() if evidence_quote is not None else ""
    if quote_in:
        span = find_evidence_span(hay, quote_in)
        if span is not None:
            s, e = span
            raw_quote = hay[s : min(e, s + max_quote_chars)]
            s += len(raw_quote) - len(raw_quote.lstrip())
            q = raw_quote.strip()
            e = s + len(q)
            if not q:
                return None
            return EvidenceSpan(quote=q, start_char=int(s), end_char=int(e), source="quote")

    mention = fallback_mention.strip() if fallback_mention is not None else ""
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
    "clamp_confidence",
    "coerce_evidence",
    "derive_evidence_from_mention",
    "find_evidence_span",
    "normalize_surface_for_match",
    "surface_mentioned",
]
