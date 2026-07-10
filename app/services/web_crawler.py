"""
Website crawler for connector runs (site-level ingestion).

Design goals:
- Keep dependencies light (lxml is already a transitive dependency via readability-lxml).
- Best-effort SSRF safety by reusing validate_url_for_ingest for each visited URL and each redirect hop.
- Allow authenticated crawling via headers (cookie/bearer/basic), without storing plaintext secrets.
"""


import contextlib
import hashlib
import re
from collections import deque
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, cast
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from defusedxml import ElementTree as DefusedET
from fastapi import HTTPException

from app.api.utils.url_ingest import validate_url_for_ingest
from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.core.http_client import get_http_client_pool
from app.core.optional_deps import optional_import
from app.rag.core.logging import get_logger
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup

_DISALLOWED_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "file:")
logger = get_logger("services.web_crawler")


def _build_page_sync_token(*, url: str, text: str | None, content_type: str | None) -> str:
    """
    Best-effort content fingerprint used by connector incremental manifests.
    """
    ct = str(content_type or "").split(";", 1)[0].strip().lower()
    body = str(text or "")
    if body:
        digest = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()
        if ct:
            return f"content_type:{ct}|body_sha256:{digest}"
        return f"body_sha256:{digest}"
    return f"url_sha256:{hashlib.sha256(str(url or '').encode('utf-8', 'ignore')).hexdigest()}"


def _extract_sitemap_candidates_from_robots(text: str, *, base_url: str) -> list[str]:
    """
    Extract "Sitemap:" entries from robots.txt (best-effort).
    """
    if not text:
        return []
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.lower().startswith("sitemap:"):
            continue
        url = line.split(":", 1)[1].strip()
        if not url:
            continue
        try:
            out.append(_normalize_url(urljoin(base_url, url)))
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
    # Dedup while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    return deduped


def _parse_sitemap_xml(xml_text: str) -> tuple[list[str], list[str]]:
    """
    Parse sitemap XML, returning (page_urls, sitemap_urls) lists.

    Supports both <urlset> and <sitemapindex>.
    """
    raw = (xml_text or "").strip()
    if not raw:
        return [], []

    # Avoid huge CPU work on very large sitemaps.
    raw = raw[:5_000_000]

    try:
        root = DefusedET.fromstring(raw)
    except Exception:
        return [], []

    def tag_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    root_name = tag_name(str(getattr(root, "tag", "") or "")).lower()

    page_urls: list[str] = []
    sitemap_urls: list[str] = []

    if root_name.endswith("sitemapindex"):
        for child in root:
            if tag_name(str(getattr(child, "tag", "") or "")).lower() != "sitemap":
                continue
            loc_el = None
            for el in child:
                if tag_name(str(getattr(el, "tag", "") or "")).lower() == "loc":
                    loc_el = el
                    break
            loc = (loc_el.text or "").strip() if loc_el is not None else ""
            if loc:
                sitemap_urls.append(loc)
        return page_urls, sitemap_urls

    if root_name.endswith("urlset"):
        for child in root:
            if tag_name(str(getattr(child, "tag", "") or "")).lower() != "url":
                continue
            loc_el = None
            for el in child:
                if tag_name(str(getattr(el, "tag", "") or "")).lower() == "loc":
                    loc_el = el
                    break
            loc = (loc_el.text or "").strip() if loc_el is not None else ""
            if loc:
                page_urls.append(loc)
        return page_urls, sitemap_urls

    # Fallback: extract any <loc> to page_urls (best-effort).
    for el in root.iter():
        if tag_name(str(getattr(el, "tag", "") or "")).lower() != "loc":
            continue
        loc = (el.text or "").strip()
        if loc:
            page_urls.append(loc)
    return page_urls, sitemap_urls


class _RobotsCache:
    """
    Best-effort robots.txt policy cache keyed by netloc.

    - Fetch failures are treated as "allow all" (cache None).
    - Uses validate_url_for_ingest per hop to preserve SSRF defenses.
    """

    def __init__(self) -> None:
        self._cache: dict[str, RobotFileParser | None] = {}
        self._raw: dict[str, str] = {}

    def get_raw(self, netloc: str) -> str | None:
        return self._raw.get(netloc)

    async def _load(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout_sec: float,
        follow_redirects: bool,
    ) -> RobotFileParser | None:
        try:
            parsed = urlsplit(base_url)
        except Exception:
            return None
        scheme = parsed.scheme or "https"
        netloc = (parsed.netloc or "").strip().lower()
        if not netloc:
            return None

        if netloc in self._cache:
            return self._cache[netloc]

        robots_url = urlunsplit((scheme, netloc, "/robots.txt", "", ""))
        try:
            safe = await validate_url_for_ingest(robots_url)
        except Exception:
            self._cache[netloc] = None
            return None

        try:
            text, final_url, content_type = await _fetch_page_text(
                safe,
                headers={**headers, "Accept": "text/plain,*/*;q=0.1"},
                timeout_sec=timeout_sec,
                max_bytes=250_000,
                follow_redirects=follow_redirects,
            )
        except Exception:
            self._cache[netloc] = None
            return None

        if content_type and "text" not in content_type:
            # robots should be text; treat unexpected content types as allow-all.
            self._cache[netloc] = None
            return None

        rp = RobotFileParser()
        rp.set_url(final_url or robots_url)
        with contextlib.suppress(Exception):
            rp.parse((text or "").splitlines())

        self._cache[netloc] = rp
        self._raw[netloc] = text or ""
        return rp

    async def can_fetch(
        self,
        url: str,
        *,
        user_agent: str,
        headers: dict[str, str],
        timeout_sec: float,
        follow_redirects: bool,
    ) -> bool:
        try:
            parsed = urlsplit(url)
        except Exception:
            return True
        base = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))

        rp = await self._load(
            base_url=base,
            headers=headers,
            timeout_sec=timeout_sec,
            follow_redirects=follow_redirects,
        )
        if rp is None:
            return True
        with contextlib.suppress(Exception):
            return bool(rp.can_fetch(user_agent, url))
        return True


@lru_cache(maxsize=1)
def _get_lxml_html():  # noqa: ANN201
    # Imported lazily and cached to avoid repeated warnings during large crawls.
    return optional_import("lxml.html", feature="web_crawl_link_extraction", pip_name="lxml")


def _normalize_url(raw: str) -> str:
    """
    Normalize URL for crawling dedup.

    - Strip common tracking params (utm_*, gclid, fbclid, ...).
    - Drop fragment (anchors).
    - Keep query (after tracking stripping).
    """
    return normalize_url_for_dedup(str(raw or "").strip())


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for raw in patterns or []:
        pat = str(raw or "").strip()
        if not pat:
            continue
        try:
            compiled.append(re.compile(pat, flags=re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"invalid url pattern: {str(exc)[:120]}") from exc
    return compiled


def _match_any(url: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(url) for p in patterns)


async def _fetch_page_text(
    url: str,
    *,
    headers: dict[str, str],
    timeout_sec: float,
    max_bytes: int,
    follow_redirects: bool,
) -> tuple[str, str, str]:
    """
    Fetch a URL as text (best-effort), returning (text, final_url, content_type).

    Redirect handling is explicit to preserve SSRF checks per hop.
    """
    pool = get_http_client_pool()
    # Security/compliance: do not propagate internal tenant/user headers to crawled websites.
    client = await pool.get_external_client()

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

            chunks: list[bytes] = []
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


def _extract_links_from_html(html_text: str, *, base_url: str) -> tuple[list[str], dict[str, Any] | None]:
    lxml_html = _get_lxml_html()
    if lxml_html is None:
        return (
            [],
            {
                "level": "warning",
                "feature": "web_crawl_link_extraction",
                "dependency": "lxml",
                "reason": "dependency_missing",
                "remediation": "pip install lxml",
            },
        )

    raw = (html_text or "").strip()
    if not raw:
        return [], None

    try:
        doc = lxml_html.fromstring(raw)
    except Exception:
        return [], None

    try:
        doc.make_links_absolute(base_url, resolve_base_href=True)
    except Exception as exc:
        logger.debug("Ignoring web crawl link absolute rewrite failure: %s", exc)

    out: list[str] = []
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
    return out, None


@dataclass(frozen=True)
class WebCrawlResult:
    urls: list[str]
    visited: int
    queued: int
    errors: list[dict[str, Any]]
    sync_tokens: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WebCrawlOptions:
    start_urls: list[str] = field(default_factory=list)
    max_pages: int = 0
    max_depth: int = 0
    same_host_only: bool = True
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    use_sitemaps: bool = False
    sitemap_urls: list[str] | None = None
    respect_robots: bool = False
    dedup_canonical: bool = True
    headers: dict[str, str] | None = None
    user_agent: str | None = None
    timeout_sec: float | None = None
    max_bytes: int | None = None
    follow_redirects: bool | None = None


def _resolve_web_crawl_options(
    *,
    options: WebCrawlOptions | None,
    legacy_overrides: dict[str, Any],
) -> WebCrawlOptions:
    if options is None:
        return WebCrawlOptions(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(WebCrawlOptions, replace(options, **legacy_overrides))


async def crawl_site(
    *,
    options: WebCrawlOptions | None = None,
    **legacy_overrides: Any,
) -> WebCrawlResult:
    """
    Crawl a website starting from one or more seed URLs.

    Returns a list of normalized URLs to ingest (deduped).
    """
    crawl_options = _resolve_web_crawl_options(options=options, legacy_overrides=legacy_overrides)
    start_urls = crawl_options.start_urls
    max_pages = crawl_options.max_pages
    max_depth = crawl_options.max_depth
    same_host_only = crawl_options.same_host_only
    include_patterns = crawl_options.include_patterns
    exclude_patterns = crawl_options.exclude_patterns
    use_sitemaps = crawl_options.use_sitemaps
    sitemap_urls = crawl_options.sitemap_urls
    respect_robots = crawl_options.respect_robots
    dedup_canonical = crawl_options.dedup_canonical
    headers = crawl_options.headers
    user_agent = crawl_options.user_agent
    timeout_sec = crawl_options.timeout_sec
    max_bytes = crawl_options.max_bytes
    follow_redirects = crawl_options.follow_redirects

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
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue

    # Headers for fetch.
    h: dict[str, str] = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
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

    robots_cache: _RobotsCache | None = _RobotsCache() if respect_robots else None

    # Optional: sitemap-first discovery mode (best-effort).
    #
    # We intentionally do NOT fetch every discovered page here; the connector ingestion stage
    # will fetch each URL anyway. The crawler's job is to produce a bounded URL list.
    if use_sitemaps:
        sitemap_seed_urls: list[str] = []
        raw_sitemap_urls = sitemap_urls if isinstance(sitemap_urls, list) else []
        for u in raw_sitemap_urls:
            s = str(u or "").strip()
            if s:
                sitemap_seed_urls.append(s)

        # Infer {scheme}://{host}/sitemap.xml for each start URL host as a fallback.
        for s in seeds:
            try:
                parsed = urlsplit(s)
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue
            if not parsed.scheme or not parsed.netloc:
                continue
            sitemap_seed_urls.append(urlunsplit((parsed.scheme, parsed.netloc, "/sitemap.xml", "", "")))

        # Dedup sitemap urls.
        sitemap_seen: set[str] = set()
        sitemap_queue: deque[str] = deque()
        for u in sitemap_seed_urls:
            nu = _normalize_url(u)
            if not nu or nu in sitemap_seen:
                continue
            sitemap_seen.add(nu)
            sitemap_queue.append(nu)

        discovered_pages: list[str] = []
        sitemap_errors: list[dict[str, Any]] = []

        # Attempt to pull sitemap URLs from robots.txt (best-effort) to cover common setups.
        if robots_cache is not None:
            for s in seeds:
                try:
                    parsed = urlsplit(s)
                except Exception:
                    get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                    continue
                base = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
                await robots_cache._load(base_url=base, headers=h, timeout_sec=timeout_eff, follow_redirects=follow_eff)
                raw_txt = robots_cache.get_raw((parsed.netloc or "").strip().lower()) or ""
                if raw_txt:
                    sitemap_from_robots = _extract_sitemap_candidates_from_robots(raw_txt, base_url=base)
                    for u in sitemap_from_robots:
                        nu = _normalize_url(u)
                        if not nu or nu in sitemap_seen:
                            continue
                        sitemap_seen.add(nu)
                        sitemap_queue.append(nu)

        sitemap_hops = 0
        while sitemap_queue and len(discovered_pages) < int(max_pages):
            sitemap_hops += 1
            if sitemap_hops > 40:
                break
            sitemap_url = sitemap_queue.popleft()
            try:
                safe = await validate_url_for_ingest(sitemap_url)
            except Exception as exc:
                if len(sitemap_errors) < 20:
                    sitemap_errors.append({"url": sitemap_url, "error": str(getattr(exc, "detail", exc))[:200]})
                continue

            try:
                xml_text, final_url, _ct = await _fetch_page_text(
                    safe,
                    headers={**h, "Accept": "application/xml,text/xml,application/xhtml+xml;q=0.9,*/*;q=0.1"},
                    timeout_sec=timeout_eff,
                    max_bytes=max(1_000_000, min(max_bytes_eff, 10_000_000)),
                    follow_redirects=follow_eff,
                )
            except Exception as exc:
                if len(sitemap_errors) < 20:
                    sitemap_errors.append({"url": safe, "error": str(exc)[:200]})
                continue

            base_url = final_url or safe
            pages, nested = _parse_sitemap_xml(xml_text)

            for raw_page in pages:
                if len(discovered_pages) >= int(max_pages):
                    break
                try:
                    candidate = _normalize_url(urljoin(base_url, str(raw_page or "").strip()))
                except Exception:
                    get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                    continue
                if not candidate:
                    continue
                if include_re and not _match_any(candidate, include_re):
                    continue
                if exclude_re and _match_any(candidate, exclude_re):
                    continue
                if same_host_only and allowed_netlocs:
                    with contextlib.suppress(Exception):
                        if urlsplit(candidate).netloc.lower() not in allowed_netlocs:
                            continue
                if robots_cache is not None:
                    allowed = await robots_cache.can_fetch(
                        candidate,
                        user_agent=ua,
                        headers=h,
                        timeout_sec=timeout_eff,
                        follow_redirects=follow_eff,
                    )
                    if not allowed:
                        continue
                discovered_pages.append(candidate)

            for raw_child in nested:
                child = str(raw_child or "").strip()
                if not child:
                    continue
                try:
                    child = _normalize_url(urljoin(base_url, child))
                except Exception:
                    get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                    continue
                if not child or child in sitemap_seen:
                    continue
                sitemap_seen.add(child)
                sitemap_queue.append(child)

        # If we found any sitemap pages, return early (bounded).
        if discovered_pages:
            safe_out: list[str] = []
            for u in discovered_pages[: int(max_pages)]:
                try:
                    safe_out.append(await validate_url_for_ingest(u))
                except Exception:
                    get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                    continue
            return WebCrawlResult(urls=safe_out, visited=0, queued=0, errors=sitemap_errors)

    q: deque[tuple[str, int]] = deque()
    for u in seeds:
        q.append((_normalize_url(u), 0))

    visited: set[str] = set()
    out: list[str] = []
    out_keys: set[str] = set()
    sync_tokens: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    degraded_seen: set[tuple[str, str]] = set()

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
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
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

        # Optional robots.txt gate (best-effort).
        if robots_cache is not None:
            allowed = await robots_cache.can_fetch(
                safe_url,
                user_agent=ua,
                headers=h,
                timeout_sec=timeout_eff,
                follow_redirects=follow_eff,
            )
            if not allowed:
                continue

        # Fetch when needed: link discovery and/or canonical dedup.
        text = ""
        final_url = safe_url
        content_type = ""
        should_fetch = bool(depth < int(max_depth)) or bool(dedup_canonical)
        if should_fetch:
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
                # Fall back to ingesting the URL even if fetch/link discovery failed.

        canonical_url = None
        if dedup_canonical and text and "html" in (content_type or ""):
            canonical_url = extract_canonical_url(text, base_url=final_url)

        out_url = canonical_url or safe_url
        out_key = _normalize_url(out_url)
        if out_key and out_key not in out_keys:
            out_keys.add(out_key)
            out.append(out_url)
            sync_tokens[out_url] = _build_page_sync_token(
                url=out_url,
                text=(text or None),
                content_type=(content_type or None),
            )

        if depth >= int(max_depth):
            continue

        if not text or "html" not in (content_type or ""):
            continue

        links, degraded = _extract_links_from_html(text, base_url=final_url)
        if degraded is not None:
            key = (str(degraded.get("feature") or ""), str(degraded.get("dependency") or ""))
            if key not in degraded_seen:
                degraded_seen.add(key)
                logger.warning(
                    "Web crawl degraded: feature=%s dependency=%s reason=%s remediation=%s",
                    str(degraded.get("feature") or "unknown"),
                    str(degraded.get("dependency") or "unknown"),
                    str(degraded.get("reason") or "unknown"),
                    str(degraded.get("remediation") or ""),
                )
                if len(errors) < 20:
                    errors.append({"url": safe_url, **degraded})

        for link in links:
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
                    get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                    continue
            if robots_cache is not None:
                allowed = await robots_cache.can_fetch(
                    link,
                    user_agent=ua,
                    headers=h,
                    timeout_sec=timeout_eff,
                    follow_redirects=follow_eff,
                )
                if not allowed:
                    continue
            q.append((link, depth + 1))

    return WebCrawlResult(urls=out, visited=len(visited), queued=len(q), errors=errors, sync_tokens=sync_tokens)


__all__ = ["WebCrawlOptions", "WebCrawlResult", "crawl_site"]
