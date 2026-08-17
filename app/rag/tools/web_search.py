from typing import Any

import httpx

from app.core.config import settings
from app.rag.core.http import httpx_trust_env

_DEFAULT_PROVIDER_ORDER = ("tavily", "serper", "brave")


def _safe_text(value: Any, *, max_len: int = 500) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _normalize_provider_order(value: list[str] | tuple[str, ...] | None) -> list[str]:
    raw = list(value or _DEFAULT_PROVIDER_ORDER)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        provider = str(item or "").strip().lower()
        if provider not in {"tavily", "serper", "brave"}:
            continue
        if provider in seen:
            continue
        seen.add(provider)
        out.append(provider)
    return out or list(_DEFAULT_PROVIDER_ORDER)


def _normalize_results(items: list[dict[str, Any]] | None, *, max_results: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = _safe_text(item.get("url"), max_len=1000)
        title = _safe_text(item.get("title"), max_len=240)
        snippet = _safe_text(item.get("snippet") or item.get("content") or item.get("description"), max_len=1200)
        source = _safe_text(item.get("source"), max_len=120)
        published_at = _safe_text(item.get("published_at") or item.get("date"), max_len=80)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        payload: dict[str, Any] = {
            "title": title or url,
            "url": url,
            "snippet": snippet or "",
            "source": source or "",
        }
        if published_at:
            payload["published_at"] = published_at
        out.append(payload)
        if len(out) >= max(1, int(max_results or 1)):
            break
    return out


async def _run_tavily_search(
    *,
    query: str,
    max_results: int,
    site_filter: list[str] | None = None,
    freshness: str | None = None,
    lang: str | None = None,
    region: str | None = None,
) -> list[dict[str, Any]]:
    api_key = str(getattr(settings, "TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("missing_tavily_api_key")
    payload: dict[str, Any] = {
        "query": str(query or ""),
        "max_results": int(max_results or 5),
    }
    if site_filter:
        payload["include_domains"] = list(site_filter)
    if freshness:
        payload["time_range"] = str(freshness)
    if lang:
        payload["search_lang"] = str(lang)
    if region:
        payload["region"] = str(region)
    async with httpx.AsyncClient(
        trust_env=httpx_trust_env(), timeout=float(getattr(settings, "WEB_SEARCH_TIMEOUT_SEC", 8.0) or 8.0)
    ) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()
    results = body.get("results") if isinstance(body, dict) else []
    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("content") or item.get("snippet"),
            "source": item.get("source") or "tavily",
            "published_at": item.get("published_date"),
        }
        for item in results
        if isinstance(item, dict)
    ]


async def _run_serper_search(
    *,
    query: str,
    max_results: int,
    site_filter: list[str] | None = None,
    freshness: str | None = None,
    lang: str | None = None,
    region: str | None = None,
) -> list[dict[str, Any]]:
    api_key = str(getattr(settings, "SERPER_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("missing_serper_api_key")
    query_text = str(query or "")
    if site_filter:
        for domain in site_filter:
            dom = str(domain or "").strip()
            if dom:
                query_text = f"{query_text} site:{dom}"
    payload: dict[str, Any] = {
        "q": query_text.strip(),
        "num": int(max_results or 5),
    }
    if freshness:
        payload["tbs"] = f"qdr:{freshness}"
    if lang:
        payload["hl"] = str(lang)
    if region:
        payload["gl"] = str(region)
    async with httpx.AsyncClient(
        trust_env=httpx_trust_env(), timeout=float(getattr(settings, "WEB_SEARCH_TIMEOUT_SEC", 8.0) or 8.0)
    ) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()
    results = body.get("organic") if isinstance(body, dict) else []
    return [
        {
            "title": item.get("title"),
            "url": item.get("link"),
            "snippet": item.get("snippet"),
            "source": item.get("source") or "serper",
            "published_at": item.get("date"),
        }
        for item in results
        if isinstance(item, dict)
    ]


async def _run_brave_search(
    *,
    query: str,
    max_results: int,
    site_filter: list[str] | None = None,
    freshness: str | None = None,
    lang: str | None = None,
    region: str | None = None,
) -> list[dict[str, Any]]:
    api_key = str(getattr(settings, "BRAVE_SEARCH_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("missing_brave_search_api_key")
    params: dict[str, Any] = {
        "q": str(query or ""),
        "count": int(max_results or 5),
    }
    if site_filter:
        params["site"] = ",".join([str(item).strip() for item in site_filter if str(item).strip()])
    if freshness:
        params["freshness"] = str(freshness)
    if lang:
        params["search_lang"] = str(lang)
    if region:
        params["country"] = str(region)
    async with httpx.AsyncClient(
        trust_env=httpx_trust_env(), timeout=float(getattr(settings, "WEB_SEARCH_TIMEOUT_SEC", 8.0) or 8.0)
    ) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key},
            params=params,
        )
        resp.raise_for_status()
        body = resp.json()
    results = ((body.get("web") or {}).get("results") if isinstance(body, dict) else []) or []
    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("description"),
            "source": item.get("profile", {}).get("name") if isinstance(item.get("profile"), dict) else "brave",
            "published_at": item.get("age"),
        }
        for item in results
        if isinstance(item, dict)
    ]


async def web_search(
    query: str,
    *,
    provider_order: list[str] | tuple[str, ...] | None = None,
    max_results: int | None = None,
    site_filter: list[str] | None = None,
    freshness: str | None = None,
    lang: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    providers = _normalize_provider_order(provider_order)
    limit = max(1, int(max_results or getattr(settings, "WEB_SEARCH_MAX_RESULTS", 5) or 5))
    tried: list[str] = []
    errors: dict[str, str] = {}

    provider_funcs = {
        "tavily": _run_tavily_search,
        "serper": _run_serper_search,
        "brave": _run_brave_search,
    }

    for provider in providers:
        tried.append(provider)
        fn = provider_funcs[provider]
        try:
            raw_results = await fn(
                query=str(query or ""),
                max_results=limit,
                site_filter=site_filter,
                freshness=freshness,
                lang=lang,
                region=region,
            )
            results = _normalize_results(raw_results, max_results=limit)
            return {
                "ok": True,
                "query": str(query or ""),
                "provider": provider,
                "providers_tried": tried,
                "fallback_used": len(tried) > 1,
                "total_results": len(results),
                "results": results,
                "errors": errors,
            }
        except Exception as exc:  # noqa: BLE001
            errors[provider] = str(exc)[:200]

    return {
        "ok": False,
        "query": str(query or ""),
        "provider": None,
        "providers_tried": tried,
        "fallback_used": len(tried) > 1,
        "total_results": 0,
        "results": [],
        "errors": errors,
    }


__all__ = ["web_search"]
