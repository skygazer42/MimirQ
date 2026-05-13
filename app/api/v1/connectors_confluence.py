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
        q = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "confluence_space")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["space_key"].astext == space_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["page_id"].astext == pid)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
        )
        for doc in q.yield_per(200):
            _resolve_connectors_helper("_apply_document_access_from_config")(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                connector_id="confluence_space",
            )
            if isinstance(acl_provenance, dict):
                try:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                    meta0["acl_provenance"] = dict(acl_provenance)
                    doc.doc_metadata = meta0
                except Exception:
                    pass
            updated += 1
    except Exception:
        # Best-effort fallback: scan a bounded recent window and filter in Python.
        max_docs_scan = max(0, int(max_docs_scan or 0))
        if max_docs_scan <= 0:
            max_docs_scan = 5000
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .order_by(DBDocument.created_at.desc())
            .limit(max_docs_scan)
            .all()
        )
        for doc in docs or []:
            meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}
            conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
            if str(conn.get("connector_id") or "") != "confluence_space":
                continue
            if str(conn.get("base_url") or "") != base_url:
                continue
            if str(conn.get("space_key") or "") != space_key:
                continue
            if str(conn.get("page_id") or "") != pid:
                continue
            _resolve_connectors_helper("_apply_document_access_from_config")(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                connector_id="confluence_space",
            )
            if isinstance(acl_provenance, dict):
                try:
                    meta0 = dict(meta or {})
                    meta0["acl_provenance"] = dict(acl_provenance)
                    doc.doc_metadata = meta0
                except Exception:
                    pass
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

    for it in items:
        if not isinstance(it, dict):
            continue
        restrictions = it.get("restrictions")
        if not isinstance(restrictions, dict):
            continue

        group_obj = restrictions.get("group")
        if isinstance(group_obj, dict):
            g_res = group_obj.get("results")
            g_items = g_res if isinstance(g_res, list) else []
            for g in g_items:
                if not isinstance(g, dict):
                    continue
                name = str(g.get("name") or "").strip()
                if not name:
                    continue
                k = name.lower()
                if k in seen_g:
                    continue
                seen_g.add(k)
                group_names.append(name)
                if max_groups and len(group_names) >= max_groups:
                    break

        user_obj = restrictions.get("user")
        if isinstance(user_obj, dict):
            u_res = user_obj.get("results")
            u_items = u_res if isinstance(u_res, list) else []
            user_count += int(len(u_items))

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

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    links = data.get("_links") if isinstance(data.get("_links"), dict) else {}
    link_base = links.get("base") if isinstance(links.get("base"), str) and str(links.get("base") or "").strip() else str(link_base_fallback or "")

    results = data.get("results") if isinstance(data.get("results"), list) else []
    out: list[dict[str, str]] = []

    for raw in results:
        if len(out) >= lim:
            break
        if not isinstance(raw, dict):
            continue

        attachment_id = str(raw.get("id") or "").strip()
        if not attachment_id:
            continue

        filename = str(raw.get("title") or raw.get("filename") or raw.get("name") or "").strip()
        if not filename:
            filename = f"confluence-attachment-{attachment_id}"

        item_links = raw.get("_links") if isinstance(raw.get("_links"), dict) else {}
        download = str(item_links.get("download") or "").strip()
        download_url = _confluence_attachment_download_url(base=link_base, download=download)
        if not download_url:
            continue

        out.append(
            {
                "attachment_id": attachment_id,
                "filename": filename,
                "download_url": download_url,
            }
        )

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
        restrictions_url = f"{settings_map.get('api_base')}/content/{page_id}/restriction/byOperation/read"
        r_resp = await _confluence_request(
            pool,
            "GET",
            restrictions_url,
            params={"expand": "restrictions.group,restrictions.user"},
            headers=dict(settings_map.get("headers") or {}),
        )
        if r_resp is not None and int(getattr(r_resp, "status_code", 0) or 0) == 404:
            restricted_flag = False
        else:
            r_data = r_resp.json() if r_resp is not None else {}
            restricted, group_names, _user_count = _confluence_parse_read_restriction_groups(r_data)
            if not restricted:
                restricted_flag = False
            else:
                restricted_flag = True
                ext_ids = [_confluence_group_principal_key(name) for name in (group_names or [])]
                ext_ids = [key for key in ext_ids if key]
                mapped_gids = _resolve_connectors_helper("_resolve_tenant_group_ids_by_external_id")(
                    db,
                    tenant_id=tenant_id,
                    external_ids=ext_ids,
                )
                if mapped_gids:
                    ordered = sorted(mapped_gids, key=lambda value: str(value))
                    effective_access = {
                        "mode": "partial_members",
                        "partial_group_list": [str(group_id) for group_id in ordered],
                    }
                else:
                    effective_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}
                    fallback_used = True
    except Exception:
        effective_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}
        restricted_flag = None
        fallback_used = True

    with contextlib.suppress(Exception):
        from app.services.document_acl_provenance_service import build_document_acl_provenance

        acl_provenance = build_document_acl_provenance(
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

    updated_existing = int(
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

    if str(settings_map.get("ingest_method") or "") == "webui":
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
        doc = await _resolve_connectors_helper("_ingest_url_upload_request")(
            background_tasks=None,
            body=body,
            tenant_id=tenant_id,
            account_id=requested_by,
            db=db,
        )
    else:
        if not page_id:
            raise ValueError("missing page id")
        content_resp = await _confluence_request(
            pool,
            "GET",
            f"{settings_map.get('api_base')}/content/{page_id}",
            params={"expand": "body.view,version"},
            headers=dict(settings_map.get("headers") or {}),
        )
        content = content_resp.json() if content_resp is not None else {}
        body0 = content.get("body") if isinstance(content, dict) else None
        view0 = body0.get("view") if isinstance(body0, dict) else None
        view_value = view0.get("value") if isinstance(view0, dict) else None
        page_html = str(view_value or "")
        if not page_html.strip():
            raise ValueError("missing body.view.value")

        title_escaped = html.escape(title or "")
        base_tag = f'<base href="{html.escape(page_url)}" />' if page_url else ""
        full_html = (
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
        html_body = _resolve_connectors_helper("LocalHtmlIngestRequest")(
            html=full_html,
            source_url=page_url,
            dataset_id=run.dataset_id,
            filename=filename,
            parser_backend=str(settings_map.get("parser_backend") or "auto"),
            chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
            pipeline=settings_map.get("pipeline"),
        )
        doc = await _resolve_connectors_helper("_ingest_local_html_request")(
            background_tasks=None,
            body=html_body,
            tenant_id=tenant_id,
            account_id=requested_by,
            db=db,
            ingestion_kind="upload_url",
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
    db.add(
        _resolve_connectors_helper("ConnectorRunDocument")(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=doc.id,
            source_ref=(page_id or page_url)[:1000] or None,
            status="created",
        )
    )
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
    db.add(
        _resolve_connectors_helper("ConnectorRunDocument")(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=att_doc.id,
            source_ref=(attachment_id or download_url)[:1000] or None,
            status="created",
        )
    )
    return att_doc.id


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
    if (
        not settings_map.get("include_attachments")
        or not page_id
        or int(progress.get("attachments_processed") or 0) >= int(settings_map.get("max_total_attachments") or 0)
        or _confluence_space_run_cancelled(db, run=run)
    ):
        return {
            "attachments_processed": 0,
            "attachments_created": 0,
            "attachments_failed": 0,
            "attachments_skipped": 0,
            "failed": 0,
            "created_doc_ids": [],
        }

    remaining_total = int(settings_map.get("max_total_attachments") or 0) - int(progress.get("attachments_processed") or 0)
    per_page_limit = int(min(int(settings_map.get("max_attachments_per_page") or 0), max(0, remaining_total)))
    if per_page_limit <= 0:
        return {
            "attachments_processed": 0,
            "attachments_created": 0,
            "attachments_failed": 0,
            "attachments_skipped": 0,
            "failed": 0,
            "created_doc_ids": [],
        }

    try:
        att_resp = await _confluence_request(
            pool,
            "GET",
            f"{settings_map.get('api_base')}/content/{page_id}/child/attachment",
            params={"start": 0, "limit": per_page_limit},
            headers=dict(settings_map.get("headers") or {}),
        )
        att_data = att_resp.json() if att_resp is not None else {}
        att_refs = _confluence_extract_attachments(
            att_data if isinstance(att_data, dict) else {},
            link_base_fallback=str(link_base or settings_map.get("base_url") or ""),
            limit=per_page_limit,
        )
    except Exception as exc:  # noqa: BLE001
        run.stats = _resolve_connectors_helper("_append_connector_error")(
            dict(run.stats or {}),
            url=f"confluence_attachments:{page_id}",
            exc=exc,
        )
        return {
            "attachments_processed": 0,
            "attachments_created": 0,
            "attachments_failed": 1,
            "attachments_skipped": 0,
            "failed": 1,
            "created_doc_ids": [],
        }

    created_doc_ids: list[UUID] = []
    attachments_processed = 0
    attachments_created = 0
    attachments_failed = 0
    attachments_skipped = 0
    failed = 0

    for attachment_ref in att_refs:
        if (
            int(progress.get("attachments_processed") or 0) + attachments_processed
        ) >= int(settings_map.get("max_total_attachments") or 0):
            break
        if _confluence_space_run_cancelled(db, run=run):
            break

        attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
        filename = str(attachment_ref.get("filename") or "").strip()
        download_url = str(attachment_ref.get("download_url") or "").strip()
        attachments_processed += 1

        if not attachment_id or not download_url:
            attachments_skipped += 1
            continue

        ext = Path(filename).suffix.lower()
        if ext and ext not in settings.allowed_extensions_list:
            attachments_skipped += 1
            continue

        try:
            doc_id = await _ingest_single_confluence_attachment(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                page_id=page_id,
                title=str(page_info.get("title") or ""),
                page_url=str(page_info.get("page_url") or ""),
                attachment_ref=attachment_ref,
                effective_access=effective_access,
                acl_provenance=acl_provenance,
                settings_map=settings_map,
            )
            created_doc_ids.append(doc_id)
            attachments_created += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            attachments_failed += 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}),
                url=(download_url or attachment_id),
                exc=exc,
            )

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
        if int(progress.get("processed") or 0) >= int(settings_map.get("max_pages") or 0):
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
        last_modified = str(page_info.get("last_modified") or "")

        if str(settings_map.get("effective_mode") or "") == "incremental" and _should_skip_timestamp_boundary_item(
            item_id=page_id,
            item_timestamp=last_modified or None,
            cursor_timestamp=str(settings_map.get("cursor_last_modified") or ""),
            boundary_ids=set(settings_map.get("cursor_last_modified_ids") or set()),
        ):
            progress["skipped_boundary_duplicates"] = int(progress.get("skipped_boundary_duplicates") or 0) + 1
            _persist_confluence_space_progress(db, run=run, progress=progress)
            continue

        if last_modified:
            last_seen, ids_seen = _advance_timestamp_boundary(
                last_timestamp=progress.get("last_modified_seen"),
                boundary_ids=set(progress.get("last_modified_ids_seen") or set()),
                item_timestamp=last_modified,
                item_id=page_id,
            )
            progress["last_modified_seen"] = last_seen
            progress["last_modified_ids_seen"] = ids_seen

        if not page_url:
            progress["failed"] = int(progress.get("failed") or 0) + 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}),
                url=(page_id or title or "confluence_page"),
                exc=ValueError("missing page url"),
            )
            progress["processed"] = int(progress.get("processed") or 0) + 1
            _persist_confluence_space_progress(db, run=run, progress=progress)
            continue

        try:
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
        except Exception as exc:  # noqa: BLE001
            progress["failed"] = int(progress.get("failed") or 0) + 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=page_url, exc=exc)
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


def _soft_delete_missing_confluence_pages(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    settings_map: dict[str, Any],
    observed_page_ids: set[str],
) -> int:
    now = _resolve_connectors_helper("_now")()
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == run.dataset_id,
                DBDocument.archived_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "confluence_space")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["space_key"].astext == str(settings_map.get("space_key") or ""))  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == str(settings_map.get("base_url") or ""))  # type: ignore[attr-defined]
            .all()
        )
    except Exception:
        docs = (
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

    disabled = 0
    for doc in docs or []:
        meta = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != "confluence_space":
            continue
        if str(conn.get("space_key") or "") != str(settings_map.get("space_key") or ""):
            continue
        if str(conn.get("base_url") or "") != str(settings_map.get("base_url") or ""):
            continue
        page_id = str(conn.get("page_id") or "").strip()
        if not page_id or page_id in observed_page_ids:
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
