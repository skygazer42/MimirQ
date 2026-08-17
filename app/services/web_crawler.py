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

from app.api.utils.url_ingest import _validated_fetch_target, _ValidatedFetchTarget, validate_url_for_ingest
from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.core.http_client import get_http_client_pool
from app.core.http_env import httpx_trust_env
from app.core.optional_deps import optional_import
from app.rag.core.logging import get_logger
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup

_DISALLOWED_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "file:")
_SENSITIVE_REQUEST_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
logger = get_logger("services.web_crawler")


def _request_origin(url: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(str(url or ""))
        scheme = str(parsed.scheme or "").lower()
        host = str(parsed.hostname or "").lower()
        if scheme not in {"http", "https"} or not host:
            return None
        port = parsed.port or (443 if scheme == "https" else 80)
        return scheme, host, port
    except (TypeError, ValueError):
        return None


def _without_sensitive_request_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _SENSITIVE_REQUEST_HEADERS}


def _headers_for_crawl_target(
    headers: dict[str, str],
    *,
    url: str,
    credential_origins: set[tuple[str, str, int | None]],
) -> dict[str, str]:
    if _request_origin(url) in credential_origins:
        return dict(headers)
    return _without_sensitive_request_headers(headers)


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


def _xml_tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _first_child_loc_text(node: Any) -> str:
    for child in node:
        if _xml_tag_name(str(getattr(child, "tag", "") or "")).lower() != "loc":
            continue
        return (child.text or "").strip()
    return ""


def _named_children_loc_values(root: Any, *, child_name: str) -> list[str]:
    values: list[str] = []
    for child in root:
        if _xml_tag_name(str(getattr(child, "tag", "") or "")).lower() != child_name:
            continue
        loc = _first_child_loc_text(child)
        if loc:
            values.append(loc)
    return values


def _iter_loc_values(root: Any) -> list[str]:
    values: list[str] = []
    for child in root.iter():
        if _xml_tag_name(str(getattr(child, "tag", "") or "")).lower() != "loc":
            continue
        loc = (child.text or "").strip()
        if loc:
            values.append(loc)
    return values


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

    root_name = _xml_tag_name(str(getattr(root, "tag", "") or "")).lower()
    if root_name.endswith("sitemapindex"):
        return [], _named_children_loc_values(root, child_name="sitemap")

    if root_name.endswith("urlset"):
        return _named_children_loc_values(root, child_name="url"), []

    # Fallback: extract any <loc> to page_urls (best-effort).
    return _iter_loc_values(root), []


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


def _max_redirects() -> int:
    max_redirects = int(getattr(settings, "URL_INGEST_MAX_REDIRECTS", 5) or 5)
    return max(0, min(max_redirects, 20))


async def _client_for_fetch_target(
    *,
    target: _ValidatedFetchTarget,
    pooled_client: httpx.AsyncClient,
    pinned_https_client: httpx.AsyncClient | None,
    pinned_https_host: str | None,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient | None, str | None]:
    if urlsplit(target.raw).scheme != "https":
        return pooled_client, pinned_https_client, pinned_https_host
    if pinned_https_client is not None and pinned_https_host == target.host_header:
        return pinned_https_client, pinned_https_client, pinned_https_host
    if pinned_https_client is not None:
        await pinned_https_client.aclose()
    pinned_https_client = httpx.AsyncClient(
        http2=False,
        follow_redirects=False,
        trust_env=httpx_trust_env(logger=logger),
    )
    return pinned_https_client, pinned_https_client, target.host_header


async def _resolve_redirect_hop(
    *,
    resp: Any,
    current_url: str,
    current_origin: tuple[str, str, int | None] | None,
    request_headers: dict[str, str],
    hops: int,
    follow_redirects: bool,
    max_redirects: int,
) -> tuple[_ValidatedFetchTarget, str, tuple[str, str, int | None] | None, dict[str, str], int]:
    if not follow_redirects:
        raise HTTPException(status_code=400, detail="redirects are not allowed")
    if hops >= max_redirects:
        raise HTTPException(status_code=400, detail="too many redirects")
    loc = (resp.headers.get("location") or "").strip()
    if not loc:
        raise HTTPException(status_code=400, detail="redirect location missing")
    next_target = await _validated_fetch_target(urljoin(current_url, loc))
    next_url = next_target.raw
    next_origin = _request_origin(next_url)
    if next_origin != current_origin:
        request_headers = _without_sensitive_request_headers(request_headers)
    return next_target, next_url, next_origin, request_headers, hops + 1


async def _read_response_text(resp: Any, *, max_bytes: int) -> str:
    chunks: list[bytes] = []
    size = 0
    async for chunk in resp.aiter_bytes():
        if not chunk:
            continue
        size += len(chunk)
        if max_bytes > 0 and size > max_bytes:
            raise HTTPException(status_code=413, detail="remote file too large")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "ignore")


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
    pooled_client = await pool.get_external_client()

    current_target = await _validated_fetch_target(url)
    current = current_target.raw
    request_headers = dict(headers)
    current_origin = _request_origin(current)
    hops = 0
    max_redirects = _max_redirects()
    pinned_https_client: httpx.AsyncClient | None = None
    pinned_https_host: str | None = None

    try:
        while True:
            target = current_target
            client, pinned_https_client, pinned_https_host = await _client_for_fetch_target(
                target=target,
                pooled_client=pooled_client,
                pinned_https_client=pinned_https_client,
                pinned_https_host=pinned_https_host,
            )
            pinned_headers = {**request_headers, "Host": target.host_header}
            async with client.stream(
                "GET",
                target.connect_url,
                headers=pinned_headers,
                timeout=httpx.Timeout(timeout_sec),
                follow_redirects=False,
                extensions={"sni_hostname": target.host},
            ) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    current_target, current, current_origin, request_headers, hops = await _resolve_redirect_hop(
                        resp=resp,
                        current_url=current,
                        current_origin=current_origin,
                        request_headers=request_headers,
                        hops=hops,
                        follow_redirects=follow_redirects,
                        max_redirects=max_redirects,
                    )
                    continue

                if resp.status_code >= 400:
                    raise HTTPException(status_code=400, detail=f"failed to fetch url (status={resp.status_code})")

                content_type = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                return await _read_response_text(resp, max_bytes=max_bytes), current, content_type
    finally:
        if pinned_https_client is not None:
            await pinned_https_client.aclose()


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


@dataclass(frozen=True)
class _CrawlRuntime:
    max_pages: int
    max_depth: int
    same_host_only: bool
    include_re: list[re.Pattern[str]]
    exclude_re: list[re.Pattern[str]]
    allowed_netlocs: set[str]
    credential_origins: set[tuple[str, str, int | None]]
    headers: dict[str, str]
    user_agent: str
    timeout_sec: float
    max_bytes: int
    follow_redirects: bool
    robots_cache: _RobotsCache | None


def _collect_seed_scope(seeds: list[str]) -> tuple[set[str], set[tuple[str, str, int | None]]]:
    allowed_netlocs: set[str] = set()
    credential_origins: set[tuple[str, str, int | None]] = set()
    for seed in seeds:
        try:
            allowed_netlocs.add(urlsplit(seed).netloc.lower())
            origin = _request_origin(seed)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        if origin is not None:
            credential_origins.add(origin)
    return allowed_netlocs, credential_origins


def _build_crawl_headers(headers: dict[str, str] | None, *, user_agent: str | None) -> tuple[dict[str, str], str]:
    merged: dict[str, str] = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    ua = (user_agent or "").strip() or "MimirQ/1.0 (+web-crawl)"
    merged["User-Agent"] = ua
    if headers:
        for key, value in headers.items():
            name = str(key or "").strip()
            if not name:
                continue
            merged[name] = str(value or "")[:20_000]
    return merged, ua


def _resolve_crawl_runtime(*, crawl_options: WebCrawlOptions, seeds: list[str]) -> _CrawlRuntime:
    allowed_netlocs, credential_origins = _collect_seed_scope(seeds)
    headers, user_agent = _build_crawl_headers(crawl_options.headers, user_agent=crawl_options.user_agent)
    max_bytes_eff = int(
        crawl_options.max_bytes
        if crawl_options.max_bytes is not None
        else getattr(settings, "URL_INGEST_MAX_BYTES", 0) or 0
    )
    if max_bytes_eff <= 0:
        max_bytes_eff = int(getattr(settings, "MAX_FILE_SIZE", 0) or 50_000_000)
    return _CrawlRuntime(
        max_pages=int(crawl_options.max_pages),
        max_depth=int(crawl_options.max_depth),
        same_host_only=bool(crawl_options.same_host_only),
        include_re=_compile_patterns(crawl_options.include_patterns),
        exclude_re=_compile_patterns(crawl_options.exclude_patterns),
        allowed_netlocs=allowed_netlocs,
        credential_origins=credential_origins,
        headers=headers,
        user_agent=user_agent,
        timeout_sec=float(
            crawl_options.timeout_sec
            if crawl_options.timeout_sec is not None
            else getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0) or 30.0
        ),
        max_bytes=max_bytes_eff,
        follow_redirects=(
            bool(crawl_options.follow_redirects)
            if crawl_options.follow_redirects is not None
            else bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False))
        ),
        robots_cache=_RobotsCache() if crawl_options.respect_robots else None,
    )


def _append_crawl_error(errors: list[dict[str, Any]], *, url: str, error: str) -> None:
    if len(errors) < 20:
        errors.append({"url": url, "error": error[:200]})


def _within_allowed_hosts(url: str, *, allowed_netlocs: set[str]) -> bool:
    with contextlib.suppress(Exception):
        return urlsplit(url).netloc.lower() in allowed_netlocs
    get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
    return False


def _url_passes_filters(url: str, *, runtime: _CrawlRuntime) -> bool:
    if runtime.include_re and not _match_any(url, runtime.include_re):
        return False
    if runtime.exclude_re and _match_any(url, runtime.exclude_re):
        return False
    if (
        runtime.same_host_only
        and runtime.allowed_netlocs
        and not _within_allowed_hosts(url, allowed_netlocs=runtime.allowed_netlocs)
    ):
        return False
    return True


async def _robots_allow_url(url: str, *, runtime: _CrawlRuntime) -> bool:
    if runtime.robots_cache is None:
        return True
    return await runtime.robots_cache.can_fetch(
        url,
        user_agent=runtime.user_agent,
        headers=_headers_for_crawl_target(
            runtime.headers,
            url=url,
            credential_origins=runtime.credential_origins,
        ),
        timeout_sec=runtime.timeout_sec,
        follow_redirects=runtime.follow_redirects,
    )


def _normalized_sitemap_seed_urls(*, seeds: list[str], sitemap_urls: list[str] | None) -> list[str]:
    sitemap_seed_urls: list[str] = [str(url or "").strip() for url in (sitemap_urls or []) if str(url or "").strip()]
    for seed in seeds:
        try:
            parsed = urlsplit(seed)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        if parsed.scheme and parsed.netloc:
            sitemap_seed_urls.append(urlunsplit((parsed.scheme, parsed.netloc, "/sitemap.xml", "", "")))
    return sitemap_seed_urls


def _enqueue_unique_urls(queue: deque[str], seen: set[str], urls: list[str]) -> None:
    for url in urls:
        normalized = _normalize_url(url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        queue.append(normalized)


async def _extend_sitemap_queue_from_robots(
    *,
    seeds: list[str],
    runtime: _CrawlRuntime,
    sitemap_queue: deque[str],
    sitemap_seen: set[str],
) -> None:
    if runtime.robots_cache is None:
        return
    for seed in seeds:
        try:
            parsed = urlsplit(seed)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        base = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        await runtime.robots_cache._load(
            base_url=base,
            headers=_headers_for_crawl_target(runtime.headers, url=base, credential_origins=runtime.credential_origins),
            timeout_sec=runtime.timeout_sec,
            follow_redirects=runtime.follow_redirects,
        )
        raw_txt = runtime.robots_cache.get_raw((parsed.netloc or "").strip().lower()) or ""
        _enqueue_unique_urls(
            sitemap_queue,
            sitemap_seen,
            _extract_sitemap_candidates_from_robots(raw_txt, base_url=base) if raw_txt else [],
        )


async def _fetch_sitemap_document(
    *,
    sitemap_url: str,
    runtime: _CrawlRuntime,
    errors: list[dict[str, Any]],
) -> tuple[str, str] | None:
    try:
        safe = await validate_url_for_ingest(sitemap_url)
    except Exception as exc:
        _append_crawl_error(errors, url=sitemap_url, error=str(getattr(exc, "detail", exc)))
        return None
    try:
        sitemap_headers = _headers_for_crawl_target(
            runtime.headers, url=safe, credential_origins=runtime.credential_origins
        )
        sitemap_headers["Accept"] = "application/xml,text/xml,application/xhtml+xml;q=0.9,*/*;q=0.1"
        xml_text, final_url, _ct = await _fetch_page_text(
            safe,
            headers=sitemap_headers,
            timeout_sec=runtime.timeout_sec,
            max_bytes=max(1_000_000, min(runtime.max_bytes, 10_000_000)),
            follow_redirects=runtime.follow_redirects,
        )
    except Exception as exc:
        _append_crawl_error(errors, url=safe, error=str(exc))
        return None
    return xml_text, final_url or safe


async def _discover_pages_from_sitemaps(
    *,
    seeds: list[str],
    runtime: _CrawlRuntime,
    sitemap_urls: list[str] | None,
) -> WebCrawlResult | None:
    sitemap_queue: deque[str] = deque()
    sitemap_seen: set[str] = set()
    _enqueue_unique_urls(
        sitemap_queue, sitemap_seen, _normalized_sitemap_seed_urls(seeds=seeds, sitemap_urls=sitemap_urls)
    )
    await _extend_sitemap_queue_from_robots(
        seeds=seeds, runtime=runtime, sitemap_queue=sitemap_queue, sitemap_seen=sitemap_seen
    )

    discovered_pages: list[str] = []
    errors: list[dict[str, Any]] = []
    sitemap_hops = 0
    while sitemap_queue and len(discovered_pages) < runtime.max_pages:
        sitemap_hops += 1
        if sitemap_hops > 40:
            break
        fetched = await _fetch_sitemap_document(
            sitemap_url=sitemap_queue.popleft(),
            runtime=runtime,
            errors=errors,
        )
        if fetched is None:
            continue
        xml_text, base_url = fetched
        page_urls, nested_sitemaps = _parse_sitemap_xml(xml_text)
        for raw_page in page_urls:
            if len(discovered_pages) >= runtime.max_pages:
                break
            with contextlib.suppress(Exception):
                candidate = _normalize_url(urljoin(base_url, str(raw_page or "").strip()))
                if (
                    candidate
                    and _url_passes_filters(candidate, runtime=runtime)
                    and await _robots_allow_url(candidate, runtime=runtime)
                ):
                    discovered_pages.append(candidate)
        _enqueue_unique_urls(
            sitemap_queue,
            sitemap_seen,
            [urljoin(base_url, str(child or "").strip()) for child in nested_sitemaps if str(child or "").strip()],
        )

    if not discovered_pages:
        return None
    safe_out: list[str] = []
    for url in discovered_pages[: runtime.max_pages]:
        with contextlib.suppress(Exception):
            safe_out.append(await validate_url_for_ingest(url))
    return WebCrawlResult(urls=safe_out, visited=0, queued=0, errors=errors)


async def _validated_crawl_url(url: str, *, errors: list[dict[str, Any]]) -> str | None:
    try:
        return await validate_url_for_ingest(url)
    except HTTPException as exc:
        _append_crawl_error(errors, url=url, error=str(getattr(exc, "detail", "") or "invalid_url"))
    except Exception as exc:
        _append_crawl_error(errors, url=url, error=str(exc))
    return None


def _record_crawled_url(
    *,
    out: list[str],
    out_keys: set[str],
    sync_tokens: dict[str, str],
    out_url: str,
    text: str,
    content_type: str,
) -> None:
    out_key = _normalize_url(out_url)
    if not out_key or out_key in out_keys:
        return
    out_keys.add(out_key)
    out.append(out_url)
    sync_tokens[out_url] = _build_page_sync_token(
        url=out_url,
        text=(text or None),
        content_type=(content_type or None),
    )


def _record_degraded_crawl(
    *,
    degraded: dict[str, Any] | None,
    degraded_seen: set[tuple[str, str]],
    errors: list[dict[str, Any]],
    safe_url: str,
) -> None:
    if degraded is None:
        return
    key = (str(degraded.get("feature") or ""), str(degraded.get("dependency") or ""))
    if key in degraded_seen:
        return
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


async def _crawl_page_queue(*, seeds: list[str], runtime: _CrawlRuntime, dedup_canonical: bool) -> WebCrawlResult:
    queue: deque[tuple[str, int]] = deque((_normalize_url(url), 0) for url in seeds)
    visited: set[str] = set()
    out: list[str] = []
    out_keys: set[str] = set()
    sync_tokens: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    degraded_seen: set[tuple[str, str]] = set()

    while queue and len(out) < runtime.max_pages:
        url, depth = queue.popleft()
        url = _normalize_url(url)
        if not url or url in visited:
            continue
        visited.add(url)
        if not _url_passes_filters(url, runtime=runtime):
            continue
        safe_url = await _validated_crawl_url(url, errors=errors)
        if safe_url is None or not await _robots_allow_url(safe_url, runtime=runtime):
            continue

        text = ""
        final_url = safe_url
        content_type = ""
        should_fetch = depth < runtime.max_depth or dedup_canonical
        if should_fetch:
            try:
                text, final_url, content_type = await _fetch_page_text(
                    safe_url,
                    headers=_headers_for_crawl_target(
                        runtime.headers, url=safe_url, credential_origins=runtime.credential_origins
                    ),
                    timeout_sec=runtime.timeout_sec,
                    max_bytes=runtime.max_bytes,
                    follow_redirects=runtime.follow_redirects,
                )
            except Exception as exc:
                _append_crawl_error(errors, url=safe_url, error=str(exc))

        canonical_url = (
            extract_canonical_url(text, base_url=final_url)
            if dedup_canonical and text and "html" in (content_type or "")
            else None
        )
        _record_crawled_url(
            out=out,
            out_keys=out_keys,
            sync_tokens=sync_tokens,
            out_url=canonical_url or safe_url,
            text=text,
            content_type=content_type,
        )

        if depth >= runtime.max_depth or not text or "html" not in (content_type or ""):
            continue
        links, degraded = _extract_links_from_html(text, base_url=final_url)
        _record_degraded_crawl(
            degraded=degraded,
            degraded_seen=degraded_seen,
            errors=errors,
            safe_url=safe_url,
        )
        for link in links:
            if (
                link
                and link not in visited
                and _url_passes_filters(link, runtime=runtime)
                and await _robots_allow_url(link, runtime=runtime)
            ):
                queue.append((link, depth + 1))

    return WebCrawlResult(urls=out, visited=len(visited), queued=len(queue), errors=errors, sync_tokens=sync_tokens)


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
    seeds = [str(url or "").strip() for url in (crawl_options.start_urls or []) if str(url or "").strip()]
    if not seeds:
        return WebCrawlResult(urls=[], visited=0, queued=0, errors=[])
    runtime = _resolve_crawl_runtime(crawl_options=crawl_options, seeds=seeds)
    if crawl_options.use_sitemaps:
        sitemap_result = await _discover_pages_from_sitemaps(
            seeds=seeds,
            runtime=runtime,
            sitemap_urls=crawl_options.sitemap_urls,
        )
        if sitemap_result is not None:
            return sitemap_result
    return await _crawl_page_queue(seeds=seeds, runtime=runtime, dedup_canonical=bool(crawl_options.dedup_canonical))


__all__ = ["WebCrawlOptions", "WebCrawlResult", "crawl_site"]
