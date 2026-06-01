from __future__ import annotations

import contextlib
import html
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.connector import ConnectorRun
from app.models.document import Document as DBDocument
from app.services.connector_sync_state import normalize_boundary_ids


def _zero_confluence_attachment_result(*, failed: int = 0, attachments_failed: int = 0) -> dict[str, Any]:
    return {
        "attachments_processed": 0,
        "attachments_created": 0,
        "attachments_failed": int(attachments_failed),
        "attachments_skipped": 0,
        "failed": int(failed),
        "created_doc_ids": [],
    }


def _resolve_connectors_helper(name: str):  # noqa: ANN202
    leader_module = globals().get("_leader_module")
    helper = getattr(leader_module, name, None) if leader_module is not None else None
    if callable(helper):
        return helper

    preferred_modules = (
        "app.api.v1.connectors",
        "test_support_connectors_module",
    )
    for module_name in preferred_modules:
        module = sys.modules.get(module_name)
        helper = getattr(module, name, None) if module is not None else None
        if callable(helper):
            return helper

    for module in reversed(tuple(sys.modules.values())):
        path = str(getattr(module, "__file__", "") or "")
        if not path.endswith("/app/api/v1/connectors.py"):
            continue
        helper = getattr(module, name, None)
        if callable(helper):
            return helper

    raise RuntimeError(f"connectors helper not available: {name}")


def _confluence_connector_base_query(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
):
    return db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.dataset_id == dataset_id,
        DBDocument.archived_at.is_(None),
        DBDocument.disabled_at.is_(None),
    )


def _confluence_page_metadata_query(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    base_url: str,
    space_key: str,
    page_id: str,
):
    return (
        _confluence_connector_base_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
        .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "confluence_space")  # type: ignore[attr-defined]
        .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
        .filter(DBDocument.doc_metadata["connector"]["space_key"].astext == space_key)  # type: ignore[attr-defined]
        .filter(DBDocument.doc_metadata["connector"]["page_id"].astext == page_id)  # type: ignore[attr-defined]
        .order_by(DBDocument.created_at.desc())
    )


def _confluence_recent_documents(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    max_docs_scan: int,
) -> list[Any]:
    max_docs_scan = max(0, int(max_docs_scan or 0)) or 5000
    return (
        _confluence_connector_base_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
        .order_by(DBDocument.created_at.desc())
        .limit(max_docs_scan)
        .all()
    )


def _confluence_doc_connector_metadata(doc: Any) -> dict[str, Any]:
    meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}
    conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
    return conn


def _confluence_doc_matches_page(
    doc: Any,
    *,
    base_url: str,
    space_key: str,
    page_id: str,
) -> bool:
    conn = _confluence_doc_connector_metadata(doc)
    return (
        str(conn.get("connector_id") or "") == "confluence_space"
        and str(conn.get("base_url") or "") == base_url
        and str(conn.get("space_key") or "") == space_key
        and str(conn.get("page_id") or "") == page_id
    )


def _apply_confluence_acl_to_doc(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    doc: Any,
    access: dict | None,
    acl_provenance: dict | None,
) -> None:
    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=doc,
        access=access,
        connector_id="confluence_space",
    )
    if not isinstance(acl_provenance, dict):
        return
    with contextlib.suppress(Exception):
        meta = dict(getattr(doc, "doc_metadata", None) or {})
        meta["acl_provenance"] = dict(acl_provenance)
        doc.doc_metadata = meta


def _delta_sync_confluence_documents_acl_by_page_id(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    space_key: str,
    page_id: str,
    requested_by: str,
    access: dict | None,
    acl_provenance: dict | None,
    max_docs_scan: int = 5000,
) -> int:
    """
    ACL delta sync for Confluence documents by `(base_url, space_key, page_id)`.

    This updates both the page doc and any attachment docs for the same page
    because attachments inherit the same effective access.
    """
    if dataset_id is None:
        return 0
    pid = str(page_id or "").strip()
    if not pid:
        return 0
    base_url = str(base_url or "").strip()
    space_key = str(space_key or "").strip()

    updated = 0
    try:
        q = _confluence_page_metadata_query(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            base_url=base_url,
            space_key=space_key,
            page_id=pid,
        )
        for doc in q.yield_per(200):
            _apply_confluence_acl_to_doc(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                acl_provenance=acl_provenance,
            )
            updated += 1
    except Exception:
        # Best-effort fallback: scan a bounded recent window and filter in Python.
        for doc in _confluence_recent_documents(db, tenant_id=tenant_id, dataset_id=dataset_id, max_docs_scan=max_docs_scan):
            if not _confluence_doc_matches_page(doc, base_url=base_url, space_key=space_key, page_id=pid):
                continue
            _apply_confluence_acl_to_doc(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                acl_provenance=acl_provenance,
            )
            updated += 1

    return int(updated)


def _confluence_api_base_url(base_url: str) -> str:
    """
    Normalize a Confluence base URL to its REST API base.

    Examples:
    - https://<site>.atlassian.net/wiki -> https://<site>.atlassian.net/wiki/rest/api
    - https://confluence.example.com -> https://confluence.example.com/rest/api
    - https://confluence.example.com/rest/api -> unchanged
    """
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/rest/api"):
        return base
    return f"{base}/rest/api"


async def _confluence_request(pool, method: str, url: str, **kwargs):  # noqa: ANN001, ANN201
    """
    Confluence API requests are always third-party outbound HTTP calls.

    Security/compliance: force the HTTP client pool to use its external profile
    (no internal tenant/user headers).
    """
    return await pool.request_with_retry(method, url, use_external_client=True, **kwargs)


def _confluence_join_webui(*, base: str, webui: str) -> str:
    """
    Join Confluence `_links.base` + `_links.webui` safely.

    Note: `webui` is often an absolute path (starts with "/") that must be appended
    to `base` *including* its context path (e.g. "/wiki"). Do NOT use urljoin().
    """
    b = str(base or "").strip().rstrip("/")
    w = str(webui or "").strip()
    if not b or not w:
        return ""
    if _resolve_connectors_helper("_is_http_or_https_url")(w):
        return w
    if not w.startswith("/"):
        w = "/" + w
    return b + w


def _confluence_extract_last_modified(page: dict) -> str | None:
    """
    Best-effort extraction of a stable modified timestamp for incremental cursoring.

    We prefer `version.when` (available with expand=version).
    """
    if not isinstance(page, dict):
        return None
    ver = page.get("version")
    if isinstance(ver, dict):
        when = ver.get("when")
        if isinstance(when, str) and when.strip():
            return when.strip()
    hist = page.get("history")
    if isinstance(hist, dict):
        last_upd = hist.get("lastUpdated")
        if isinstance(last_upd, dict):
            when = last_upd.get("when")
            if isinstance(when, str) and when.strip():
                return when.strip()
    return None


def _should_skip_timestamp_boundary_item(
    *,
    item_id: str,
    item_timestamp: str | None,
    cursor_timestamp: str | None,
    boundary_ids: set[str],
) -> bool:
    candidate_id = str(item_id or "").strip()
    candidate_ts = str(item_timestamp or "").strip()
    cursor_ts = str(cursor_timestamp or "").strip()
    if not candidate_id or not candidate_ts or not cursor_ts or not boundary_ids:
        return False
    return candidate_ts == cursor_ts and candidate_id in boundary_ids


def _advance_timestamp_boundary(
    *,
    last_timestamp: str | None,
    boundary_ids: set[str],
    item_timestamp: str | None,
    item_id: str,
) -> tuple[str | None, set[str]]:
    current_ts = str(item_timestamp or "").strip() or None
    current_id = str(item_id or "").strip()
    if not current_ts:
        return last_timestamp, set(boundary_ids or set())

    if current_ts != str(last_timestamp or "").strip():
        next_ids: set[str] = set()
        if current_id:
            next_ids.add(current_id)
        return current_ts, next_ids

    next_ids = set(boundary_ids or set())
    if current_id:
        next_ids.add(current_id)
    return current_ts, next_ids


def _confluence_group_principal_key(group_name: str) -> str:
    """
    Build a stable source principal key for a Confluence group name.

    Format (bounded to TenantGroup.external_id max_length=255):
      confluence:group:<group_name>
    """
    name = str(group_name or "").strip()
    if not name:
        return ""
    key = f"confluence:group:{name.lower()}"
    return key[:255]


def _confluence_restriction_group_names(group_obj: object, *, seen: set[str], max_groups: int) -> list[str]:
    if not isinstance(group_obj, dict):
        return []

    results = group_obj.get("results")
    group_items = results if isinstance(results, list) else []
    names: list[str] = []
    for group in group_items:
        if max_groups and len(seen) >= max_groups:
            break
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _confluence_restriction_user_count(user_obj: object) -> int:
    if not isinstance(user_obj, dict):
        return 0
    results = user_obj.get("results")
    return len(results) if isinstance(results, list) else 0


def _confluence_parse_read_restriction_groups(data: object, *, max_groups: int = 200) -> tuple[bool, list[str], int]:
    """
    Parse read restrictions for a page and extract allowed group names.

    Returns: (is_restricted, group_names, user_count)
    - is_restricted=False means "unrestricted" (no view restrictions)
    - is_restricted=True means "restricted" (some restrictions exist, even if we can't map them)
    """
    if not isinstance(data, dict):
        return True, [], 0

    results = data.get("results")
    items = results if isinstance(results, list) else []
    group_names: list[str] = []
    seen_g: set[str] = set()
    user_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        restrictions = item.get("restrictions")
        if not isinstance(restrictions, dict):
            continue

        group_names.extend(_confluence_restriction_group_names(restrictions.get("group"), seen=seen_g, max_groups=max_groups))
        user_count += _confluence_restriction_user_count(restrictions.get("user"))

        if max_groups and len(group_names) >= max_groups:
            break

    is_restricted = bool(group_names or user_count)
    return is_restricted, group_names, int(user_count)


def _confluence_ingest_method(cfg: dict) -> str:
    """
    Normalize Confluence page ingestion method.

    Backward compatibility:
    - If ingest_method is missing (older saved configs), default to api_view.
    """
    raw = cfg.get("ingest_method") if isinstance(cfg, dict) else None
    m = str(raw or "api_view").strip().lower()
    return m if m in {"api_view", "webui"} else "api_view"


def _confluence_attachment_limits(cfg: dict) -> tuple[bool, int, int]:
    """
    Parse and clamp Confluence attachments ingestion limits from a raw config dict.

    Notes:
    - The API layer validates config via Pydantic, but the runner is defensive and clamps here too.
    - 0 values fall back to defaults (same pattern as max_pages/page_size elsewhere).
    """
    raw = cfg if isinstance(cfg, dict) else {}
    include = bool(raw.get("include_attachments", False))

    per_page = int(raw.get("max_attachments_per_page") or 10)
    per_page = max(1, min(per_page, 50))

    total = int(raw.get("max_total_attachments") or 200)
    total = max(1, min(total, 2000))

    return include, per_page, total


def _confluence_attachment_download_url(*, base: str, download: str) -> str:
    """
    Build an absolute attachment download URL from Confluence REST `_links`.

    `download` is typically a path like "/download/attachments/...". We must preserve
    Confluence context paths (e.g. "/wiki"), so we reuse the same join logic as webui.
    """
    return _confluence_join_webui(base=str(base or ""), webui=str(download or ""))


def _confluence_effective_positive_limit(limit: int) -> int:
    lim = int(limit or 0)
    return lim if lim > 0 else 10_000


def _confluence_attachment_link_base(data: dict, *, fallback: str) -> str:
    links = data.get("_links") if isinstance(data.get("_links"), dict) else {}
    base = links.get("base") if isinstance(links.get("base"), str) and str(links.get("base") or "").strip() else fallback
    return str(base or "")


def _confluence_attachment_ref(raw: object, *, link_base: str) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None

    attachment_id = str(raw.get("id") or "").strip()
    if not attachment_id:
        return None

    filename = str(raw.get("title") or raw.get("filename") or raw.get("name") or "").strip()
    item_links = raw.get("_links") if isinstance(raw.get("_links"), dict) else {}
    download = str(item_links.get("download") or "").strip()
    download_url = _confluence_attachment_download_url(base=link_base, download=download)
    if not download_url:
        return None

    return {
        "attachment_id": attachment_id,
        "filename": filename or f"confluence-attachment-{attachment_id}",
        "download_url": download_url,
    }


def _confluence_extract_attachments(data: dict, *, link_base_fallback: str, limit: int) -> list[dict[str, str]]:
    """
    Extract attachment refs from a Confluence attachments API response.

    Returns a list of dicts with:
    - attachment_id
    - filename
    - download_url

    The result is bounded by `limit` and skips items missing required fields.
    """
    if not isinstance(data, dict):
        return []

    lim = _confluence_effective_positive_limit(limit)
    link_base = _confluence_attachment_link_base(data, fallback=str(link_base_fallback or ""))
    results = data.get("results") if isinstance(data.get("results"), list) else []
    out: list[dict[str, str]] = []

    for raw in results:
        if len(out) >= lim:
            break
        attachment_ref = _confluence_attachment_ref(raw, link_base=link_base)
        if attachment_ref:
            out.append(attachment_ref)

    return out


def _confluence_attachment_connector_metadata(
    *,
    base_url: str,
    space_key: str,
    page_id: str | None,
    page_title: str | None,
    page_url: str,
    attachment_id: str,
    filename: str,
    download_url: str,
    run_id: str,
    mode: str,
    ingest_method: str,
) -> dict[str, Any]:
    """
    Build doc_metadata.connector for a Confluence attachment document.

    This must not affect pipeline hashing (metadata is patched after doc creation).
    """
    return {
        "connector_id": "confluence_space",
        "doc_kind": "attachment",
        "base_url": base_url,
        "space_key": space_key,
        "page_id": (str(page_id or "").strip() or None),
        "page_title": (str(page_title or "").strip() or None),
        "page_url": str(page_url or "").strip(),
        "attachment_id": str(attachment_id or "").strip(),
        "filename": str(filename or "").strip(),
        "download_url": str(download_url or "").strip(),
        "run_id": str(run_id or "").strip(),
        "mode": str(mode or "").strip(),
        "ingest_method": str(ingest_method or "").strip(),
    }


def _normalize_connector_sync_mode(value: object) -> str:
    sync_mode = str(value or "auto").strip().lower()
    if sync_mode not in {"auto", "full", "incremental"}:
        return "auto"
    return sync_mode


def _resolve_connector_effective_mode(*, sync_mode: str, cursor_last_modified: str) -> str:
    effective_mode = str(sync_mode or "auto").strip().lower() or "auto"
    if effective_mode == "auto":
        effective_mode = "incremental" if cursor_last_modified else "full"
    if effective_mode == "incremental" and not cursor_last_modified:
        effective_mode = "full"
    return effective_mode


def _confluence_source_acl_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
    source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")
    source_acl_mode = (
        str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
    )
    source_acl_fallback_mode = (
        str(source_acl.get("fallback_mode") or "partial_members").strip().lower()
        if isinstance(source_acl, dict)
        else "partial_members"
    )
    return {
        "access": access,
        "source_acl_mode": source_acl_mode,
        "source_acl_fallback_mode": source_acl_fallback_mode,
        "has_manual_access_override": has_manual_access_override,
        "enable_source_acl": bool(source_acl_mode == "inherit" and not has_manual_access_override),
    }


def _build_confluence_space_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
    space_key = str(cfg.get("space_key") or "").strip()
    if not base_url or not space_key:
        raise ValueError("base_url and space_key are required")

    sync_mode = _normalize_connector_sync_mode(cfg.get("sync_mode"))

    state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
    cursor_last_modified = str(state.get("last_modified") or "").strip() if isinstance(state, dict) else ""
    cursor_last_modified_ids = (
        set(normalize_boundary_ids(state.get("last_modified_ids"))) if isinstance(state, dict) else set()
    )

    effective_mode = _resolve_connector_effective_mode(
        sync_mode=sync_mode,
        cursor_last_modified=cursor_last_modified,
    )

    include_attachments, max_attachments_per_page, max_total_attachments = _confluence_attachment_limits(cfg)
    ingest_method = _confluence_ingest_method(cfg)
    acl_settings = _confluence_source_acl_settings(cfg)
    user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
    auth_headers = _resolve_connectors_helper("_build_auth_headers")(cfg)
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": (user_agent or "MimirQ/1.0 (+confluence_space)"),
    }
    headers.update(auth_headers)

    return {
        "base_url": base_url,
        "space_key": space_key,
        "effective_mode": effective_mode,
        "cursor_last_modified": cursor_last_modified,
        "cursor_last_modified_ids": cursor_last_modified_ids,
        "max_pages": max(1, min(int(cfg.get("max_pages") or 50), 500)),
        "page_size": max(1, min(int(cfg.get("page_size") or 25), 100)),
        "soft_delete": bool(cfg.get("soft_delete", False)),
        "include_attachments": bool(include_attachments),
        "max_attachments_per_page": int(max_attachments_per_page),
        "max_total_attachments": int(max_total_attachments),
        "ingest_method": ingest_method,
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": (
            cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        ),
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access": acl_settings.get("access"),
        "source_acl_mode": acl_settings.get("source_acl_mode"),
        "source_acl_fallback_mode": acl_settings.get("source_acl_fallback_mode"),
        "has_manual_access_override": bool(acl_settings.get("has_manual_access_override")),
        "enable_source_acl": bool(acl_settings.get("enable_source_acl")),
        "user_agent": user_agent,
        "auth_headers": auth_headers,
        "api_base": _confluence_api_base_url(base_url),
        "search_url": f"{_confluence_api_base_url(base_url)}/content/search",
        "headers": headers,
    }


def _build_confluence_space_search_cql(*, space_key: str, effective_mode: str, cursor_last_modified: str) -> str:
    cql = f'space="{space_key}" and type=page and status=current'
    if effective_mode == "incremental" and cursor_last_modified:
        cql += f' and lastmodified >= "{cursor_last_modified}"'
    cql += " ORDER BY lastmodified ASC"
    return cql


def _initialize_confluence_space_run_stats(*, run: ConnectorRun, settings_map: dict[str, Any]) -> dict[str, Any]:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": settings_map.get("effective_mode"),
            "ingest_method": settings_map.get("ingest_method"),
            "space_key": settings_map.get("space_key"),
            "base_url": settings_map.get("base_url"),
            "max_pages": int(settings_map.get("max_pages") or 0),
            "page_size": int(settings_map.get("page_size") or 0),
            "processed_pages": 0,
            "cursor": 0,
            "created": 0,
            "failed": 0,
            "include_attachments": bool(settings_map.get("include_attachments")),
            "max_attachments_per_page": int(settings_map.get("max_attachments_per_page") or 0),
            "max_total_attachments": int(settings_map.get("max_total_attachments") or 0),
            "processed_attachments": 0,
            "created_attachments": 0,
            "failed_attachments": 0,
            "skipped_attachments": 0,
            "skipped_boundary_duplicates": 0,
            "failed_urls": [],
            "errors": [],
            "error_groups": [],
        }
    )
    if settings_map.get("cursor_last_modified"):
        stats["cursor_in"] = settings_map.get("cursor_last_modified")
    return stats


def _confluence_space_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return str(run.status or "").lower() == "cancelled"


def _initialize_confluence_space_progress() -> dict[str, Any]:
    return {
        "created": 0,
        "failed": 0,
        "processed": 0,
        "attachments_processed": 0,
        "attachments_created": 0,
        "attachments_failed": 0,
        "attachments_skipped": 0,
        "created_doc_ids": [],
        "delta_acl_docs_updated": 0,
        "delta_acl_pages_updated": 0,
        "observed_page_ids": set(),
        "last_modified_seen": None,
        "last_modified_ids_seen": set(),
        "skipped_boundary_duplicates": 0,
    }


async def _fetch_confluence_space_listing_page(
    pool,
    *,
    settings_map: dict[str, Any],
    start: int,
) -> tuple[list[dict[str, Any]], str]:
    params = {
        "cql": str(settings_map.get("cql") or ""),
        "start": int(start),
        "limit": int(settings_map.get("page_size") or 0),
        "expand": "version",
    }
    resp = await _confluence_request(
        pool,
        "GET",
        str(settings_map.get("search_url") or ""),
        params=params,
        headers=dict(settings_map.get("headers") or {}),
    )
    data = resp.json() if resp is not None else {}
    links = data.get("_links") if isinstance(data, dict) else None
    link_base = links.get("base") if isinstance(links, dict) and isinstance(links.get("base"), str) else None
    results = data.get("results") if isinstance(data, dict) else None
    pages = results if isinstance(results, list) else []
    return pages, str(link_base or settings_map.get("base_url") or "")


def _parse_confluence_listing_page(*, page: object, link_base: str, base_url: str) -> dict[str, str | None]:
    raw_page = page if isinstance(page, dict) else {}
    page_id = str(raw_page.get("id") or "").strip()
    title = str(raw_page.get("title") or "").strip()
    last_modified = _confluence_extract_last_modified(raw_page)
    page_links = raw_page.get("_links") if isinstance(raw_page.get("_links"), dict) else None
    webui = str(page_links.get("webui") or "").strip() if isinstance(page_links, dict) else ""
    if not webui and isinstance(page_links, dict):
        webui = str(page_links.get("tinyui") or "").strip()
    page_url = _confluence_join_webui(base=str(link_base or base_url), webui=webui)
    return {
        "page_id": page_id,
        "title": title,
        "last_modified": last_modified,
        "page_url": page_url,
    }


def _build_confluence_page_filename(*, page_id: str, title: str) -> str | None:
    if page_id:
        base_name = f"{page_id}-{title}".strip("-").strip() if title else str(page_id)
    else:
        base_name = title or "confluence-page"
    if not base_name:
        return None
    filename = base_name
    if not filename.lower().endswith((".html", ".htm")):
        filename = f"{filename}.html"
    return filename


def _confluence_source_acl_fallback_access(settings_map: dict[str, Any]) -> dict[str, Any]:
    return {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}


async def _fetch_confluence_page_restriction_principals(
    pool,
    *,
    page_id: str,
    settings_map: dict[str, Any],
) -> tuple[bool | None, list[str]]:
    restrictions_url = f"{settings_map.get('api_base')}/content/{page_id}/restriction/byOperation/read"
    response = await _confluence_request(
        pool,
        "GET",
        restrictions_url,
        params={"expand": "restrictions.group,restrictions.user"},
        headers=dict(settings_map.get("headers") or {}),
    )
    if response is not None and int(getattr(response, "status_code", 0) or 0) == 404:
        return False, []

    data = response.json() if response is not None else {}
    restricted, group_names, _user_count = _confluence_parse_read_restriction_groups(data)
    if not restricted:
        return False, []

    ext_ids = [_confluence_group_principal_key(name) for name in (group_names or [])]
    return True, [key for key in ext_ids if key]


def _resolve_confluence_acl_access_from_principals(
    db: Session,
    *,
    tenant_id: UUID,
    ext_ids: list[str],
    settings_map: dict[str, Any],
) -> tuple[dict[str, Any], set[UUID], bool]:
    mapped_gids = set(
        _resolve_connectors_helper("_resolve_tenant_group_ids_by_external_id")(
            db,
            tenant_id=tenant_id,
            external_ids=ext_ids,
        )
        or set()
    )
    if not mapped_gids:
        return _confluence_source_acl_fallback_access(settings_map), mapped_gids, True

    ordered = sorted(mapped_gids, key=lambda value: str(value))
    return {
        "mode": "partial_members",
        "partial_group_list": [str(group_id) for group_id in ordered],
    }, mapped_gids, False


def _build_confluence_acl_provenance(
    *,
    run_id: UUID,
    effective_access: dict[str, Any] | None,
    settings_map: dict[str, Any],
    ext_ids: list[str],
    mapped_gids: set[UUID],
    fallback_used: bool,
    restricted_flag: bool | None,
) -> dict[str, Any] | None:
    with contextlib.suppress(Exception):
        from app.services.document_acl_provenance_service import build_document_acl_provenance

        return build_document_acl_provenance(
            connector_id="confluence_space",
            connector_run_id=str(run_id),
            effective_access=effective_access,
            source_acl_mode=str(settings_map.get("source_acl_mode") or "disabled"),
            source_acl_fallback_mode=str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            source_principal_external_ids=ext_ids,
            mapped_group_ids=mapped_gids,
            fallback_used=fallback_used,
            restricted=restricted_flag,
        )
    return None


def _delta_sync_confluence_page_acl(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_id: str,
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> int:
    return int(
        _resolve_connectors_helper("_delta_sync_confluence_documents_acl_by_page_id")(
            db,
            tenant_id=tenant_id,
            dataset_id=run.dataset_id,
            base_url=str(settings_map.get("base_url") or ""),
            space_key=str(settings_map.get("space_key") or ""),
            page_id=page_id,
            requested_by=requested_by,
            access=effective_access,
            acl_provenance=acl_provenance,
        )
    )


async def _resolve_confluence_page_acl(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    page_id: str,
    settings_map: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
    effective_access = settings_map.get("access")
    acl_provenance: dict[str, Any] | None = None

    if not settings_map.get("enable_source_acl") or not page_id:
        return (effective_access if isinstance(effective_access, dict) else None), None, 0

    ext_ids: list[str] = []
    mapped_gids: set[UUID] = set()
    restricted_flag: bool | None = None
    fallback_used = False
    try:
        restricted_flag, ext_ids = await _fetch_confluence_page_restriction_principals(
            pool,
            page_id=page_id,
            settings_map=settings_map,
        )
        if restricted_flag:
            effective_access, mapped_gids, fallback_used = _resolve_confluence_acl_access_from_principals(
                db,
                tenant_id=tenant_id,
                ext_ids=ext_ids,
                settings_map=settings_map,
            )
    except Exception:
        effective_access = _confluence_source_acl_fallback_access(settings_map)
        restricted_flag = None
        fallback_used = True

    acl_provenance = _build_confluence_acl_provenance(
        run_id=run_id,
        effective_access=effective_access,
        settings_map=settings_map,
        ext_ids=ext_ids,
        mapped_gids=mapped_gids,
        fallback_used=fallback_used,
        restricted_flag=restricted_flag,
    )
    updated_existing = _delta_sync_confluence_page_acl(
        db,
        run=run,
        tenant_id=tenant_id,
        requested_by=requested_by,
        page_id=page_id,
        effective_access=effective_access if isinstance(effective_access, dict) else None,
        acl_provenance=acl_provenance,
        settings_map=settings_map,
    )
    return (effective_access if isinstance(effective_access, dict) else None), acl_provenance, updated_existing


def _patch_confluence_page_document_metadata(
    db: Session,
    *,
    doc: Any,
    run: ConnectorRun,
    page_id: str,
    title: str,
    page_url: str,
    last_modified: str | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> None:
    try:
        meta0 = dict(getattr(doc, "doc_metadata", None) or {})
        if last_modified:
            lm_iso = _resolve_connectors_helper("_normalize_datetime_utc_iso")(last_modified) or last_modified
            meta0["source_last_modified_at"] = lm_iso
            meta0["source_last_modified_source"] = "connector:confluence:last_modified"
            meta0["source_last_modified_raw"] = meta0.get("source_last_modified_raw") or last_modified
        if isinstance(acl_provenance, dict):
            meta0["acl_provenance"] = dict(acl_provenance)
        meta0["connector"] = {
            "connector_id": "confluence_space",
            "base_url": settings_map.get("base_url"),
            "space_key": settings_map.get("space_key"),
            "page_id": (page_id or None),
            "page_title": (title or None),
            "page_url": page_url,
            "last_modified": (last_modified or None),
            "run_id": str(run.id),
            "mode": settings_map.get("effective_mode"),
            "ingest_method": settings_map.get("ingest_method"),
        }
        doc.doc_metadata = meta0
        _resolve_connectors_helper("_apply_connector_identity_metadata")(
            doc=doc,
            run=run,
            connector_id="confluence_space",
            source_ref=(page_id or page_url),
            source_id=(page_id or page_url),
        )
        db.commit()
    except Exception:
        pass


async def _ingest_confluence_page_webui(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_url: str,
    filename: str | None,
    settings_map: dict[str, Any],
):
    body = _resolve_connectors_helper("UrlUploadRequest")(
        url=page_url,
        dataset_id=run.dataset_id,
        filename=filename,
        fetch_headers=settings_map.get("auth_headers") or None,
        user_agent=settings_map.get("user_agent"),
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    return await _resolve_connectors_helper("_ingest_url_upload_request")(
        background_tasks=None,
        body=body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )


def _confluence_page_html_document(*, title: str, page_url: str, page_html: str) -> str:
    title_escaped = html.escape(title or "")
    base_tag = f'<base href="{html.escape(page_url)}" />' if page_url else ""
    return (
        "<!doctype html>\n"
        "<html>\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{title_escaped}</title>\n"
        f"  {base_tag}\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{title_escaped}</h1>\n"
        f"{page_html}\n"
        "</body>\n"
        "</html>\n"
    )


async def _fetch_confluence_page_view_html(pool, *, page_id: str, settings_map: dict[str, Any]) -> str:
    content_resp = await _confluence_request(
        pool,
        "GET",
        f"{settings_map.get('api_base')}/content/{page_id}",
        params={"expand": "body.view,version"},
        headers=dict(settings_map.get("headers") or {}),
    )
    content = content_resp.json() if content_resp is not None else {}
    body = content.get("body") if isinstance(content, dict) else None
    view = body.get("view") if isinstance(body, dict) else None
    view_value = view.get("value") if isinstance(view, dict) else None
    page_html = str(view_value or "")
    if not page_html.strip():
        raise ValueError("missing body.view.value")
    return page_html


async def _ingest_confluence_page_api_view(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_id: str,
    title: str,
    page_url: str,
    filename: str | None,
    settings_map: dict[str, Any],
):
    if not page_id:
        raise ValueError("missing page id")
    page_html = await _fetch_confluence_page_view_html(pool, page_id=page_id, settings_map=settings_map)
    html_body = _resolve_connectors_helper("LocalHtmlIngestRequest")(
        html=_confluence_page_html_document(title=title, page_url=page_url, page_html=page_html),
        source_url=page_url,
        dataset_id=run.dataset_id,
        filename=filename,
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    return await _resolve_connectors_helper("_ingest_local_html_request")(
        background_tasks=None,
        body=html_body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
        ingestion_kind="upload_url",
    )


async def _ingest_confluence_page_document(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_id: str,
    title: str,
    page_url: str,
    filename: str | None,
    settings_map: dict[str, Any],
):
    if str(settings_map.get("ingest_method") or "") == "webui":
        return await _ingest_confluence_page_webui(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            page_url=page_url,
            filename=filename,
            settings_map=settings_map,
        )
    return await _ingest_confluence_page_api_view(
        pool,
        db,
        run=run,
        tenant_id=tenant_id,
        requested_by=requested_by,
        page_id=page_id,
        title=title,
        page_url=page_url,
        filename=filename,
        settings_map=settings_map,
    )


def _track_confluence_run_document(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    document_id: UUID,
    source_ref: str,
) -> None:
    db.add(
        _resolve_connectors_helper("ConnectorRunDocument")(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=document_id,
            source_ref=(source_ref or "")[:1000] or None,
            status="created",
        )
    )


async def _ingest_confluence_page(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_info: dict[str, str | None],
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> UUID:
    page_id = str(page_info.get("page_id") or "")
    title = str(page_info.get("title") or "")
    page_url = str(page_info.get("page_url") or "")
    filename = _build_confluence_page_filename(page_id=page_id, title=title)

    doc = await _ingest_confluence_page_document(
        pool,
        db,
        run=run,
        tenant_id=tenant_id,
        requested_by=requested_by,
        page_id=page_id,
        title=title,
        page_url=page_url,
        filename=filename,
        settings_map=settings_map,
    )

    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=doc,
        access=effective_access,
        connector_id="confluence_space",
    )
    _patch_confluence_page_document_metadata(
        db,
        doc=doc,
        run=run,
        page_id=page_id,
        title=title,
        page_url=page_url,
        last_modified=str(page_info.get("last_modified") or "") or None,
        acl_provenance=acl_provenance,
        settings_map=settings_map,
    )
    _track_confluence_run_document(db, run=run, tenant_id=tenant_id, document_id=doc.id, source_ref=(page_id or page_url))
    return doc.id


def _patch_confluence_attachment_document_metadata(
    *,
    att_doc: Any,
    run: ConnectorRun,
    page_id: str,
    title: str,
    page_url: str,
    attachment_id: str,
    filename: str,
    download_url: str,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> None:
    try:
        meta_att = dict(getattr(att_doc, "doc_metadata", None) or {})
        if isinstance(acl_provenance, dict):
            meta_att["acl_provenance"] = dict(acl_provenance)
        meta_att["connector"] = _confluence_attachment_connector_metadata(
            base_url=str(settings_map.get("base_url") or ""),
            space_key=str(settings_map.get("space_key") or ""),
            page_id=(page_id or None),
            page_title=(title or None),
            page_url=page_url,
            attachment_id=attachment_id,
            filename=filename,
            download_url=download_url,
            run_id=str(run.id),
            mode=str(settings_map.get("effective_mode") or ""),
            ingest_method=str(settings_map.get("ingest_method") or ""),
        )
        att_doc.doc_metadata = meta_att
        _resolve_connectors_helper("_apply_connector_identity_metadata")(
            doc=att_doc,
            run=run,
            connector_id="confluence_space",
            source_ref=(attachment_id or download_url),
            source_id=(attachment_id or download_url),
        )
    except Exception:
        pass


async def _ingest_single_confluence_attachment(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_id: str,
    title: str,
    page_url: str,
    attachment_ref: dict[str, str],
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> UUID:
    attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
    filename = str(attachment_ref.get("filename") or "").strip()
    download_url = str(attachment_ref.get("download_url") or "").strip()
    att_body = _resolve_connectors_helper("UrlUploadRequest")(
        url=download_url,
        dataset_id=run.dataset_id,
        filename=filename,
        fetch_headers=settings_map.get("auth_headers") or None,
        user_agent=settings_map.get("user_agent"),
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    att_doc = await _resolve_connectors_helper("_ingest_url_upload_request")(
        background_tasks=None,
        body=att_body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )
    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=att_doc,
        access=effective_access,
        connector_id="confluence_space",
    )
    _patch_confluence_attachment_document_metadata(
        att_doc=att_doc,
        run=run,
        page_id=page_id,
        title=title,
        page_url=page_url,
        attachment_id=attachment_id,
        filename=filename,
        download_url=download_url,
        acl_provenance=acl_provenance,
        settings_map=settings_map,
    )
    _track_confluence_run_document(
        db,
        run=run,
        tenant_id=tenant_id,
        document_id=att_doc.id,
        source_ref=(attachment_id or download_url),
    )
    return att_doc.id


def _confluence_should_skip_attachments(db: Session, *, run: ConnectorRun, page_id: str, settings_map: dict[str, Any], progress: dict[str, Any]) -> bool:
    return (
        not settings_map.get("include_attachments")
        or not page_id
        or int(progress.get("attachments_processed") or 0) >= int(settings_map.get("max_total_attachments") or 0)
        or _confluence_space_run_cancelled(db, run=run)
    )


def _confluence_attachment_page_limit(settings_map: dict[str, Any], progress: dict[str, Any]) -> int:
    remaining_total = int(settings_map.get("max_total_attachments") or 0) - int(progress.get("attachments_processed") or 0)
    return int(min(int(settings_map.get("max_attachments_per_page") or 0), max(0, remaining_total)))


async def _fetch_confluence_attachment_refs(
    pool,
    *,
    page_id: str,
    link_base: str,
    settings_map: dict[str, Any],
    limit: int,
) -> list[dict[str, str]]:
    att_resp = await _confluence_request(
        pool,
        "GET",
        f"{settings_map.get('api_base')}/content/{page_id}/child/attachment",
        params={"start": 0, "limit": limit},
        headers=dict(settings_map.get("headers") or {}),
    )
    att_data = att_resp.json() if att_resp is not None else {}
    return _confluence_extract_attachments(
        att_data if isinstance(att_data, dict) else {},
        link_base_fallback=str(link_base or settings_map.get("base_url") or ""),
        limit=limit,
    )


def _confluence_attachment_ref_skipped(attachment_ref: dict[str, str]) -> bool:
    attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
    filename = str(attachment_ref.get("filename") or "").strip()
    download_url = str(attachment_ref.get("download_url") or "").strip()
    if not attachment_id or not download_url:
        return True

    ext = Path(filename).suffix.lower()
    return bool(ext and ext not in settings.allowed_extensions_list)


def _append_confluence_attachment_error(run: ConnectorRun, *, url: str, exc: Exception) -> None:
    run.stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=url, exc=exc)


def _confluence_total_attachment_limit_reached(progress: dict[str, Any], *, processed_in_page: int, settings_map: dict[str, Any]) -> bool:
    return (int(progress.get("attachments_processed") or 0) + processed_in_page) >= int(settings_map.get("max_total_attachments") or 0)


async def _process_confluence_attachment_ref(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_info: dict[str, str | None],
    attachment_ref: dict[str, str],
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> tuple[UUID | None, bool]:
    if _confluence_attachment_ref_skipped(attachment_ref):
        return None, True

    try:
        doc_id = await _ingest_single_confluence_attachment(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            page_id=str(page_info.get("page_id") or ""),
            title=str(page_info.get("title") or ""),
            page_url=str(page_info.get("page_url") or ""),
            attachment_ref=attachment_ref,
            effective_access=effective_access,
            acl_provenance=acl_provenance,
            settings_map=settings_map,
        )
        return doc_id, False
    except Exception as exc:  # noqa: BLE001
        attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
        download_url = str(attachment_ref.get("download_url") or "").strip()
        _append_confluence_attachment_error(run, url=(download_url or attachment_id), exc=exc)
        raise


async def _ingest_confluence_page_attachments(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    page_info: dict[str, str | None],
    link_base: str,
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any]:
    page_id = str(page_info.get("page_id") or "")
    if _confluence_should_skip_attachments(db, run=run, page_id=page_id, settings_map=settings_map, progress=progress):
        return _zero_confluence_attachment_result()

    per_page_limit = _confluence_attachment_page_limit(settings_map, progress)
    if per_page_limit <= 0:
        return _zero_confluence_attachment_result()

    try:
        att_refs = await _fetch_confluence_attachment_refs(
            pool,
            page_id=page_id,
            link_base=link_base,
            settings_map=settings_map,
            limit=per_page_limit,
        )
    except Exception as exc:  # noqa: BLE001
        _append_confluence_attachment_error(run, url=f"confluence_attachments:{page_id}", exc=exc)
        return _zero_confluence_attachment_result(failed=1, attachments_failed=1)

    created_doc_ids: list[UUID] = []
    attachments_processed = 0
    attachments_created = 0
    attachments_failed = 0
    attachments_skipped = 0
    failed = 0

    for attachment_ref in att_refs:
        if _confluence_total_attachment_limit_reached(progress, processed_in_page=attachments_processed, settings_map=settings_map):
            break
        if _confluence_space_run_cancelled(db, run=run):
            break
        attachments_processed += 1

        try:
            doc_id, skipped = await _process_confluence_attachment_ref(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                page_info=page_info,
                attachment_ref=attachment_ref,
                effective_access=effective_access,
                acl_provenance=acl_provenance,
                settings_map=settings_map,
            )
            if skipped:
                attachments_skipped += 1
                continue
            created_doc_ids.append(doc_id)
            attachments_created += 1
        except Exception:  # noqa: BLE001
            failed += 1
            attachments_failed += 1

    return {
        "attachments_processed": attachments_processed,
        "attachments_created": attachments_created,
        "attachments_failed": attachments_failed,
        "attachments_skipped": attachments_skipped,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
    }


def _persist_confluence_space_progress(
    db: Session,
    *,
    run: ConnectorRun,
    progress: dict[str, Any],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "processed_pages": int(progress.get("processed") or 0),
            "cursor": int(progress.get("processed") or 0),
            "created": int(progress.get("created") or 0),
            "failed": int(progress.get("failed") or 0),
            "processed_attachments": int(progress.get("attachments_processed") or 0),
            "created_attachments": int(progress.get("attachments_created") or 0),
            "failed_attachments": int(progress.get("attachments_failed") or 0),
            "skipped_attachments": int(progress.get("attachments_skipped") or 0),
            "skipped_boundary_duplicates": int(progress.get("skipped_boundary_duplicates") or 0),
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_pages_updated") or 0),
        }
    )
    if progress.get("last_modified_seen"):
        stats["last_modified"] = progress.get("last_modified_seen")
        stats["last_modified_ids"] = sorted(progress.get("last_modified_ids_seen") or set())
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


def _confluence_page_limit_reached(progress: dict[str, Any], settings_map: dict[str, Any]) -> bool:
    return int(progress.get("processed") or 0) >= int(settings_map.get("max_pages") or 0)


def _confluence_page_skipped_by_boundary(page_info: dict[str, str | None], settings_map: dict[str, Any]) -> bool:
    if str(settings_map.get("effective_mode") or "") != "incremental":
        return False
    return _should_skip_timestamp_boundary_item(
        item_id=str(page_info.get("page_id") or ""),
        item_timestamp=str(page_info.get("last_modified") or "") or None,
        cursor_timestamp=str(settings_map.get("cursor_last_modified") or ""),
        boundary_ids=set(settings_map.get("cursor_last_modified_ids") or set()),
    )


def _record_confluence_boundary_skip(db: Session, *, run: ConnectorRun, progress: dict[str, Any]) -> None:
    progress["skipped_boundary_duplicates"] = int(progress.get("skipped_boundary_duplicates") or 0) + 1
    _persist_confluence_space_progress(db, run=run, progress=progress)


def _advance_confluence_progress_boundary(progress: dict[str, Any], *, page_info: dict[str, str | None]) -> None:
    last_modified = str(page_info.get("last_modified") or "")
    if not last_modified:
        return

    last_seen, ids_seen = _advance_timestamp_boundary(
        last_timestamp=progress.get("last_modified_seen"),
        boundary_ids=set(progress.get("last_modified_ids_seen") or set()),
        item_timestamp=last_modified,
        item_id=str(page_info.get("page_id") or ""),
    )
    progress["last_modified_seen"] = last_seen
    progress["last_modified_ids_seen"] = ids_seen


def _record_confluence_page_failure(
    db: Session,
    *,
    run: ConnectorRun,
    progress: dict[str, Any],
    url: str,
    exc: Exception,
    mark_processed: bool,
) -> None:
    progress["failed"] = int(progress.get("failed") or 0) + 1
    run.stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=url, exc=exc)
    if mark_processed:
        progress["processed"] = int(progress.get("processed") or 0) + 1
        _persist_confluence_space_progress(db, run=run, progress=progress)


def _merge_confluence_attachment_progress(progress: dict[str, Any], attachments: dict[str, Any]) -> None:
    progress["created"] = int(progress.get("created") or 0) + int(attachments.get("attachments_created") or 0)
    progress["failed"] = int(progress.get("failed") or 0) + int(attachments.get("failed") or 0)
    progress["attachments_processed"] = int(progress.get("attachments_processed") or 0) + int(
        attachments.get("attachments_processed") or 0
    )
    progress["attachments_created"] = int(progress.get("attachments_created") or 0) + int(
        attachments.get("attachments_created") or 0
    )
    progress["attachments_failed"] = int(progress.get("attachments_failed") or 0) + int(
        attachments.get("attachments_failed") or 0
    )
    progress["attachments_skipped"] = int(progress.get("attachments_skipped") or 0) + int(
        attachments.get("attachments_skipped") or 0
    )
    progress.setdefault("created_doc_ids", []).extend(attachments.get("created_doc_ids") or [])


async def _process_single_confluence_page(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    page_info: dict[str, str | None],
    link_base: str,
    progress: dict[str, Any],
) -> None:
    page_id = str(page_info.get("page_id") or "")
    effective_access, acl_provenance, updated_existing = await _resolve_confluence_page_acl(
        pool,
        db,
        run=run,
        run_id=run_id,
        tenant_id=tenant_id,
        requested_by=requested_by,
        page_id=page_id,
        settings_map=settings_map,
    )
    progress["delta_acl_docs_updated"] = int(progress.get("delta_acl_docs_updated") or 0) + int(updated_existing)
    if updated_existing:
        progress["delta_acl_pages_updated"] = int(progress.get("delta_acl_pages_updated") or 0) + 1

    doc_id = await _ingest_confluence_page(
        pool,
        db,
        run=run,
        tenant_id=tenant_id,
        requested_by=requested_by,
        page_info=page_info,
        effective_access=effective_access,
        acl_provenance=acl_provenance,
        settings_map=settings_map,
    )
    progress["created"] = int(progress.get("created") or 0) + 1
    progress.setdefault("created_doc_ids", []).append(doc_id)
    if page_id:
        progress.setdefault("observed_page_ids", set()).add(page_id)

    attachments = await _ingest_confluence_page_attachments(
        pool,
        db,
        run=run,
        tenant_id=tenant_id,
        requested_by=requested_by,
        page_info=page_info,
        link_base=link_base,
        effective_access=effective_access,
        acl_provenance=acl_provenance,
        settings_map=settings_map,
        progress=progress,
    )
    _merge_confluence_attachment_progress(progress, attachments)


async def _process_confluence_space_page_batch(
    pool,
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    pages: list[dict[str, Any]],
    link_base: str,
    progress: dict[str, Any],
) -> dict[str, Any]:
    for page in pages:
        if _confluence_page_limit_reached(progress, settings_map):
            break
        if _confluence_space_run_cancelled(db, run=run):
            break

        page_info = _parse_confluence_listing_page(
            page=page,
            link_base=link_base,
            base_url=str(settings_map.get("base_url") or ""),
        )
        page_id = str(page_info.get("page_id") or "")
        title = str(page_info.get("title") or "")
        page_url = str(page_info.get("page_url") or "")

        if _confluence_page_skipped_by_boundary(page_info, settings_map):
            _record_confluence_boundary_skip(db, run=run, progress=progress)
            continue

        _advance_confluence_progress_boundary(progress, page_info=page_info)

        if not page_url:
            _record_confluence_page_failure(
                db,
                run=run,
                progress=progress,
                url=(page_id or title or "confluence_page"),
                exc=ValueError("missing page url"),
                mark_processed=True,
            )
            continue

        try:
            await _process_single_confluence_page(
                pool,
                db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                requested_by=requested_by,
                settings_map=settings_map,
                page_info=page_info,
                link_base=link_base,
                progress=progress,
            )
        except Exception as exc:  # noqa: BLE001
            _record_confluence_page_failure(db, run=run, progress=progress, url=page_url, exc=exc, mark_processed=False)
        finally:
            progress["processed"] = int(progress.get("processed") or 0) + 1
            _persist_confluence_space_progress(db, run=run, progress=progress)

    return progress


async def _probe_confluence_space_listing_complete(
    pool,
    *,
    settings_map: dict[str, Any],
    start: int,
) -> bool:
    try:
        probe = await _confluence_request(
            pool,
            "GET",
            str(settings_map.get("search_url") or ""),
            params={"cql": str(settings_map.get("cql") or ""), "start": int(start), "limit": 1},
            headers=dict(settings_map.get("headers") or {}),
        )
        probe_data = probe.json() if probe is not None else {}
        probe_results = probe_data.get("results") if isinstance(probe_data, dict) else None
        probe_pages = probe_results if isinstance(probe_results, list) else []
        return not probe_pages
    except Exception:
        return False


def _confluence_space_metadata_query(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    settings_map: dict[str, Any],
):
    return (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == run.dataset_id,
            DBDocument.archived_at.is_(None),
        )
        .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "confluence_space")  # type: ignore[attr-defined]
        .filter(DBDocument.doc_metadata["connector"]["space_key"].astext == str(settings_map.get("space_key") or ""))  # type: ignore[attr-defined]
        .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == str(settings_map.get("base_url") or ""))  # type: ignore[attr-defined]
    )


def _confluence_soft_delete_candidates(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    settings_map: dict[str, Any],
) -> list[Any]:
    try:
        return _confluence_space_metadata_query(db, run=run, tenant_id=tenant_id, settings_map=settings_map).all()
    except Exception:
        return (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == run.dataset_id,
                DBDocument.archived_at.is_(None),
            )
            .order_by(DBDocument.created_at.desc())
            .limit(5000)
            .all()
        )


def _confluence_doc_missing_from_full_sync(doc: Any, *, settings_map: dict[str, Any], observed_page_ids: set[str]) -> bool:
    conn = _confluence_doc_connector_metadata(doc)
    if str(conn.get("connector_id") or "") != "confluence_space":
        return False
    if str(conn.get("space_key") or "") != str(settings_map.get("space_key") or ""):
        return False
    if str(conn.get("base_url") or "") != str(settings_map.get("base_url") or ""):
        return False
    page_id = str(conn.get("page_id") or "").strip()
    return bool(page_id and page_id not in observed_page_ids)


def _soft_delete_missing_confluence_pages(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    settings_map: dict[str, Any],
    observed_page_ids: set[str],
) -> int:
    now = _resolve_connectors_helper("_now")()
    disabled = 0
    docs = _confluence_soft_delete_candidates(db, run=run, tenant_id=tenant_id, settings_map=settings_map)
    for doc in docs or []:
        if not _confluence_doc_missing_from_full_sync(doc, settings_map=settings_map, observed_page_ids=observed_page_ids):
            continue
        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1
    return disabled


def _finalize_cancelled_confluence_space_run(db: Session, *, run: ConnectorRun) -> None:
    if run.finished_at is None:
        run.finished_at = _resolve_connectors_helper("_now")()
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _emit_confluence_source_acl_delta_sync_audit(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    run: ConnectorRun,
    run_id: UUID,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    if not settings_map.get("enable_source_acl"):
        return
    with contextlib.suppress(Exception):
        from app.services.audit_log_service import audit_log_event

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=requested_by,
            action="confluence_space.source_acl.delta_sync",
            resource_type="connector_run",
            resource_id=str(run_id),
            details={
                "dataset_id": str(run.dataset_id),
                "connector_id": "confluence_space",
                "base_url": str(settings_map.get("base_url") or ""),
                "space_key": str(settings_map.get("space_key") or ""),
                "mode": str(settings_map.get("effective_mode") or ""),
                "updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
                "updated_pages": int(progress.get("delta_acl_pages_updated") or 0),
                "fallback_mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            },
        )


def _finalize_confluence_space_run_success(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    run_id: UUID,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
    soft_deleted: int,
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_pages_updated") or 0),
            "skipped_boundary_duplicates": int(progress.get("skipped_boundary_duplicates") or 0),
            "soft_deleted": int(soft_deleted),
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    run.finished_at = _resolve_connectors_helper("_now")()
    run.status = _resolve_connectors_helper("_connector_run_completion_status")(
        created=int(progress.get("created") or 0),
        failed=int(progress.get("failed") or 0),
    )
    _emit_confluence_source_acl_delta_sync_audit(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        run=run,
        run_id=run_id,
        settings_map=settings_map,
        progress=progress,
    )
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _mark_confluence_space_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = (
            db.query(ConnectorRun)
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if run is not None:
            run.status = "failed"
            run.finished_at = _resolve_connectors_helper("_now")()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


async def _execute_confluence_space_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for confluence_space connector.

    Flow:
    - List pages in a Confluence space (full or incremental based on state/sync_mode)
    - For each page, ingest its web UI URL via the existing URL ingestion pipeline
    """
    db = _resolve_connectors_helper("SessionLocal")()
    try:
        run = (
            db.query(ConnectorRun)
            .options(selectinload(ConnectorRun.documents))
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if not run:
            return
        if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
            return

        run.status = "running"
        run.started_at = _resolve_connectors_helper("_now")()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        settings_map = _build_confluence_space_run_settings(
            _resolve_connectors_helper("decrypt_connector_config_secrets")(dict(run.config or {}))
        )
        settings_map["cql"] = _build_confluence_space_search_cql(
            space_key=str(settings_map.get("space_key") or ""),
            effective_mode=str(settings_map.get("effective_mode") or ""),
            cursor_last_modified=str(settings_map.get("cursor_last_modified") or ""),
        )
        run.stats = _resolve_connectors_helper("_finalize_connector_stats")(
            _initialize_confluence_space_run_stats(run=run, settings_map=settings_map)
        )
        db.commit()

        pool = _resolve_connectors_helper("get_http_client_pool")()
        start = 0
        listing_complete = False
        stopped_mid_batch = False
        progress = _initialize_confluence_space_progress()

        while int(progress.get("processed") or 0) < int(settings_map.get("max_pages") or 0):
            if _confluence_space_run_cancelled(db, run=run):
                break

            pages, link_base = await _fetch_confluence_space_listing_page(
                pool,
                settings_map=settings_map,
                start=start,
            )
            if not pages:
                listing_complete = True
                break

            batch_processed0 = int(progress.get("processed") or 0)
            progress = await _resolve_connectors_helper("_process_confluence_space_page_batch")(
                pool,
                db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                requested_by=requested_by,
                settings_map=settings_map,
                pages=pages,
                link_base=link_base,
                progress=progress,
            )

            if int(progress.get("processed") or 0) >= int(settings_map.get("max_pages") or 0) and (
                batch_processed0 + len(pages)
            ) > int(settings_map.get("max_pages") or 0):
                stopped_mid_batch = True

            start += int(len(pages))
            if int(progress.get("processed") or 0) >= int(settings_map.get("max_pages") or 0):
                break
            if len(pages) < int(settings_map.get("page_size") or 0):
                listing_complete = True
                break

        if (
            str(settings_map.get("effective_mode") or "") == "full"
            and bool(settings_map.get("soft_delete"))
            and run.dataset_id
            and progress.get("observed_page_ids")
            and (not listing_complete)
            and (not stopped_mid_batch)
            and int(progress.get("processed") or 0) >= int(settings_map.get("max_pages") or 0)
            and (not _confluence_space_run_cancelled(db, run=run))
        ):
            listing_complete = await _resolve_connectors_helper("_probe_confluence_space_listing_complete")(
                pool,
                settings_map=settings_map,
                start=start,
            )

        if _confluence_space_run_cancelled(db, run=run):
            _resolve_connectors_helper("_finalize_cancelled_confluence_space_run")(db, run=run)
            return

        soft_deleted = 0
        if (
            str(settings_map.get("effective_mode") or "") == "full"
            and bool(settings_map.get("soft_delete"))
            and run.dataset_id
            and progress.get("observed_page_ids")
            and listing_complete
        ):
            soft_deleted = _resolve_connectors_helper("_soft_delete_missing_confluence_pages")(
                db,
                run=run,
                tenant_id=tenant_id,
                settings_map=settings_map,
                observed_page_ids=set(progress.get("observed_page_ids") or set()),
            )

        _resolve_connectors_helper("_finalize_confluence_space_run_success")(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            run_id=run_id,
            settings_map=settings_map,
            progress=progress,
            soft_deleted=soft_deleted,
        )
    except Exception as exc:  # noqa: BLE001
        _resolve_connectors_helper("_mark_confluence_space_run_failed")(
            db,
            run_id=run_id,
            tenant_id=tenant_id,
            exc=exc,
        )
    finally:
        db.close()
