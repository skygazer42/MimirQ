"""
HTML canonical URL extraction (best-effort).

Used by:
- web crawling (dedup)
- URL ingestion (metadata)
"""


import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.rag.preprocessing.urls import canonicalize_url

_CANONICAL_LINK_TAG_RE = re.compile(r"(?is)<link\b[^>]*>")
_CANONICAL_REL_RE = re.compile(r"(?is)\brel\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))")
_CANONICAL_HREF_RE = re.compile(r"(?is)\bhref\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))")


def normalize_url_for_dedup(url: str) -> str:
    """
    Normalize URL for storage/dedup:
    - strip common tracking params (utm_*, gclid, fbclid, ...)
    - drop fragment
    """
    s = canonicalize_url(str(url or "").strip(), strip_tracking=True)
    try:
        parts = urlsplit(s)
    except Exception:
        return s
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))  # drop fragment


def extract_canonical_url(html_text: str, *, base_url: str) -> str | None:
    """
    Best-effort extraction of <link rel="canonical" href="..."> from HTML.

    Notes:
    - dependency-free and conservative; may miss edge cases
    - returns an absolute, normalized URL (strip tracking + drop fragment)
    """
    raw = (html_text or "").strip()
    if not raw:
        return None

    for m in _CANONICAL_LINK_TAG_RE.finditer(raw[:200_000]):  # bound work on huge pages
        tag = m.group(0) or ""
        rel_m = _CANONICAL_REL_RE.search(tag)
        rel_raw = (rel_m.group(1) or rel_m.group(2) or rel_m.group(3) or "") if rel_m else ""
        rel = str(rel_raw).strip().lower()
        if not rel:
            continue
        # rel can contain multiple tokens, e.g. "canonical nofollow".
        if "canonical" not in {t for t in re.split(r"\s+", rel) if t}:
            continue
        href_m = _CANONICAL_HREF_RE.search(tag)
        href_raw = (href_m.group(1) or href_m.group(2) or href_m.group(3) or "") if href_m else ""
        href = str(href_raw).strip()
        if not href:
            continue
        try:
            return normalize_url_for_dedup(urljoin(base_url, href))
        except Exception:
            return None
    return None


__all__ = ["extract_canonical_url", "normalize_url_for_dedup"]
