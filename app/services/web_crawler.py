"""
Website crawler for connector runs (site-level ingestion).

Design goals:
- Keep dependencies light (lxml is already a transitive dependency via readability-lxml).
- Best-effort SSRF safety by reusing validate_url_for_ingest for each visited URL and each redirect hop.
- Allow authenticated crawling via headers (cookie/bearer/basic), without storing plaintext secrets.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from app.api.utils.url_ingest import validate_url_for_ingest
from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.rag.preprocessing.urls import canonicalize_url


_DISALLOWED_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "file:")


def _normalize_url(raw: str) -> str:
    """
    Normalize URL for crawling dedup.

    - Strip common tracking params (utm_*, gclid, fbclid, ...).
    - Drop fragment (anchors).
    - Keep query (after tracking stripping).
    """
    s = canonicalize_url(str(raw or "").strip(), strip_tracking=True)
    try:
        parts = urlsplit(s)
    except Exception:
        return s
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))  # drop fragment


def _compile_patterns(patterns: List[str]) -> List[re.Pattern[str]]:
    compiled: List[re.Pattern[str]] = []
    for raw in patterns or []:
        pat = str(raw or "").strip()
        if not pat:
            continue
        try:
            compiled.append(re.compile(pat, flags=re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"invalid url pattern: {str(exc)[:120]}") from exc
    return compiled


def _match_any(url: str, patterns: List[re.Pattern[str]]) -> bool:
    return any(p.search(url) for p in patterns)


async def _fetch_page_text(
    url: str,
    *,
    headers: Dict[str, str],
    timeout_sec: float,
    max_bytes: int,
    follow_redirects: bool,
) -> Tuple[str, str, str]:
    """
    Fetch a URL as text (best-effort), returning (text, final_url, content_type).

    Redirect handling is explicit to preserve SSRF checks per hop.
    """
    pool = get_http_client_pool()
    client = await pool.get_client()

    current = await validate_url_for_ingest(url)
    hops = 0
    max_redirects = int(getattr(settings, "URL_INGEST_MAX_REDIRECTS", 5) or 5)
    max_redirects = max(0, min(max_redirects, 20))

    while True:
        async with client.stream(
            "GET",
            current,
            headers=headers,
            timeout=httpx.Timeout(timeout_sec),
            follow_redirects=False,
        ) as resp:
            if resp.status_code in {301, 302, 303, 307, 308}:
                if not follow_redirects:
                    raise HTTPException(status_code=400, detail="redirects are not allowed")
                if hops >= max_redirects:
                    raise HTTPException(status_code=400, detail="too many redirects")
                loc = (resp.headers.get("location") or "").strip()
                if not loc:
                    raise HTTPException(status_code=400, detail="redirect location missing")
                nxt = urljoin(str(resp.url), loc)
                current = await validate_url_for_ingest(nxt)
                hops += 1
                continue

            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"failed to fetch url (status={resp.status_code})")

            content_type = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()

            chunks: List[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                size += len(chunk)
                if max_bytes > 0 and size > max_bytes:
                    break
                chunks.append(chunk)
            body = b"".join(chunks)
            text = body.decode("utf-8", "ignore")
            return text, str(resp.url), content_type


def _extract_links_from_html(html_text: str, *, base_url: str) -> List[str]:
    try:
        from lxml import html as lxml_html  # noqa: WPS433
    except Exception:
        return []

    raw = (html_text or "").strip()
    if not raw:
        return []

    try:
        doc = lxml_html.fromstring(raw)
    except Exception:
        return []

    try:
        doc.make_links_absolute(base_url, resolve_base_href=True)
    except Exception:
        pass

    out: List[str] = []
    for _el, _attr, link, _pos in doc.iterlinks():
        if not link:
            continue
        s = str(link).strip()
        if not s:
            continue
        lowered = s.lower()
        if lowered.startswith(_DISALLOWED_SCHEMES):
            continue
        # Defensive join in case make_links_absolute didn't run.
        out.append(_normalize_url(urljoin(base_url, s)))
    return out


@dataclass(frozen=True)
class WebCrawlResult:
    urls: List[str]
    visited: int
    queued: int
    errors: List[Dict[str, Any]]


async def crawl_site(
    *,
    start_urls: List[str],
    max_pages: int,
    max_depth: int,
    same_host_only: bool,
    include_patterns: List[str],
    exclude_patterns: List[str],
    headers: Optional[Dict[str, str]] = None,
    user_agent: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    max_bytes: Optional[int] = None,
    follow_redirects: Optional[bool] = None,
) -> WebCrawlResult:
    """
    Crawl a website starting from one or more seed URLs.

    Returns a list of normalized URLs to ingest (deduped).
    """
    seeds = [str(u or "").strip() for u in (start_urls or []) if str(u or "").strip()]
    if not seeds:
        return WebCrawlResult(urls=[], visited=0, queued=0, errors=[])

    include_re = _compile_patterns(include_patterns)
    exclude_re = _compile_patterns(exclude_patterns)

    allowed_netlocs: set[str] = set()
    for s in seeds:
        try:
            allowed_netlocs.add(urlsplit(s).netloc.lower())
        except Exception:
            continue

    # Headers for fetch.
    h: Dict[str, str] = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    ua = (user_agent or "").strip() or "MimirQ/1.0 (+web-crawl)"
    h["User-Agent"] = ua
    if headers:
        for k, v in headers.items():
            key = str(k or "").strip()
            if not key:
                continue
            val = str(v or "")
            if len(val) > 20_000:
                val = val[:20_000]
            h[key] = val

    timeout_eff = float(timeout_sec if timeout_sec is not None else getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0) or 30.0)
    max_bytes_eff = int(max_bytes if max_bytes is not None else getattr(settings, "URL_INGEST_MAX_BYTES", 0) or 0)
    if max_bytes_eff <= 0:
        max_bytes_eff = int(getattr(settings, "MAX_FILE_SIZE", 0) or 50_000_000)
    follow_eff = bool(follow_redirects) if follow_redirects is not None else bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False))

    q: deque[Tuple[str, int]] = deque()
    for u in seeds:
        q.append((_normalize_url(u), 0))

    visited: set[str] = set()
    out: List[str] = []
    errors: List[Dict[str, Any]] = []

    while q and len(out) < int(max_pages):
        url, depth = q.popleft()
        url = _normalize_url(url)
        if not url or url in visited:
            continue
        visited.add(url)

        if include_re and not _match_any(url, include_re):
            continue
        if exclude_re and _match_any(url, exclude_re):
            continue

        if same_host_only and allowed_netlocs:
            try:
                if urlsplit(url).netloc.lower() not in allowed_netlocs:
                    continue
            except Exception:
                continue

        # SSRF validation per URL.
        try:
            safe_url = await validate_url_for_ingest(url)
        except HTTPException as exc:
            if len(errors) < 20:
                errors.append({"url": url, "error": str(getattr(exc, "detail", "") or "invalid_url")[:200]})
            continue
        except Exception as exc:
            if len(errors) < 20:
                errors.append({"url": url, "error": str(exc)[:200]})
            continue

        out.append(safe_url)

        if depth >= int(max_depth):
            continue

        # Fetch and discover links (HTML only).
        try:
            text, final_url, content_type = await _fetch_page_text(
                safe_url,
                headers=h,
                timeout_sec=timeout_eff,
                max_bytes=max_bytes_eff,
                follow_redirects=follow_eff,
            )
        except Exception as exc:
            if len(errors) < 20:
                errors.append({"url": safe_url, "error": str(exc)[:200]})
            continue

        if "html" not in (content_type or ""):
            continue

        for link in _extract_links_from_html(text, base_url=final_url):
            if not link:
                continue
            if link in visited:
                continue
            if include_re and not _match_any(link, include_re):
                continue
            if exclude_re and _match_any(link, exclude_re):
                continue
            if same_host_only and allowed_netlocs:
                try:
                    if urlsplit(link).netloc.lower() not in allowed_netlocs:
                        continue
                except Exception:
                    continue
            q.append((link, depth + 1))

    return WebCrawlResult(urls=out, visited=len(visited), queued=len(q), errors=errors)


__all__ = ["WebCrawlResult", "crawl_site"]

