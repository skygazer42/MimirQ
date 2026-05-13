from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import HTTPException

from app.models.connector import ConnectorRun


def _safe_error_str(exc: Exception) -> str:
    msg = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    if not msg:
        msg = exc.__class__.__name__
    if len(msg) > 200:
        msg = msg[:200]
    return msg


def _connector_error_code_from_message(
    message: str,
    *,
    default: str,
    status_code: int | None = None,
) -> str:
    lowered = str(message or "").strip().lower()
    if "not allowed" in lowered or "private ip" in lowered or "ssrf" in lowered:
        return "ssrf"
    if "timeout" in lowered:
        return "timeout"
    if status_code == 413:
        return "too_large"
    if status_code == 400:
        return "bad_request"
    return default


def _classify_connector_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, HTTPException):
        status_code = getattr(exc, "status_code", 0)
        detail = str(getattr(exc, "detail", "") or "").strip()
        msg = (detail or f"HTTP {status_code}").replace("\r", " ").replace("\n", " ").strip()
        msg = msg[:200] if len(msg) > 200 else msg
        code = _connector_error_code_from_message(
            msg,
            default=f"http_{status_code}",
            status_code=status_code,
        )
        return code, msg

    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout", _safe_error_str(exc) or "timeout"

    msg = _safe_error_str(exc)
    return _connector_error_code_from_message(msg, default="error"), msg


def _append_unique_limited(
    items: list[str],
    value: str,
    *,
    limit: int | None = None,
) -> None:
    if not value or value in items:
        return
    if limit is not None and len(items) >= limit:
        return
    items.append(value)


def _stats_list(stats: dict, key: str) -> list[Any]:
    items = stats.get(key)
    return items if isinstance(items, list) else []


def _get_or_create_error_group(
    groups: list[Any],
    *,
    key: str,
    code: str,
    msg: str,
) -> dict[str, Any]:
    for item in groups:
        if isinstance(item, dict) and str(item.get("key") or "") == key:
            return item
    group = {"key": key, "code": code, "error": msg, "count": 0, "sample_urls": []}
    groups.append(group)
    return group


def _append_connector_error(stats: dict, *, url: str, exc: Exception) -> dict:
    code, msg = _classify_connector_error(exc)

    errs = _stats_list(stats, "errors")
    if len(errs) < 20:
        errs.append({"url": url, "code": code, "error": msg})
    stats["errors"] = errs

    failed_urls = _stats_list(stats, "failed_urls")
    _append_unique_limited(failed_urls, url)
    stats["failed_urls"] = failed_urls

    groups = _stats_list(stats, "error_groups")
    key = f"{code}:{msg}"
    group = _get_or_create_error_group(groups, key=key, code=code, msg=msg)
    group["count"] = int(group.get("count", 0) or 0) + 1
    sample_urls = group.get("sample_urls")
    if not isinstance(sample_urls, list):
        sample_urls = []
    _append_unique_limited(sample_urls, url, limit=3)
    group["sample_urls"] = sample_urls
    stats["error_groups"] = groups

    return stats


def _finalize_connector_stats(stats: dict) -> dict:
    groups = stats.get("error_groups")
    if isinstance(groups, list):
        def _count(it: object) -> int:
            if not isinstance(it, dict):
                return 0
            return int(it.get("count", 0) or 0)

        stats["error_groups"] = sorted(groups, key=_count, reverse=True)
    return stats


def _connector_run_completion_status(*, created: int, failed: int) -> str:
    if failed and created == 0:
        return "failed"
    return "completed"


def _connector_config_id_from_run(run: ConnectorRun) -> str | None:
    stats = dict(getattr(run, "stats", {}) or {})
    text = str(stats.get("config_id") or "").strip()
    return text or None
