
import hashlib
import re
from typing import Any

from app.models.connector import ConnectorRun
from app.services.connector_sync_state import get_resume_cursor, normalize_source_manifest, slice_items_from_cursor

URL_SHA256_PREFIX = "url_sha256:"


def _web_crawl_content_fingerprint(
    *,
    url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    body_sha256: str | None = None,
    crawl_sync_token: str | None = None,
) -> str:
    token = str(crawl_sync_token or "").strip()
    if token:
        return token[:1000]

    parts: list[str] = []
    etag_s = str(etag or "").strip()
    if etag_s:
        parts.append(f"etag:{etag_s[:500]}")
    lm_s = str(last_modified or "").strip()
    if lm_s:
        parts.append(f"last_modified:{lm_s[:100]}")
    body_s = str(body_sha256 or "").strip().lower()
    if body_s and re.fullmatch(r"[a-f0-9]{64}", body_s):
        parts.append(f"body_sha256:{body_s}")
    if parts:
        return "|".join(parts)

    return f"{URL_SHA256_PREFIX}{hashlib.sha256(str(url or '').encode('utf-8', 'ignore')).hexdigest()}"


def _web_crawl_token_is_content_aware(token: str | None) -> bool:
    raw = str(token or "").strip()
    if not raw:
        return False
    markers = ("etag:", "last_modified:", "body_sha256:", URL_SHA256_PREFIX, "content_type:")
    return any(marker in raw for marker in markers)


def _web_crawl_manifest_token_changed(*, existing_token: str | None, discovered_token: str | None) -> bool:
    existing = str(existing_token or "").strip()
    discovered = str(discovered_token or "").strip()
    if not existing:
        return True
    if not discovered:
        return False
    if existing == discovered:
        return False
    if not _web_crawl_token_is_content_aware(existing):
        return False
    if discovered.startswith(URL_SHA256_PREFIX) and not existing.startswith(URL_SHA256_PREFIX):
        return False
    return True


def _web_crawl_extract_token_part(token: str | None, *, key: str) -> str | None:
    raw = str(token or "").strip()
    key_norm = str(key or "").strip()
    if not raw or not key_norm:
        return None
    pat = re.compile(rf"(?:^|\|){re.escape(key_norm)}:([^|]+)")
    match = pat.search(raw)
    if not match:
        return None
    out = str(match.group(1) or "").strip()
    return out or None


def _web_crawl_build_doc_sync_token(*, source_url: str, doc: Any, crawl_token: str | None = None) -> str:
    meta = dict(getattr(doc, "doc_metadata", None) or {})
    etag = str(meta.get("source_etag") or "").strip() or None
    last_modified = str(meta.get("source_last_modified_raw") or meta.get("source_last_modified_at") or "").strip() or None
    body_sha = str(meta.get("file_sha256") or "").strip().lower() or None
    if not body_sha:
        body_sha = _web_crawl_extract_token_part(crawl_token, key="body_sha256")

    token = _web_crawl_content_fingerprint(
        url=source_url,
        etag=etag,
        last_modified=last_modified,
        body_sha256=body_sha,
    )

    if token.startswith(URL_SHA256_PREFIX) and _web_crawl_token_is_content_aware(crawl_token):
        token = str(crawl_token or "").strip() or token

    ct = _web_crawl_extract_token_part(crawl_token, key="content_type")
    if ct and "content_type:" not in token:
        token = f"content_type:{ct}|{token}"

    return token


def _web_crawl_source_manifest(urls: list[str], *, sync_tokens: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    token_map = sync_tokens if isinstance(sync_tokens, dict) else {}
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url or url in out:
            continue
        out[url] = _web_crawl_content_fingerprint(
            url=url,
            crawl_sync_token=str(token_map.get(url) or "").strip() or None,
        )
    return out


def _build_web_crawl_execution_plan(
    *,
    run_stats: dict[str, Any],
    state: dict[str, Any],
    crawl_urls: list[str],
    crawl_sync_tokens: dict[str, str],
) -> dict[str, Any]:
    existing_manifest = normalize_source_manifest(state.get("source_manifest"))
    discovered_manifest = _web_crawl_source_manifest(
        [str(url or "").strip() for url in crawl_urls or [] if str(url or "").strip()],
        sync_tokens={str(key): str(value) for key, value in crawl_sync_tokens.items()},
    )
    discovered_urls = list(discovered_manifest.keys())
    resume_cursor_raw = get_resume_cursor(state)
    is_resume_run = bool((run_stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
    mode = "incremental" if existing_manifest else "full"
    delta_urls = [
        url
        for url in discovered_urls
        if (
            url not in existing_manifest
            or _web_crawl_manifest_token_changed(
                existing_token=existing_manifest.get(url),
                discovered_token=discovered_manifest.get(url),
            )
        )
    ]
    removed_urls = sorted(set(existing_manifest) - set(discovered_manifest)) if mode == "incremental" else []
    resume_cursor = resume_cursor_raw if (is_resume_run and mode == "full") else 0
    urls_to_process, cursor_in = slice_items_from_cursor(delta_urls, cursor=resume_cursor)
    source_manifest_state = {
        url: str(discovered_manifest.get(url) or token)
        for url, token in existing_manifest.items()
        if url in discovered_manifest
    }
    skipped_unchanged = max(0, int(len(discovered_urls) - len(delta_urls)))
    processed_visible = skipped_unchanged + cursor_in
    return {
        "mode": mode,
        "discovered_manifest": discovered_manifest,
        "discovered_urls": discovered_urls,
        "delta_urls": delta_urls,
        "removed_urls": removed_urls,
        "crawl_urls": urls_to_process,
        "cursor_in": int(cursor_in),
        "skipped_unchanged": int(skipped_unchanged),
        "processed_visible": int(processed_visible),
        "source_manifest_state": source_manifest_state,
        "resumed_from_state": bool(is_resume_run and ((mode == "incremental") or cursor_in > 0)),
    }


def _initialize_web_crawl_run_stats(*, run: ConnectorRun, crawl: Any, plan: dict[str, Any]) -> dict[str, Any]:
    discovered_urls = list(plan.get("discovered_urls") or [])
    delta_urls = list(plan.get("delta_urls") or [])
    removed_urls = list(plan.get("removed_urls") or [])
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "visited": int(getattr(crawl, "visited", 0) or 0),
            "queued": int(getattr(crawl, "queued", 0) or 0),
            "discovered": int(len(discovered_urls)),
            "total_urls": int(len(discovered_urls)),
            "delta_urls": int(len(delta_urls)),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_urls": int(plan.get("processed_visible") or 0),
            "cursor": int(plan.get("cursor_in") or 0),
            "created": 0,
            "failed": 0,
            "failed_urls": [],
            "errors": [],
            "error_groups": [],
            "cursor_in": int(plan.get("cursor_in") or 0),
            "resumed_from_state": bool(plan.get("resumed_from_state")),
            "removed_paths": int(len(removed_urls)),
            "removed_paths_reconciled": 0,
            "removed_documents_disabled": 0,
            "source_manifest": dict(plan.get("source_manifest_state") or {}),
        }
    )
    crawl_errors = getattr(crawl, "errors", None)
    if crawl_errors:
        stats["crawl_errors"] = list(crawl_errors)[:20]
    return stats
