"""
URL normalization helpers for governance cleaning.

Primary goal: improve consistency/dedup by stripping common tracking parameters
without changing the URL path/host.

This is opt-in because rewriting URLs can be surprising in some domains.
"""


import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_PLAIN_URL_RE = re.compile(r"(?P<url>https?://[^\s<>()]+)")
_MD_LINK_RE = re.compile(r"(\]\()(?P<url>\S+?)(\))")
_TRAILING_URL_PUNCT = frozenset(")].,;:!?")

_TRACKING_KEYS = frozenset(
    {
        "gclid",
        "fbclid",
        "igshid",
        "msclkid",
        "spm",
        "scm",
        "ref",
        "ref_src",
        "_hsenc",
        "_hsmi",
        "mkt_tok",
        "sr",
    }
)


@dataclass(frozen=True)
class UrlNormalizeResult:
    text: str
    urls_changed: int
    changed: bool


def _is_tracking_key(key: str) -> bool:
    k = (key or "").strip()
    if not k:
        return False
    k_cf = k.casefold()
    if k_cf.startswith("utm_"):
        return True
    return k_cf in _TRACKING_KEYS


def canonicalize_url(url: str, *, strip_tracking: bool = True) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw

    try:
        parts = urlsplit(raw)
    except Exception:
        return raw

    if parts.scheme not in {"http", "https"}:
        return raw

    query = parts.query or ""
    if strip_tracking and query:
        kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not _is_tracking_key(k)]
        query = urlencode(kept, doseq=True)

    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def normalize_urls(text: str, *, strip_tracking: bool = True) -> UrlNormalizeResult:
    original = text or ""
    if not original:
        return UrlNormalizeResult(text="", urls_changed=0, changed=False)

    changed = 0

    def _rewrite_url(raw_url: str) -> str:
        nonlocal changed
        url_body = raw_url
        suffix = ""
        if url_body:
            i = len(url_body)
            while i > 0 and url_body[i - 1] in _TRAILING_URL_PUNCT:
                i -= 1
            if i < len(url_body):
                suffix = url_body[i:]
                url_body = url_body[:i]
        new = canonicalize_url(url_body, strip_tracking=strip_tracking)
        if new != url_body:
            changed += 1
        return f"{new}{suffix}"

    # Markdown links: [text](url)
    def _md_repl(m: re.Match[str]) -> str:
        url = m.group("url") or ""
        # Only rewrite the url part; keep surrounding parens.
        return f"{m.group(1)}{_rewrite_url(url)}{m.group(3)}"

    out = _MD_LINK_RE.sub(_md_repl, original)

    # Plain URLs.
    def _plain_repl(m: re.Match[str]) -> str:
        return _rewrite_url(m.group("url") or "")

    out = _PLAIN_URL_RE.sub(_plain_repl, out)

    return UrlNormalizeResult(text=out, urls_changed=int(changed), changed=(out != original))


__all__ = [
    "UrlNormalizeResult",
    "canonicalize_url",
    "normalize_urls",
]
