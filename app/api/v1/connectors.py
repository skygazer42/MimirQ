"""
Connector API (enterprise ingestion framework).

This is a minimal v1 implementation focused on:
- URL batch ingestion as the first connector
- Run tracking (status/stats/error)
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    ConfluenceSpaceConnectorConfig,
    ConnectorConfigCreateRequest,
    ConnectorConfigListResponse,
    ConnectorConfigOut,
    ConnectorConfigUpdateRequest,
    ConnectorInfo,
    ConnectorRunCreateRequest,
    ConnectorRunListResponse,
    ConnectorRunOut,
    ConnectorValidateRequest,
    ConnectorValidateResponse,
    DriveFilesConnectorConfig,
    GitHubRepoConnectorConfig,
    JiraProjectConnectorConfig,
    MinioBucketConnectorConfig,
    MySQLCatalogConnectorConfig,
    SQLServerCatalogConnectorConfig,
    UrlBatchConnectorConfig,
    WebCrawlConnectorConfig,
)
from app.api.utils.url_ingest import validate_url_for_ingest
from app.api.v1.documents import (
    LocalHtmlIngestRequest,
    UrlUploadRequest,
    _ingest_local_html_request,
    _ingest_url_upload_request,
    _normalize_datetime_utc_iso,
    _resolve_writable_dataset,
)
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.http_client import get_http_client_pool
from app.core.secrets import decrypt_connector_config_secrets, encrypt_connector_config_secrets, redact_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.connector_config import ConnectorConfig
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.group_permissions import DocumentGroupPermission
from app.models.tenant_group import TenantGroup
from app.services.audit_log_service import audit_log_event
from app.services.connector_reconcile_service import (
    plan_connector_reconcile,
    resolve_connector_reconcile_source_refs,
)
from app.services.connector_registry import get_connector_definition, list_connector_definitions
from app.services.connector_sync_state import (
    build_persisted_state,
    build_saved_state_snapshot,
    get_resume_cursor,
    normalize_boundary_ids,
    normalize_source_manifest,
    slice_items_from_cursor,
)
from app.services.dataset_service import DatasetService
from app.services.document_permission_service import DocumentGroupPermissionService, DocumentPermissionService
from app.services.security_redaction import redact_connection_info
from app.services.web_crawler import crawl_site
from app.tasks.queue import enqueue_connector_run, get_queue

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
_DB_CONNECTOR_IDS = {"mysql_catalog", "sqlserver_catalog"}
URL_SHA256_PREFIX = "url_sha256:"
CONNECTOR_CONFIG_NOT_FOUND_DETAIL = "Connector config not found"
JIRA_UPDATED_SOURCE = "connector:jira:updated"
UNSUPPORTED_CONNECTOR_ID_DETAIL = "Unsupported connector_id"
URL_INGEST_DISABLED_DETAIL = "URL ingestion is disabled"
CONNECTOR_RUN_NOT_FOUND_DETAIL = "Connector run not found"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_http_or_https_url(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        return False
    return bool(str(parsed.netloc or "").strip())


def _is_link_href_allowed(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme in {"http", "https"}:
        return bool(str(parsed.netloc or "").strip())
    if scheme == "mailto":
        return bool(str(parsed.path or "").strip())
    return False


def _safe_error_str(exc: Exception) -> str:
    msg = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    if not msg:
        msg = exc.__class__.__name__
    if len(msg) > 200:
        msg = msg[:200]
    return msg


def _classify_connector_error(exc: Exception) -> tuple[str, str]:
    """
    Best-effort error classifier for connector runs.

    The goal is to group similar failures for UI/operator visibility; it is not used for control flow.
    """
    if isinstance(exc, HTTPException):
        detail = str(getattr(exc, "detail", "") or "").strip()
        msg = (detail or f"HTTP {getattr(exc, 'status_code', 0)}").replace("\r", " ").replace("\n", " ").strip()
        msg = msg[:200] if len(msg) > 200 else msg
        code = f"http_{getattr(exc, 'status_code', 0)}"
        lowered = msg.lower()
        if "not allowed" in lowered or "private ip" in lowered or "ssrf" in lowered:
            code = "ssrf"
        elif "timeout" in lowered:
            code = "timeout"
        elif getattr(exc, "status_code", None) == 413:
            code = "too_large"
        elif getattr(exc, "status_code", None) == 400:
            code = "bad_request"
        return code, msg

    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout", _safe_error_str(exc) or "timeout"

    msg = _safe_error_str(exc)
    lowered = msg.lower()
    if "timeout" in lowered:
        return "timeout", msg
    if "not allowed" in lowered or "private ip" in lowered or "ssrf" in lowered:
        return "ssrf", msg
    return "error", msg


def _append_connector_error(stats: dict, *, url: str, exc: Exception) -> dict:
    code, msg = _classify_connector_error(exc)

    # Sample errors (bounded) for UI quick display.
    errs = stats.get("errors")
    if not isinstance(errs, list):
        errs = []
    if len(errs) < 20:
        errs.append({"url": url, "code": code, "error": msg})
    stats["errors"] = errs

    failed_urls = stats.get("failed_urls")
    if not isinstance(failed_urls, list):
        failed_urls = []
    if url and url not in failed_urls:
        failed_urls.append(url)
    stats["failed_urls"] = failed_urls

    groups = stats.get("error_groups")
    if not isinstance(groups, list):
        groups = []
    key = f"{code}:{msg}"
    group = None
    for it in groups:
        if isinstance(it, dict) and str(it.get("key") or "") == key:
            group = it
            break
    if group is None:
        group = {"key": key, "code": code, "error": msg, "count": 0, "sample_urls": []}
        groups.append(group)
    group["count"] = int(group.get("count", 0) or 0) + 1
    sample_urls = group.get("sample_urls")
    if not isinstance(sample_urls, list):
        sample_urls = []
    if url and url not in sample_urls and len(sample_urls) < 3:
        sample_urls.append(url)
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

        groups_sorted = sorted(groups, key=_count, reverse=True)
        # Keep `key` for stable grouping across incremental updates, but it is optional for the UI.
        stats["error_groups"] = groups_sorted
    return stats


def _connector_run_completion_status(*, created: int, failed: int) -> str:
    if failed and created == 0:
        return "failed"
    return "completed"


def _connector_config_id_from_run(run: ConnectorRun) -> str | None:
    stats = dict(getattr(run, "stats", {}) or {})
    text = str(stats.get("config_id") or "").strip()
    return text or None


def _apply_connector_identity_metadata(
    *,
    doc: Any,
    run: ConnectorRun,
    connector_id: str,
    source_ref: str | None,
    source_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    meta0 = dict(getattr(doc, "doc_metadata", None) or {})
    connector_meta = dict(meta0.get("connector") or {})
    if isinstance(extra, dict):
        connector_meta.update({key: value for key, value in extra.items() if value is not None})

    connector_meta["connector_id"] = str(connector_id or "").strip()
    connector_meta["run_id"] = str(run.id)
    if getattr(run, "dataset_id", None) is not None:
        connector_meta["dataset_id"] = str(run.dataset_id)

    config_id = _connector_config_id_from_run(run)
    if config_id:
        connector_meta["config_id"] = config_id

    source_ref_norm = str(source_ref or "").strip()[:1000] or None
    source_id_norm = str(source_id or source_ref_norm or "").strip()[:1000] or None
    if source_ref_norm is not None:
        connector_meta["source_ref"] = source_ref_norm
    if source_id_norm is not None:
        connector_meta["source_id"] = source_id_norm

    meta0["connector"] = connector_meta
    doc.doc_metadata = meta0


def _web_crawl_content_fingerprint(
    *,
    url: str,
    crawl_sync_token: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    body_sha256: str | None = None,
) -> str:
    """
    Build a stable content-aware token for web crawl incremental manifests.

    Priority:
    1) crawler-provided sync token (already content-derived)
    2) etag / last-modified / body hash tuple
    3) url hash fallback
    """
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
    return any(m in raw for m in markers)


def _web_crawl_manifest_token_changed(*, existing_token: str | None, discovered_token: str | None) -> bool:
    existing = str(existing_token or "").strip()
    discovered = str(discovered_token or "").strip()
    if not existing:
        return True
    if not discovered:
        return False
    if existing == discovered:
        return False
    # Backward compatibility: legacy manifests used opaque URL hashes without explicit markers.
    # Treat them as presence-only for one migration run.
    if not _web_crawl_token_is_content_aware(existing):
        return False
    # If this run only has a weak URL-hash fallback token, avoid false-positive "changed" decisions.
    if discovered.startswith(URL_SHA256_PREFIX) and not existing.startswith(URL_SHA256_PREFIX):
        return False
    return True


def _web_crawl_extract_token_part(token: str | None, *, key: str) -> str | None:
    raw = str(token or "").strip()
    k = str(key or "").strip()
    if not raw or not k:
        return None
    pat = re.compile(rf"(?:^|\|){re.escape(k)}:([^|]+)")
    m = pat.search(raw)
    if not m:
        return None
    out = str(m.group(1) or "").strip()
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

    # Preserve crawler content_type marker when available.
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


def _db_row_sidecar_file_path(*, dataset_id: UUID, connector_id: str) -> str:
    return f"virtual://db_catalog/rows/{str(dataset_id)}/{str(connector_id or '').strip()}"


def _db_row_sidecar_filename(*, dataset_id: UUID, connector_id: str) -> str:
    ds = str(dataset_id)
    cid = str(connector_id or "").strip() or "db_catalog"
    return f"db_rows_{cid}_{ds}.sqlite"


def _build_db_row_source_manifest(snapshots: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for snap in snapshots or []:
        if not isinstance(snap, dict):
            continue
        source_table = str(snap.get("source_table") or "").strip()
        sync_token = str(snap.get("source_sync_token") or "").strip()
        if not source_table or not sync_token:
            continue
        out[source_table] = sync_token
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def _upsert_db_row_sidecar_document(
    *,
    db: Session,
    run: ConnectorRun,
    connector_id: str,
    requested_by: str,
    snapshots: list[dict[str, Any]],
    max_tables: int,
    max_rows_per_table: int,
    max_cols: int,
) -> dict[str, Any] | None:
    if run.dataset_id is None:
        return None
    if not snapshots:
        return None

    from app.services.table_store_service import import_db_row_snapshots

    now = _now()
    file_path = _db_row_sidecar_file_path(dataset_id=run.dataset_id, connector_id=connector_id)
    filename = _db_row_sidecar_filename(dataset_id=run.dataset_id, connector_id=connector_id)

    doc = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == run.tenant_id,
            DBDocument.dataset_id == run.dataset_id,
            DBDocument.file_path == file_path,
        )
        .first()
    )
    if doc is None:
        doc = DBDocument(
            tenant_id=run.tenant_id,
            dataset_id=run.dataset_id,
            filename=filename,
            file_type="dbrows",
            file_size=0,
            file_path=file_path,
            owner_id=(requested_by or None),
            access_mode="inherit",
            status="completed",
            processing_progress=100,
            current_stage="completed",
            error_message=None,
            chunk_count=0,
            total_characters=0,
            doc_metadata={},
            processed_at=now,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

    assets = import_db_row_snapshots(
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        document_id=doc.id,
        snapshots=snapshots,
        max_tables=max_tables,
        max_rows_per_table=max_rows_per_table,
        max_cols=max_cols,
        sample_rows=int(getattr(settings, "TABLE_STORE_SAMPLE_ROWS", 20) or 20),
    )

    tables_payload: list[dict[str, Any]] = []
    for a in assets:
        tables_payload.append(
            {
                "table_id": str(getattr(a, "table_id", "")),
                "sheet_index": int(getattr(a, "sheet_index", 0) or 0),
                "sheet_name": getattr(a, "sheet_name", None),
                "row_count": int(getattr(a, "row_count", 0) or 0),
                "col_count": int(getattr(a, "col_count", 0) or 0),
                "truncated": bool(getattr(a, "truncated", False)),
                "columns": list(getattr(a, "columns", None) or []),
                "sample_rows": list(getattr(a, "sample_rows", None) or []),
                "row_source_table": getattr(a, "row_source_table", None),
                "row_source_sync_token": getattr(a, "row_source_sync_token", None),
                "row_source_pk_hash_col": getattr(a, "row_source_pk_hash_col", None),
            }
        )

    meta = dict(getattr(doc, "doc_metadata", None) or {})
    meta["table_store"] = {
        "version": "1",
        "source_ext": ".dbrows",
        "imported_at": now.isoformat(),
        "tables": tables_payload,
    }
    doc.filename = filename
    doc.file_type = "dbrows"
    doc.file_path = file_path
    doc.status = "completed"
    doc.processing_progress = 100
    doc.current_stage = "completed"
    doc.error_message = None
    doc.chunk_count = 0
    doc.total_characters = 0
    doc.processed_at = now
    doc.doc_metadata = meta
    _apply_connector_identity_metadata(
        doc=doc,
        run=run,
        connector_id=connector_id,
        source_ref=f"db_catalog_rows:{connector_id}",
        source_id=f"{connector_id}:{run.dataset_id}",
        extra={"doc_kind": "db_row_sidecar"},
    )
    try:
        doc.file_size = int(len(json.dumps(meta, ensure_ascii=False)))
    except Exception:
        doc.file_size = 0
    db.commit()
    db.refresh(doc)

    linked = (
        db.query(ConnectorRunDocument)
        .filter(
            ConnectorRunDocument.tenant_id == run.tenant_id,
            ConnectorRunDocument.run_id == run.id,
            ConnectorRunDocument.document_id == doc.id,
        )
        .first()
    )
    if linked is None:
        db.add(
            ConnectorRunDocument(
                tenant_id=run.tenant_id,
                run_id=run.id,
                document_id=doc.id,
                source_ref=f"db_catalog_rows:{connector_id}",
                status="created",
            )
        )
        db.commit()

    return {
        "document_id": str(doc.id),
        "tables": int(len(assets)),
        "source_manifest_count": int(len(_build_db_row_source_manifest(snapshots))),
    }


def _unknown_tenant_groups(db: Session, *, tenant_id: UUID, group_ids: list[UUID]) -> list[str]:
    ids: list[UUID] = []
    seen: set[UUID] = set()
    for gid in group_ids or []:
        if gid in seen:
            continue
        seen.add(gid)
        ids.append(gid)
        if len(ids) >= 200:
            break

    if not ids:
        return []

    rows = (
        db.query(TenantGroup.id)
        .filter(
            TenantGroup.tenant_id == tenant_id,
            TenantGroup.id.in_(ids),
        )
        .all()
    )
    found = {row[0] for row in rows if row and row[0]}
    return [str(gid) for gid in ids if gid not in found]


def _normalize_doc_access_mode(value: object) -> str:
    """
    Normalize document access_mode to stable strings.

    - NULL / "" / "inherit" -> "inherit"
    """
    mode = str(value or "").strip().lower()
    if not mode or mode == "inherit":
        return "inherit"
    return mode


def _fetch_connector_run_acl_summaries(
    db: Session,
    *,
    tenant_id: UUID,
    run_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    """
    Fetch a lightweight per-run ACL summary for connector-created documents.

    Privacy:
    - returns counts only (no member ids / group ids)
    """
    if not run_ids:
        return {}

    # Dedupe but preserve order (avoid pathological IN lists).
    seen: set[UUID] = set()
    normalized_run_ids: list[UUID] = []
    for rid in run_ids:
        if rid in seen:
            continue
        seen.add(rid)
        normalized_run_ids.append(rid)

    # 1) Access mode distribution across docs created by each run.
    mode_counts: dict[UUID, dict[str, int]] = {}
    rows = (
        db.query(ConnectorRunDocument.run_id, DBDocument.access_mode, func.count(DBDocument.id))
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
        )
        .group_by(ConnectorRunDocument.run_id, DBDocument.access_mode)
        .all()
    )
    for run_id, access_mode, count in rows:
        mode = _normalize_doc_access_mode(access_mode)
        by = mode_counts.setdefault(run_id, {})
        by[mode] = int(by.get(mode, 0)) + int(count or 0)

    # 2) Allowlist member counts for docs in partial_members mode (per-doc stats aggregated to run).
    partial_member_counts_per_doc = (
        db.query(
            ConnectorRunDocument.run_id.label("run_id"),
            ConnectorRunDocument.document_id.label("document_id"),
            func.count(DocumentPermission.id).label("allowlist_count"),
        )
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .outerjoin(
            DocumentPermission,
            and_(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.document_id == ConnectorRunDocument.document_id,
            ),
        )
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
            func.lower(DBDocument.access_mode) == "partial_members",
        )
        .group_by(ConnectorRunDocument.run_id, ConnectorRunDocument.document_id)
        .subquery()
    )
    member_stats_rows = (
        db.query(
            partial_member_counts_per_doc.c.run_id,
            func.count(partial_member_counts_per_doc.c.document_id).label("doc_count"),
            func.min(partial_member_counts_per_doc.c.allowlist_count).label("min_count"),
            func.max(partial_member_counts_per_doc.c.allowlist_count).label("max_count"),
        )
        .group_by(partial_member_counts_per_doc.c.run_id)
        .all()
    )
    member_stats_by_run: dict[UUID, dict[str, int]] = {}
    for run_id, doc_count, min_count, max_count in member_stats_rows:
        member_stats_by_run[run_id] = {
            "partial_members_doc_count": int(doc_count or 0),
            "partial_member_count_min": int(min_count or 0),
            "partial_member_count_max": int(max_count or 0),
        }

    # 3) Allowlist group counts (partial_members docs only).
    partial_group_counts_per_doc = (
        db.query(
            ConnectorRunDocument.run_id.label("run_id"),
            ConnectorRunDocument.document_id.label("document_id"),
            func.count(DocumentGroupPermission.id).label("allowlist_count"),
        )
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .outerjoin(
            DocumentGroupPermission,
            and_(
                DocumentGroupPermission.tenant_id == tenant_id,
                DocumentGroupPermission.document_id == ConnectorRunDocument.document_id,
            ),
        )
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
            func.lower(DBDocument.access_mode) == "partial_members",
        )
        .group_by(ConnectorRunDocument.run_id, ConnectorRunDocument.document_id)
        .subquery()
    )
    group_stats_rows = (
        db.query(
            partial_group_counts_per_doc.c.run_id,
            func.min(partial_group_counts_per_doc.c.allowlist_count).label("min_count"),
            func.max(partial_group_counts_per_doc.c.allowlist_count).label("max_count"),
        )
        .group_by(partial_group_counts_per_doc.c.run_id)
        .all()
    )
    group_stats_by_run: dict[UUID, dict[str, int]] = {}
    for run_id, min_count, max_count in group_stats_rows:
        group_stats_by_run[run_id] = {
            "partial_group_count_min": int(min_count or 0),
            "partial_group_count_max": int(max_count or 0),
        }

    out: dict[UUID, dict[str, Any]] = {}
    for rid in normalized_run_ids:
        counts = mode_counts.get(rid, {})
        documents_total = sum(int(v or 0) for v in counts.values())
        if documents_total <= 0:
            continue

        distinct_modes = [m for m, v in counts.items() if int(v or 0) > 0]
        mode = distinct_modes[0] if len(distinct_modes) == 1 else "mixed"

        summary: dict[str, Any] = {
            "mode": mode,
            "documents_total": int(documents_total),
            "access_mode_counts": counts,
        }

        partial_docs = int(counts.get("partial_members", 0) or 0)
        if partial_docs > 0:
            summary["partial_members_doc_count"] = int(partial_docs)

        summary.update(member_stats_by_run.get(rid, {}))
        summary.update(group_stats_by_run.get(rid, {}))

        out[rid] = summary

    return out


def _run_out(run: ConnectorRun, *, acl_summary: dict[str, Any] | None = None) -> ConnectorRunOut:
    docs = getattr(run, "documents", None) or []
    connector_id = str(getattr(run, "connector_id", "") or "").strip()
    config = redact_secrets(dict(run.config or {}))
    config = redact_connection_info(config, enabled=connector_id in _DB_CONNECTOR_IDS)
    return ConnectorRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        requested_by=(run.requested_by or None),
        status=str(run.status or "pending"),  # type: ignore[arg-type]
        config=config,
        stats=dict(run.stats or {}),
        error_message=(run.error_message or None),
        task_id=(run.task_id or None),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        acl_summary=(acl_summary or None),
        documents=[
            {
                "document_id": d.document_id,
                "source_ref": (d.source_ref or None),
                "status": str(d.status or "created"),
            }
            for d in docs
        ],
    )


def _config_out(cfg: ConnectorConfig) -> ConnectorConfigOut:
    connector_id = str(cfg.connector_id or "").strip()
    config = redact_secrets(dict(cfg.config or {}))
    config = redact_connection_info(config, enabled=connector_id in _DB_CONNECTOR_IDS)
    return ConnectorConfigOut(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=connector_id,
        name=str(cfg.name or ""),
        enabled=bool(cfg.enabled),
        schedule_cron=(str(cfg.schedule_cron).strip() if isinstance(cfg.schedule_cron, str) and cfg.schedule_cron.strip() else None),
        config=config,
        state=dict(cfg.state or {}),
        last_run_at=(cfg.last_run_at or None),
        last_error=(cfg.last_error or None),
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


def _schedule_due(*, schedule: str, now: datetime, last_run_at: datetime | None) -> bool:
    """
    Best-effort cron-like evaluator for the scheduled tick hook.

    Supported (minimal) formats:
      - "@hourly" / "@daily" / "@weekly" / "@monthly"
      - "*/N * * * *" (every N minutes)
      - "0 */N * * *" (every N hours, at minute 0)
      - "0 0 */N * *" (every N days, at 00:00)

    Unknown formats are treated as not-due.
    """
    s = str(schedule or "").strip().lower()
    if not s:
        return False

    def _elapsed_sec() -> float:
        if last_run_at is None:
            # Never ran -> due.
            return 10**18
        try:
            return (now - last_run_at).total_seconds()
        except Exception:
            return 10**18

    if s in {"@hourly"}:
        return _elapsed_sec() >= 60 * 60
    if s in {"@daily"}:
        return _elapsed_sec() >= 60 * 60 * 24
    if s in {"@weekly"}:
        return _elapsed_sec() >= 60 * 60 * 24 * 7
    if s in {"@monthly"}:
        # Best-effort: treat month as 30 days.
        return _elapsed_sec() >= 60 * 60 * 24 * 30

    parts = s.split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts

        # Every N minutes.
        if minute.startswith("*/") and hour == "*" and day == "*" and month == "*" and dow == "*":
            raw = minute[2:]
            try:
                n = max(1, int(raw))
            except Exception:
                return False
            return _elapsed_sec() >= 60 * n

        # Every N hours (at minute 0).
        if minute == "0" and hour.startswith("*/") and day == "*" and month == "*" and dow == "*":
            raw = hour[2:]
            try:
                n = max(1, int(raw))
            except Exception:
                return False
            return _elapsed_sec() >= 60 * 60 * n

        # Every N days (at 00:00).
        if minute == "0" and hour == "0" and day.startswith("*/") and month == "*" and dow == "*":
            raw = day[2:]
            try:
                n = max(1, int(raw))
            except Exception:
                return False
            return _elapsed_sec() >= 60 * 60 * 24 * n

    return False


def _sync_connector_config_from_run(db: Session, *, run: ConnectorRun) -> None:
    """
    Best-effort: persist connector run outcomes back to the originating connector config.

    - last_error reflects the latest run outcome
    - state can store incremental cursors (connector-specific)
    """
    stats = dict(getattr(run, "stats", None) or {})
    raw_cfg_id = stats.get("config_id")
    cfg_id_str = str(raw_cfg_id or "").strip() if isinstance(raw_cfg_id, (str, UUID)) else ""
    if not cfg_id_str:
        return
    try:
        cfg_uuid = UUID(cfg_id_str)
    except Exception:
        return

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == cfg_uuid, ConnectorConfig.tenant_id == run.tenant_id)
        .first()
    )
    if cfg is None:
        return

    status = str(getattr(run, "status", "") or "").lower()
    cfg.last_error = None if status == "completed" else (str(getattr(run, "error_message", "") or status)[:200] or status)  # type: ignore[assignment]
    cfg.last_run_at = (getattr(run, "started_at", None) or getattr(run, "finished_at", None) or _now())  # type: ignore[assignment]

    connector_id = str(getattr(run, "connector_id", "") or "").strip()
    cfg.state = build_saved_state_snapshot(  # type: ignore[assignment]
        connector_id=connector_id,
        existing_state=dict(getattr(cfg, "state", None) or {}),
        stats=stats,
        run_id=run.id,
        run_status=status,
        recorded_at=(getattr(run, "finished_at", None) or getattr(run, "started_at", None) or _now()),
    )

    with contextlib.suppress(Exception):
        from app.services.audit_log_service import audit_log_event

        state = dict(getattr(cfg, "state", None) or {})
        state_audit = state.get("state_audit") if isinstance(state.get("state_audit"), dict) else {}
        audit_log_event(
            db,
            tenant_id=cfg.tenant_id,
            actor_id=(getattr(run, "requested_by", None) or None),
            action="connector_config.state.sync",
            resource_type="connector_config",
            resource_id=str(cfg.id),
            details={
                "config_id": str(cfg.id),
                "connector_id": connector_id,
                "run_id": str(run.id),
                "status": status,
                "schema_version": int(state.get("state_schema_version") or 0),
                "revision": int(state.get("state_revision") or 0),
                "updated_keys": list(state_audit.get("updated_keys") or []),
            },
        )

    db.commit()


@router.get("", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_connectors() -> list[ConnectorInfo]:
    """List available connectors from the shared registry."""
    return [
        ConnectorInfo(
            id=definition.connector_id,
            name=definition.name,
            description=definition.description,
            supports_incremental=definition.supports_incremental,
            supports_resume=definition.supports_resume,
            supports_full_reconcile=definition.supports_full_reconcile,
            sync_cursor_kind=definition.sync_cursor_kind,
        )
        for definition in list_connector_definitions()
    ]


def _format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    """
    Convert Pydantic ValidationError into a JSON-safe, UI-friendly list.
    """
    out: list[dict[str, Any]] = []
    for e in exc.errors() or []:
        out.append(
            {
                "loc": e.get("loc"),
                "msg": e.get("msg"),
                "type": e.get("type"),
            }
        )
        if len(out) >= 50:
            break
    return out or [{"msg": "invalid config"}]


def _validate_connector_schema(connector_id: str, config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    connector_id = str(connector_id or "").strip()
    cfg_obj: Any
    if connector_id == "url_batch":
        cfg_obj = UrlBatchConnectorConfig.model_validate(config or {})
    elif connector_id == "web_crawl":
        cfg_obj = WebCrawlConnectorConfig.model_validate(config or {})
    elif connector_id == "github_repo":
        cfg_obj = GitHubRepoConnectorConfig.model_validate(config or {})
    elif connector_id == "drive_files":
        cfg_obj = DriveFilesConnectorConfig.model_validate(config or {})
    elif connector_id == "minio_bucket":
        cfg_obj = MinioBucketConnectorConfig.model_validate(config or {})
    elif connector_id == "confluence_space":
        cfg_obj = ConfluenceSpaceConnectorConfig.model_validate(config or {})
    elif connector_id == "jira_project":
        cfg_obj = JiraProjectConnectorConfig.model_validate(config or {})
    elif connector_id == "mysql_catalog":
        cfg_obj = MySQLCatalogConnectorConfig.model_validate(config or {})
    elif connector_id == "sqlserver_catalog":
        cfg_obj = SQLServerCatalogConnectorConfig.model_validate(config or {})
    else:
        raise ValueError(UNSUPPORTED_CONNECTOR_ID_DETAIL)

    # Use JSON mode to ensure the output is JSON-serializable (UUIDs, datetimes, etc.).
    cfg_dict = cfg_obj.model_dump(mode="json", exclude_none=True)
    return cfg_obj, cfg_dict


async def _best_effort_connectivity_checks(*, connector_id: str, cfg: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Run bounded, best-effort connectivity checks.

    These checks are designed to be safe:
    - No large downloads
    - No redirects (SSRF defense-in-depth)
    - Fail-open (warnings) unless schema is invalid
    """
    checks: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []

    cid = str(connector_id or "").strip()
    if cid == "url_batch":
        urls = list(getattr(cfg, "urls", None) or [])
        checked: list[dict[str, Any]] = []
        ok = 0
        for raw in urls[:3]:
            url = str(raw or "").strip()
            if not url:
                continue
            try:
                normalized = await validate_url_for_ingest(url)
                checked.append({"url": url, "ok": True, "normalized_url": normalized})
                ok += 1
            except HTTPException as exc:
                checked.append({"url": url, "ok": False, "error": str(getattr(exc, "detail", "") or "")[:200]})
                warnings.append({"code": "url_invalid", "url": url, "error": str(getattr(exc, "detail", "") or "")[:200]})
            except Exception as exc:  # noqa: BLE001
                checked.append({"url": url, "ok": False, "error": _safe_error_str(exc)})
                warnings.append({"code": "url_check_error", "url": url, "error": _safe_error_str(exc)})
        checks["url_ingest"] = {"checked": checked, "ok": ok == len(checked) if checked else True}

    elif cid == "web_crawl":
        start_urls = list(getattr(cfg, "start_urls", None) or [])
        checked: list[dict[str, Any]] = []
        ok = 0
        for raw in start_urls[:3]:
            url = str(raw or "").strip()
            if not url:
                continue
            try:
                normalized = await validate_url_for_ingest(url)
                checked.append({"url": url, "ok": True, "normalized_url": normalized})
                ok += 1
            except HTTPException as exc:
                checked.append({"url": url, "ok": False, "error": str(getattr(exc, "detail", "") or "")[:200]})
                warnings.append({"code": "start_url_invalid", "url": url, "error": str(getattr(exc, "detail", "") or "")[:200]})
            except Exception as exc:  # noqa: BLE001
                checked.append({"url": url, "ok": False, "error": _safe_error_str(exc)})
                warnings.append({"code": "start_url_check_error", "url": url, "error": _safe_error_str(exc)})
        checks["url_ingest"] = {"checked": checked, "ok": ok == len(checked) if checked else True}

    elif cid == "jira_project":
        checks["jira_project"] = {
            "ok": bool(str(getattr(cfg, "base_url", "") or "").strip() and str(getattr(cfg, "project_key", "") or "").strip()),
            "base_url": str(getattr(cfg, "base_url", "") or "").strip(),
            "project_key": str(getattr(cfg, "project_key", "") or "").strip(),
        }

    elif cid in _DB_CONNECTOR_IDS:
        # Patchable helper for unit tests; best-effort, fail-open warnings.
        db_check, db_warn = await _check_db_connectivity_best_effort(connector_id=cid, cfg=cfg)
        checks["db_connectivity"] = db_check
        warnings.extend(db_warn)

    return checks, warnings


def _has_write_privileges_from_text(text: str) -> bool:
    t = str(text or "").lower()
    if not t:
        return False
    # Intentionally coarse: any write-ish privilege triggers a warning.
    tokens = [
        "all privileges",
        "insert",
        "update",
        "delete",
        "create",
        "drop",
        "alter",
        "grant",
        "super",
        "owner",
        "control",
        "take ownership",
    ]
    return any(tok in t for tok in tokens)


def _mysql_connectivity_check_sync(cfg: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import time

    warnings: list[dict[str, Any]] = []
    check: dict[str, Any] = {"ok": False, "latency_ms": None, "read_only": None}

    try:
        import pymysql

        t0 = time.time()
        conn = pymysql.connect(
            host=str(getattr(cfg, "host", "") or "").strip(),
            port=int(getattr(cfg, "port", 3306) or 3306),
            user=str(getattr(cfg, "username", "") or "").strip(),
            password=str(getattr(cfg, "password", "") or ""),
            database=str(getattr(cfg, "database", "") or "").strip(),
            connect_timeout=3,
            read_timeout=3,
            write_timeout=3,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            check["ok"] = True
            check["latency_ms"] = round((time.time() - t0) * 1000.0, 1)

            # Best-effort: warn if the user appears to have write privileges.
            try:
                grants_text = ""
                with conn.cursor() as cur:
                    cur.execute("SHOW GRANTS")
                    rows = cur.fetchall() or []
                parts: list[str] = []
                for row in rows:
                    if not row:
                        continue
                    parts.append(str(row[0] or ""))
                    if len(parts) >= 20:
                        break
                grants_text = "\n".join(parts)
                has_write = _has_write_privileges_from_text(grants_text)
                check["read_only"] = not has_write
                if has_write:
                    warnings.append(
                        {
                            "code": "db_write_privileges_detected",
                            "message": "DB user appears to have write privileges; consider using a read-only account.",
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                check["read_only"] = None
                warnings.append({"code": "db_read_only_check_error", "error": _safe_error_str(exc)})
        finally:
            with contextlib.suppress(Exception):
                conn.close()
    except Exception as exc:  # noqa: BLE001
        check["ok"] = False
        check["error"] = _safe_error_str(exc)
        warnings.append({"code": "db_connectivity_failed", "error": _safe_error_str(exc)})

    return check, warnings


def _sqlserver_connectivity_check_sync(cfg: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import time

    warnings: list[dict[str, Any]] = []
    check: dict[str, Any] = {"ok": False, "latency_ms": None, "read_only": None}

    try:
        import pyodbc

        # Try a reasonable default driver first; fall back to any installed driver.
        preferred = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
        ]
        installed = list(pyodbc.drivers() or [])
        driver = None
        for cand in preferred:
            if cand in installed:
                driver = cand
                break
        if not driver and installed:
            driver = installed[-1]
        if not driver:
            raise RuntimeError("No SQL Server ODBC driver found")

        host = str(getattr(cfg, "host", "") or "").strip()
        port = int(getattr(cfg, "port", 1433) or 1433)
        database = str(getattr(cfg, "database", "") or "").strip()
        username = str(getattr(cfg, "username", "") or "").strip()
        password = str(getattr(cfg, "password", "") or "")

        # Best-effort TLS defaults; operator can override at runtime by patching this helper.
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={host},{port};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )

        t0 = time.time()
        conn = pyodbc.connect(conn_str, timeout=3)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            check["ok"] = True
            check["latency_ms"] = round((time.time() - t0) * 1000.0, 1)

            # Best-effort: warn if user has write-ish permissions at DB scope.
            try:
                cur = conn.cursor()
                cur.execute("SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE')")
                perms = [str(r[0] or "") for r in (cur.fetchall() or []) if r and r[0]]
                perms_text = "\n".join(perms[:200])
                has_write = _has_write_privileges_from_text(perms_text)
                check["read_only"] = not has_write
                if has_write:
                    warnings.append(
                        {
                            "code": "db_write_privileges_detected",
                            "message": "DB user appears to have write privileges; consider using a read-only account.",
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                check["read_only"] = None
                warnings.append({"code": "db_read_only_check_error", "error": _safe_error_str(exc)})
        finally:
            with contextlib.suppress(Exception):
                conn.close()
    except Exception as exc:  # noqa: BLE001
        check["ok"] = False
        check["error"] = _safe_error_str(exc)
        warnings.append({"code": "db_connectivity_failed", "error": _safe_error_str(exc)})

    return check, warnings


async def _check_db_connectivity_best_effort(*, connector_id: str, cfg: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Patchable DB connectivity check helper for validate endpoint.

    Unit tests should monkeypatch this function to avoid real outbound DB calls.
    """

    cid = str(connector_id or "").strip()
    if cid == "mysql_catalog":
        return await asyncio.to_thread(_mysql_connectivity_check_sync, cfg)
    if cid == "sqlserver_catalog":
        return await asyncio.to_thread(_sqlserver_connectivity_check_sync, cfg)
    return {}, []


@router.post("/validate", response_model=ConnectorValidateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def validate_connector_config(
    payload: ConnectorValidateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Validate connector config (best-effort).

    Returns ok/errors/warnings so UIs can surface issues without throwing hard 4xx/5xx on validation.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    connector_id = str(payload.connector_id or "").strip()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    cfg_obj: Any | None = None
    cfg_dict: dict[str, Any] = {}
    try:
        cfg_obj, cfg_dict = _validate_connector_schema(connector_id, dict(payload.config or {}))
        checks["schema"] = {"ok": True}
    except ValidationError as exc:
        errors = _format_validation_error(exc)
        checks["schema"] = {"ok": False}
    except Exception as exc:  # noqa: BLE001
        errors = [{"msg": _safe_error_str(exc)}]
        checks["schema"] = {"ok": False}

    config_out = redact_secrets(dict(cfg_dict or {}))
    config_out = redact_connection_info(config_out, enabled=connector_id in _DB_CONNECTOR_IDS)

    if not errors and cfg_obj is not None:
        # Validate group allowlist existence (fail-closed) for connector access config.
        access = getattr(cfg_obj, "access", None)
        group_ids = list(getattr(access, "partial_group_list", None) or [])
        if group_ids:
            missing = _unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=group_ids)
            if missing:
                errors.append(
                    {
                        "loc": ("access", "partial_group_list"),
                        "msg": f"Unknown tenant groups: {', '.join(missing[:20])}",
                        "type": "value_error",
                    }
                )
                checks["access_groups"] = {"ok": False, "missing": missing[:20], "total_missing": len(missing)}
            else:
                checks["access_groups"] = {"ok": True, "count": len(group_ids)}

        # Validate tenant group ids referenced by source ACL mapping config (connector-level).
        source_acl = getattr(cfg_obj, "source_acl", None)
        rules = list(getattr(source_acl, "group_mappings", None) or [])
        source_acl_group_ids = [getattr(r, "group_id", None) for r in rules]
        source_acl_group_ids = [gid for gid in source_acl_group_ids if gid]
        if source_acl_group_ids:
            missing = _unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=source_acl_group_ids)
            if missing:
                errors.append(
                    {
                        "loc": ("source_acl", "group_mappings"),
                        "msg": f"Unknown tenant groups: {', '.join(missing[:20])}",
                        "type": "value_error",
                    }
                )
                checks["source_acl_groups"] = {"ok": False, "missing": missing[:20], "total_missing": len(missing)}
            else:
                checks["source_acl_groups"] = {"ok": True, "count": len(source_acl_group_ids)}

    if not errors and bool(payload.check_connectivity) and cfg_obj is not None:
        more_checks, more_warnings = await _best_effort_connectivity_checks(connector_id=connector_id, cfg=cfg_obj)
        checks.update(more_checks)
        warnings.extend(more_warnings)

    return ConnectorValidateResponse(
        ok=not bool(errors),
        connector_id=connector_id,
        config=config_out,
        errors=errors,
        warnings=warnings,
        checks=checks,
    )


def _execute_db_catalog_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for DB catalog connectors (MySQL / SQLServer).

    Notes:
    - This first iteration runs in-process (FastAPI BackgroundTasks).
    - DB network calls are intentionally stubbed inside app.connectors.db.catalog_runner.
    """
    db = SessionLocal()
    try:
        import time

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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        with contextlib.suppress(Exception):
            db.refresh(run)

        from app.connectors.db.catalog_runner import run_catalog_sync
        from app.connectors.db.catalog_store_sqlalchemy import SqlAlchemyCatalogStore

        connector_id = str(run.connector_id or "").strip()
        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)
        stats = dict(run.stats or {})
        cfg_id = stats.get("config_id")
        connector_config_id: UUID | None = None
        try:
            if cfg_id:
                connector_config_id = UUID(str(cfg_id))
        except Exception:
            connector_config_id = None
        store = SqlAlchemyCatalogStore(db=db)
        from app.services.metrics_logger import metrics_context

        with metrics_context(
            tenant_id=tenant_id,
            account_id=requested_by,
            dataset_id=str(run.dataset_id),
            connector_id=connector_id,
            connector_run_id=str(run_id),
        ):
            t0_sync = time.time()
            result = run_catalog_sync(
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id=connector_id,
                config=dict(cfg or {}),
                store=store,
                connector_config_id=connector_config_id,
            )
            sync_elapsed = time.time() - t0_sync

            try:
                import app.services.db_catalog_observability as obs

                obs.emit_db_catalog_sync_completed(
                    tenant_id=str(tenant_id),
                    dataset_id=str(run.dataset_id),
                    run_id=str(run_id),
                    connector_id=connector_id,
                    elapsed_sec=float(sync_elapsed),
                    result=dict(result or {}),
                )
            except Exception:
                # Metrics are best-effort; do not affect connector execution.
                pass

            # Task 7: build digest-only "virtual schema document" so retrieval can
            # directly hit table/field knowledge (no raw rows).
            try:
                from app.services.db_catalog_schema_doc_service import upsert_and_index_virtual_schema_doc

                t0_doc = time.time()
                schema_doc = upsert_and_index_virtual_schema_doc(
                    db=db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    requested_by=requested_by,
                    connector_run_id=run_id,
                )
                doc_elapsed = time.time() - t0_doc
                if isinstance(schema_doc, dict):
                    schema_doc.setdefault("elapsed_sec", float(doc_elapsed))
                    stats["schema_doc"] = schema_doc
                    try:
                        import app.services.db_catalog_observability as obs

                        obs.emit_db_catalog_schema_doc_completed(
                            tenant_id=str(tenant_id),
                            dataset_id=str(run.dataset_id),
                            run_id=str(run_id),
                            connector_id=connector_id,
                            elapsed_sec=float(doc_elapsed),
                            document_id=str(schema_doc.get("document_id") or ""),
                            chunks=int(schema_doc.get("chunks") or 0),
                            tables=int(schema_doc.get("tables") or 0),
                            catalog_last_seen_at=(
                                schema_doc.get("catalog_last_seen_at") if isinstance(schema_doc, dict) else None
                            ),
                            catalog_age_sec=(schema_doc.get("catalog_age_sec") if isinstance(schema_doc, dict) else None),
                        )
                    except Exception:
                        pass
            except Exception as exc:  # noqa: BLE001
                # Best-effort only: catalog sync success should not depend on indexing infra.
                stats["schema_doc_error"] = _safe_error_str(exc)

            # Optional: bounded row snapshots for TAG recall.
            try:
                row_sync_global = bool(getattr(settings, "DB_CATALOG_ROW_SYNC_ENABLED", False))
                row_sync_local = bool(cfg.get("row_sync_enabled"))
                row_sync_enabled = bool(row_sync_global and row_sync_local)
                stats["row_sync_enabled"] = bool(row_sync_enabled)
                if row_sync_enabled:
                    from app.connectors.db.catalog_runner import extract_row_snapshots

                    max_tables = int(cfg.get("row_sync_max_tables") or getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_TABLES", 20) or 20)
                    max_rows = int(
                        cfg.get("row_sync_max_rows_per_table")
                        or getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE", 50)
                        or 50
                    )
                    max_cols = int(cfg.get("row_sync_max_cols") or getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_COLS", 50) or 50)
                    snapshots = extract_row_snapshots(
                        tenant_id=tenant_id,
                        dataset_id=run.dataset_id,
                        connector_id=connector_id,
                        config=dict(cfg or {}),
                        max_tables=max_tables,
                        max_rows_per_table=max_rows,
                        max_cols=max_cols,
                    )
                    source_manifest = _build_db_row_source_manifest(snapshots)
                    stats["total_tables"] = int(len(snapshots))
                    stats["source_manifest"] = source_manifest

                    sidecar = _upsert_db_row_sidecar_document(
                        db=db,
                        run=run,
                        connector_id=connector_id,
                        requested_by=requested_by,
                        snapshots=snapshots,
                        max_tables=max_tables,
                        max_rows_per_table=max_rows,
                        max_cols=max_cols,
                    )
                    if isinstance(sidecar, dict):
                        stats["row_sidecar"] = sidecar
            except Exception as exc:  # noqa: BLE001
                stats["row_sync_error"] = _safe_error_str(exc)

        stats.update({"result": dict(result or {})})
        # Best-effort audit log (do not block connector execution).
        try:
            from app.services.audit_log_service import audit_log_event

            schema_doc = stats.get("schema_doc") if isinstance(stats, dict) else None
            diff = schema_doc.get("schema_diff") if isinstance(schema_doc, dict) else None
            diff_counts = None
            if isinstance(diff, dict):
                diff_counts = {
                    "tables_added": int(((diff.get("tables_added") or {}) if isinstance(diff.get("tables_added"), dict) else {}).get("count") or 0),
                    "tables_removed": int(((diff.get("tables_removed") or {}) if isinstance(diff.get("tables_removed"), dict) else {}).get("count") or 0),
                    "columns_added": int(((diff.get("columns_added") or {}) if isinstance(diff.get("columns_added"), dict) else {}).get("count") or 0),
                    "columns_removed": int(((diff.get("columns_removed") or {}) if isinstance(diff.get("columns_removed"), dict) else {}).get("count") or 0),
                    "columns_changed": int(((diff.get("columns_changed") or {}) if isinstance(diff.get("columns_changed"), dict) else {}).get("count") or 0),
                }

            audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=requested_by,
                action="db_catalog.sync.completed",
                resource_type="connector_run",
                resource_id=str(run_id),
                details={
                    "dataset_id": str(run.dataset_id),
                    "connector_id": connector_id,
                    "config_id": (str(stats.get("config_id")) if stats.get("config_id") is not None else None),
                    "result": dict(result or {}),
                    "schema_doc_id": (str(schema_doc.get("document_id")) if isinstance(schema_doc, dict) and schema_doc.get("document_id") else None),
                    "schema_diff_counts": diff_counts,
                },
            )
        except Exception:
            pass
        run.stats = _finalize_connector_stats(stats)
        run.status = "completed"
        run.finished_at = _now()
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        # Best-effort: avoid raising from background tasks (keep request path stable).
        with contextlib.suppress(Exception):
            import app.services.db_catalog_observability as obs

            obs.emit_db_catalog_sync_failed(
                tenant_id=str(tenant_id),
                dataset_id=str(getattr(run, "dataset_id", "") or ""),
                run_id=str(run_id),
                connector_id=str(getattr(run, "connector_id", "") or ""),
                elapsed_sec=0.0,
                error=_safe_error_str(exc),
            )
        with contextlib.suppress(Exception):
            from app.services.audit_log_service import audit_log_event

            audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=requested_by,
                action="db_catalog.sync.failed",
                resource_type="connector_run",
                resource_id=str(run_id),
                details={
                    "dataset_id": (str(getattr(run, "dataset_id", "") or "") if run is not None else None),
                    "connector_id": str(getattr(run, "connector_id", "") or ""),
                    "error": _safe_error_str(exc),
                },
            )
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = _safe_error_str(exc)
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
            db.rollback()
    finally:
        db.close()


async def _execute_url_batch_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for url_batch connector.

    Notes:
    - Runs in API process (FastAPI BackgroundTasks). If TASK_QUEUE is enabled, document processing is queued;
      otherwise documents are processed inline (async) within this background task.
    """
    db = SessionLocal()
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
        if run.started_at is None:
            run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)
        urls = cfg.get("urls") if isinstance(cfg.get("urls"), list) else []
        urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
        filename = cfg.get("filename") if isinstance(cfg.get("filename"), str) else None
        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None

        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        access_members = access.get("partial_member_list") if isinstance(access, dict) else None
        if not isinstance(access_members, list):
            access_members = []
        access_members = [str(v).strip() for v in access_members if isinstance(v, (str, int, float)) and str(v).strip()]
        access_groups = access.get("partial_group_list") if isinstance(access, dict) else None
        if not isinstance(access_groups, list):
            access_groups = []
        access_groups = [str(v).strip() for v in access_groups if isinstance(v, (str, int, float)) and str(v).strip()]

        auth_headers = _build_auth_headers(cfg)

        processed_refs: set[str] = set()
        for d in (getattr(run, "documents", None) or []):
            ref = str(getattr(d, "source_ref", "") or "").strip()
            if ref:
                processed_refs.add(ref)

        stats0 = dict(run.stats or {})
        cursor_raw = stats0.get("cursor", stats0.get("processed_urls", 0))
        try:
            cursor0 = max(0, int(cursor_raw or 0))
        except Exception:
            cursor0 = 0

        # Resume-friendly defaults: don't reset progress if the run already has stats.
        stats0.setdefault("total_urls", int(len(urls)))
        stats0.setdefault("processed_urls", int(cursor0))
        stats0.setdefault("cursor", int(cursor0))
        stats0.setdefault("failed_urls", [])
        stats0.setdefault("errors", [])
        stats0.setdefault("error_groups", [])

        raw_doc_ids = stats0.get("document_ids")
        created_doc_ids: list[str] = []
        if isinstance(raw_doc_ids, list):
            created_doc_ids = [str(v).strip() for v in raw_doc_ids if str(v).strip()]
        if not created_doc_ids:
            created_doc_ids = [str(getattr(d, "document_id", "") or "") for d in (getattr(run, "documents", None) or [])]
            created_doc_ids = [v for v in created_doc_ids if v]
        stats0["document_ids"] = created_doc_ids

        def _safe_int(value: object, default: int = 0) -> int:
            try:
                return int(value or 0)
            except Exception:
                return int(default)

        created = _safe_int(stats0.get("created"), default=len(created_doc_ids))
        failed = _safe_int(stats0.get("failed"), default=0)
        stats0.setdefault("created", int(created))
        stats0.setdefault("failed", int(failed))

        run.stats = stats0
        db.commit()

        # Iterate from cursor0 but still skip URLs that already have a mapping row.
        start_idx = max(0, min(int(cursor0), len(urls)))
        for idx in range(start_idx, len(urls)):
            url = urls[idx]
            # Observe cancellation from another DB session (best-effort).
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            try:
                if url in processed_refs:
                    continue
                body = UrlUploadRequest(
                    url=url,
                    dataset_id=run.dataset_id,
                    filename=filename,
                    fetch_headers=auth_headers or None,
                    user_agent=user_agent,
                    parser_backend=parser_backend,
                    chunk_strategy=chunk_strategy,
                    pipeline=pipeline,  # type: ignore[arg-type]
                )
                doc = await _ingest_url_upload_request(
                    background_tasks=None,
                    body=body,
                    tenant_id=tenant_id,
                    account_id=requested_by,
                    db=db,
                )

                _apply_document_access_from_config(
                    db,
                    tenant_id=tenant_id,
                    requested_by=requested_by,
                    doc=doc,
                    access={
                        "mode": access_mode,
                        "partial_member_list": list(access_members),
                        "partial_group_list": list(access_groups),
                    },
                    connector_id="url_batch",
                )
                _apply_connector_identity_metadata(
                    doc=doc,
                    run=run,
                    connector_id="url_batch",
                    source_ref=url,
                    source_id=url,
                )

                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        document_id=doc.id,
                        source_ref=url,
                        status="created",
                    )
                )
                created += 1
                created_doc_ids.append(str(doc.id))
                processed_refs.add(url)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=url, exc=exc)
                run.stats = stats
            finally:
                processed = idx + 1
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "total_urls": int(len(urls)),
                        "processed_urls": int(processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
                        "document_ids": list(created_doc_ids),
                    }
                )
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        # Finalize status (don't override cancellation).
        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


def _build_auth_headers(cfg: dict) -> dict[str, str]:
    auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else None
    if not isinstance(auth, dict):
        return {}
    t = str(auth.get("type") or "none").strip().lower()
    if t == "cookie":
        cookie = str(auth.get("cookie") or "").strip()
        return {"Cookie": cookie} if cookie else {}
    if t == "bearer":
        token = str(auth.get("token") or "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}
    if t == "basic":
        import base64

        username = str(auth.get("username") or "").strip()
        password = str(auth.get("password") or "").strip()
        if not username or not password:
            return {}
        raw = f"{username}:{password}".encode("utf-8", "ignore")
        b64 = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {b64}"}
    return {}


_DRIVE_FILE_ID_FROM_PATH_RE = re.compile(r"/file/d/([^/]+)")


def _extract_drive_file_id(url: str) -> str | None:
    """
    Extract Google Drive file id from common share link formats.

    Supported:
    - https://drive.google.com/file/d/<id>/view
    - https://drive.google.com/open?id=<id>
    - https://drive.google.com/uc?id=<id>
    """
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    host = (parsed.netloc or "").strip().lower()
    if host not in {"drive.google.com", "docs.google.com"}:
        return None

    qs = parse_qs(parsed.query or "")
    if "id" in qs and qs["id"]:
        fid = str(qs["id"][0] or "").strip()
        return fid or None

    m = _DRIVE_FILE_ID_FROM_PATH_RE.search(parsed.path or "")
    if m:
        fid = str(m.group(1) or "").strip()
        return fid or None
    return None


def _drive_direct_download_url(file_id: str) -> str:
    fid = str(file_id or "").strip()
    if not fid:
        raise ValueError("drive_file_id_required")
    # Best-effort; may still require auth/cookie for non-public files.
    return f"https://drive.google.com/uc?export=download&id={fid}"


def _drive_source_ref(*, file_id: str | None, source_url: str) -> str:
    """
    Build a stable source_ref for Drive incremental manifests.

    Prefer `file_id` for stability across share-link variants.
    """
    fid = str(file_id or "").strip()
    if fid:
        return fid

    raw_url = str(source_url or "").strip()
    digest = hashlib.sha256(raw_url.encode("utf-8", "ignore")).hexdigest()
    return f"url:{digest}"


def _drive_fallback_sync_token(*, file_id: str | None, source_url: str) -> str:
    """
    Best-effort fallback token when Drive metadata cursor fields are unavailable.
    """
    fid = str(file_id or "").strip()
    raw_url = str(source_url or "").strip()
    seed = f"file_id:{fid}|url:{raw_url}"
    digest = hashlib.sha256(seed.encode("utf-8", "ignore")).hexdigest()
    return f"hash:{digest}"


async def _drive_fetch_file_sync_token(
    *,
    client: httpx.AsyncClient | None,
    file_id: str,
    source_url: str,
    headers: dict[str, str] | None = None,
) -> str:
    """
    Build a Drive file sync token for incremental freshness.

    Priority:
    1) version + modifiedTime + fileId from Drive API metadata.
    2) fallback hash derived from url/file_id.
    """
    fid = str(file_id or "").strip()
    fallback = _drive_fallback_sync_token(file_id=fid, source_url=source_url)
    if not fid or client is None:
        return fallback

    url = f"https://www.googleapis.com/drive/v3/files/{quote(fid, safe='')}"
    params = {
        "fields": "id,version,modifiedTime",
        "supportsAllDrives": "true",
    }
    try:
        resp = await client.get(url, params=params, headers=dict(headers or {}))
        if int(resp.status_code or 0) >= 400:
            return fallback
        payload = resp.json() if callable(getattr(resp, "json", None)) else {}
    except Exception:
        return fallback

    data = payload if isinstance(payload, dict) else {}
    version = str(data.get("version") or "").strip()
    modified_time = str(data.get("modifiedTime") or "").strip()
    resolved_file_id = str(data.get("id") or fid).strip() or fid
    if not version and not modified_time:
        return fallback

    parts: list[str] = []
    if version:
        parts.append(f"version:{version}")
    if modified_time:
        parts.append(f"modified_time:{modified_time}")
    parts.append(f"file_id:{resolved_file_id}")
    return "|".join(parts)


def _drive_group_principal_key(email: str) -> str:
    """
    Build a stable source principal key for a Google Drive group permission.

    Format (bounded to TenantGroup.external_id max_length=255):
      drive:group:<email>
    """
    e = str(email or "").strip().lower()
    if not e:
        return ""
    return f"drive:group:{e}"[:255]


async def _drive_fetch_file_permissions(
    *,
    client: httpx.AsyncClient,
    file_id: str,
    headers: dict[str, str],
    max_items: int = 500,
) -> list[dict[str, Any]]:
    """
    Best-effort: fetch Drive file permissions via Google Drive API v3.

    Notes:
    - Requires OAuth bearer token with appropriate scopes (e.g., drive.readonly).
    - Caller should treat failures as "unknown" and fail-closed if ACL inheritance is enabled.
    """
    fid = str(file_id or "").strip()
    if not fid:
        return []

    url = f"https://www.googleapis.com/drive/v3/files/{quote(fid, safe='')}/permissions"
    params = {
        "fields": "permissions(type,role,emailAddress,domain,deleted)",
        # Some environments need this for shared drives; harmless otherwise.
        "supportsAllDrives": "true",
    }
    resp = await client.get(url, params=params, headers=headers)
    if int(resp.status_code or 0) >= 400:
        raise RuntimeError(f"drive api failed (status={resp.status_code})")

    data = resp.json()
    perms = data.get("permissions") if isinstance(data, dict) else None
    items = perms if isinstance(perms, list) else []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(dict(it))
        if max_items and len(out) >= max_items:
            break
    return out


def _github_raw_url(*, owner: str, repo: str, branch: str, path: str) -> str:
    """
    Build a raw.githubusercontent.com URL for a file path.
    """
    o = str(owner or "").strip()
    r = str(repo or "").strip()
    b = str(branch or "").strip() or "main"
    p = str(path or "").lstrip("/").strip()
    if not o or not r or not p:
        raise ValueError("invalid_github_raw_url_parts")
    return f"https://raw.githubusercontent.com/{o}/{r}/{quote(b, safe='')}/{quote(p, safe='/')}"  # noqa: E501


def _github_team_principal_key(*, org: str, team_slug: str) -> str:
    """
    Build a stable source principal key for a GitHub org team.

    Format (bounded to TenantGroup.external_id max_length=255):
      github:team:<org>/<slug>
    """
    o = str(org or "").strip()
    s = str(team_slug or "").strip()
    if not o or not s:
        return ""
    key = f"github:team:{o.lower()}/{s.lower()}"
    return key[:255]


def _parse_link_header_next(link_header: str | None) -> str | None:
    """
    Best-effort parse GitHub-style RFC5988 Link header for rel="next".
    """
    raw = str(link_header or "").strip()
    if not raw:
        return None
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        if 'rel="next"' not in p and "rel=next" not in p:
            continue
        # Format: <url>; rel="next"
        if "<" in p and ">" in p:
            start = p.find("<")
            end = p.find(">", start + 1)
            if start >= 0 and end > start:
                candidate = p[start + 1 : end].strip()
                return candidate or None
    return None


async def _github_fetch_repo_team_principal_keys(
    *,
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    headers: dict[str, str],
    max_pages: int = 3,
    max_items: int = 200,
) -> list[str]:
    """
    Best-effort: list org teams with access to a repo and return stable principal keys.

    Notes:
    - GitHub requires authentication + org permissions (read:org) for this endpoint.
    - Fail-open at fetch level (return empty list on errors) but downstream mapping should fail-closed.
    """
    o = str(owner or "").strip()
    r = str(repo or "").strip()
    if not o or not r:
        return []

    url = f"https://api.github.com/repos/{quote(o, safe='')}/{quote(r, safe='')}/teams?per_page=100"
    out: list[str] = []
    seen: set[str] = set()

    for _page in range(max(1, min(int(max_pages or 0), 10))):
        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            return out
        data = resp.json()
        items = data if isinstance(data, list) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            slug = str(it.get("slug") or "").strip()
            org_obj = it.get("organization")
            org_login = ""
            if isinstance(org_obj, dict):
                org_login = str(org_obj.get("login") or "").strip()
            if not org_login:
                org_login = o
            key = _github_team_principal_key(org=org_login, team_slug=slug)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
            if max_items and len(out) >= max_items:
                return out

        link = None
        with contextlib.suppress(Exception):
            link = resp.headers.get("Link")
        next_url = _parse_link_header_next(link)
        if not next_url:
            break
        url = next_url

    return out


def _resolve_tenant_group_ids_by_external_id(
    db: Session,
    *,
    tenant_id: UUID,
    external_ids: list[str],
    max_items: int = 200,
) -> set[UUID]:
    """
    Resolve tenant group ids by external_id (tenant-scoped).
    """
    ids: list[str] = []
    seen: set[str] = set()
    for raw in external_ids or []:
        ext = str(raw or "").strip()
        if not ext or ext in seen:
            continue
        seen.add(ext)
        # TenantGroup.external_id max_length is 255.
        ids.append(ext[:255])
        if max_items and len(ids) >= max_items:
            break

    if not ids:
        return set()

    rows = (
        db.query(TenantGroup.id)
        .filter(
            TenantGroup.tenant_id == tenant_id,
            TenantGroup.external_id.in_(ids),
        )
        .all()
    )
    return {row[0] for row in rows if row and row[0]}


async def _execute_web_crawl_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for web_crawl connector.

    Flow:
    - Crawl start_urls and discover links (bounded by max_pages/max_depth)
    - Ingest each discovered URL using the existing /documents/upload-url path
    """
    db = SessionLocal()
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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)

        start_urls = cfg.get("start_urls") if isinstance(cfg.get("start_urls"), list) else []
        start_urls = [str(u or "").strip() for u in start_urls if str(u or "").strip()]
        max_pages = int(cfg.get("max_pages") or 50)
        max_depth = int(cfg.get("max_depth") or 3)
        same_host_only = bool(cfg.get("same_host_only", True))
        include_patterns = cfg.get("include_patterns") if isinstance(cfg.get("include_patterns"), list) else []
        exclude_patterns = cfg.get("exclude_patterns") if isinstance(cfg.get("exclude_patterns"), list) else []
        use_sitemaps = bool(cfg.get("use_sitemaps", False))
        sitemap_urls = cfg.get("sitemap_urls") if isinstance(cfg.get("sitemap_urls"), list) else []
        respect_robots = bool(cfg.get("respect_robots", False))
        dedup_canonical = bool(cfg.get("dedup_canonical", True))
        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None

        filename = cfg.get("filename") if isinstance(cfg.get("filename"), str) else None
        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None

        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        access_members = access.get("partial_member_list") if isinstance(access, dict) else None
        if not isinstance(access_members, list):
            access_members = []
        access_members = [str(v).strip() for v in access_members if isinstance(v, (str, int, float)) and str(v).strip()]
        access_groups = access.get("partial_group_list") if isinstance(access, dict) else None
        if not isinstance(access_groups, list):
            access_groups = []
        access_groups = [str(v).strip() for v in access_groups if isinstance(v, (str, int, float)) and str(v).strip()]

        auth_headers = _build_auth_headers(cfg)

        crawl = await crawl_site(
            start_urls=start_urls,
            max_pages=max_pages,
            max_depth=max_depth,
            same_host_only=same_host_only,
            include_patterns=[str(p or "") for p in include_patterns if str(p or "").strip()],
            exclude_patterns=[str(p or "") for p in exclude_patterns if str(p or "").strip()],
            use_sitemaps=use_sitemaps,
            sitemap_urls=[str(u or "") for u in sitemap_urls if str(u or "").strip()],
            respect_robots=respect_robots,
            dedup_canonical=dedup_canonical,
            headers=auth_headers,
            user_agent=user_agent,
            timeout_sec=float(getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0) or 30.0),
            max_bytes=int(getattr(settings, "URL_INGEST_MAX_BYTES", 0) or settings.MAX_FILE_SIZE),
            follow_redirects=bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False)),
        )

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []
        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        existing_manifest = normalize_source_manifest(state.get("source_manifest"))
        crawl_sync_tokens = getattr(crawl, "sync_tokens", None)
        crawl_sync_tokens = crawl_sync_tokens if isinstance(crawl_sync_tokens, dict) else {}
        discovered_manifest = _web_crawl_source_manifest(
            [str(url or "").strip() for url in (crawl.urls or []) if str(url or "").strip()],
            sync_tokens={str(k): str(v) for k, v in crawl_sync_tokens.items()},
        )
        discovered_urls = list(discovered_manifest.keys())
        resume_cursor_raw = get_resume_cursor(state)
        is_resume_run = bool((run.stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
        effective_mode = "incremental" if existing_manifest else "full"
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
        removed_urls = sorted(set(existing_manifest) - set(discovered_manifest)) if effective_mode == "incremental" else []
        resume_cursor = resume_cursor_raw if (is_resume_run and effective_mode == "full") else 0
        crawl_urls, cursor_in = slice_items_from_cursor(delta_urls, cursor=resume_cursor)
        source_manifest_state = {
            url: str(discovered_manifest.get(url) or token)
            for url, token in existing_manifest.items()
            if url in discovered_manifest
        }
        skipped_unchanged = max(0, int(len(discovered_urls) - len(delta_urls)))
        processed_visible = skipped_unchanged + cursor_in
        removed_urls_reconciled = 0
        removed_documents_disabled = 0

        stats = dict(run.stats or {})
        stats.update(
            {
                "mode": effective_mode,
                "visited": int(crawl.visited),
                "queued": int(crawl.queued),
                "discovered": int(len(discovered_urls)),
                "total_urls": int(len(discovered_urls)),
                "delta_urls": int(len(delta_urls)),
                "skipped_unchanged": int(skipped_unchanged),
                "processed_urls": int(processed_visible),
                "cursor": int(cursor_in),
                "created": 0,
                "failed": 0,
                "failed_urls": [],
                "errors": [],
                "error_groups": [],
                "cursor_in": int(cursor_in),
                "resumed_from_state": bool(is_resume_run and ((effective_mode == "incremental") or cursor_in > 0)),
                "removed_paths": int(len(removed_urls)),
                "removed_paths_reconciled": 0,
                "removed_documents_disabled": 0,
                "source_manifest": dict(source_manifest_state),
            }
        )
        if crawl.errors:
            stats["crawl_errors"] = list(crawl.errors)[:20]
        run.stats = _finalize_connector_stats(stats)
        db.commit()

        for idx, url in enumerate(crawl_urls):
            # Observe cancellation from another DB session (best-effort).
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            succeeded = False
            ingested_doc = None
            try:
                body = UrlUploadRequest(
                    url=url,
                    dataset_id=run.dataset_id,
                    filename=filename,
                    fetch_headers=auth_headers or None,
                    user_agent=user_agent,
                    parser_backend=parser_backend,
                    chunk_strategy=chunk_strategy,
                    pipeline=pipeline,  # type: ignore[arg-type]
                )
                doc = await _ingest_url_upload_request(
                    background_tasks=None,
                    body=body,
                    tenant_id=tenant_id,
                    account_id=requested_by,
                    db=db,
                )
                ingested_doc = doc

                _apply_document_access_from_config(
                    db,
                    tenant_id=tenant_id,
                    requested_by=requested_by,
                    doc=doc,
                    access={
                        "mode": access_mode,
                        "partial_member_list": list(access_members),
                        "partial_group_list": list(access_groups),
                    },
                    connector_id="web_crawl",
                )
                _apply_connector_identity_metadata(
                    doc=doc,
                    run=run,
                    connector_id="web_crawl",
                    source_ref=url,
                    source_id=url,
                )

                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        document_id=doc.id,
                        source_ref=url,
                        status="created",
                    )
                )
                created += 1
                created_doc_ids.append(doc.id)
                succeeded = True
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=url, exc=exc)
                run.stats = stats
            finally:
                processed = cursor_in + idx + 1
                processed_visible = skipped_unchanged + processed
                if succeeded and url and url in discovered_manifest:
                    token = str(discovered_manifest.get(url) or "").strip()
                    if ingested_doc is not None:
                        with contextlib.suppress(Exception):
                            token = _web_crawl_build_doc_sync_token(
                                source_url=url,
                                doc=ingested_doc,
                                crawl_token=token,
                            )
                    source_manifest_state[url] = token or discovered_manifest[url]
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "mode": effective_mode,
                        "total_urls": int(len(discovered_urls)),
                        "delta_urls": int(len(delta_urls)),
                        "skipped_unchanged": int(skipped_unchanged),
                        "processed_urls": int(processed_visible),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
                        "removed_paths": int(len(removed_urls)),
                        "removed_paths_reconciled": int(removed_urls_reconciled),
                        "removed_documents_disabled": int(removed_documents_disabled),
                        "source_manifest": dict(source_manifest_state),
                        "document_ids": [str(d) for d in created_doc_ids],
                    }
                )
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        # Finalize status (don't override cancellation).
        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        if effective_mode == "incremental" and removed_urls:
            for source_url in removed_urls:
                try:
                    disabled = _soft_disable_connector_documents_by_source_url(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=run.dataset_id,
                        connector_id="web_crawl",
                        source_url=source_url,
                    )
                except Exception as exc:  # noqa: BLE001
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=source_url, exc=exc)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    continue
                removed_documents_disabled += int(disabled)
                if disabled:
                    removed_urls_reconciled += 1

        stats = dict(run.stats or {})
        stats.update(
            {
                "mode": effective_mode,
                "delta_urls": int(len(delta_urls)),
                "skipped_unchanged": int(skipped_unchanged),
                "removed_paths": int(len(removed_urls)),
                "removed_paths_reconciled": int(removed_urls_reconciled),
                "removed_documents_disabled": int(removed_documents_disabled),
                "source_manifest": dict(source_manifest_state),
                "document_ids": [str(d) for d in created_doc_ids],
            }
        )
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


def _apply_document_access_from_config(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    doc,  # noqa: ANN001
    access: dict | None,
    connector_id: str | None = None,
) -> None:
    """
    Apply optional document-level ACL overrides for connector-created docs.

    This is best-effort and does not affect pipeline_hash.
    """
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    access_members = access.get("partial_member_list") if isinstance(access, dict) else None
    if not isinstance(access_members, list):
        access_members = []
    access_members = [str(v).strip() for v in access_members if isinstance(v, (str, int, float)) and str(v).strip()]
    access_groups = access.get("partial_group_list") if isinstance(access, dict) else None
    if not isinstance(access_groups, list):
        access_groups = []
    access_groups = [str(v).strip() for v in access_groups if isinstance(v, (str, int, float)) and str(v).strip()]

    try:
        doc.access_mode = None if access_mode == "inherit" else access_mode
        if not (getattr(doc, "owner_id", None) or "").strip():
            doc.owner_id = requested_by

        if access_mode == "partial_members":
            DocumentPermissionService.update_partial_member_list(db, tenant_id, doc.id, list(access_members))
            DocumentGroupPermissionService.update_partial_group_list(db, tenant_id, doc.id, list(access_groups))
        else:
            DocumentPermissionService.clear_partial_member_list(db, tenant_id, doc.id)
            DocumentGroupPermissionService.clear_partial_group_list(db, tenant_id, doc.id)
    except Exception:
        with contextlib.suppress(Exception):
            from app.services.connector_acl_prometheus_metrics import observe_connector_acl_apply_error

            observe_connector_acl_apply_error(connector_id=connector_id, mode=access_mode)
        raise
    else:
        with contextlib.suppress(Exception):
            from app.services.connector_acl_prometheus_metrics import observe_connector_acl_apply

            observe_connector_acl_apply(
                connector_id=connector_id,
                mode=access_mode,
                member_count=len(access_members),
                group_count=len(access_groups),
            )


def _delta_sync_connector_documents_acl_by_source_url(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    connector_id: str,
    source_url: str,
    requested_by: str,
    access: dict | None,
    acl_provenance: dict | None,
    max_docs: int = 50_000,
) -> int:
    """
    Best-effort ACL delta sync for connector-managed documents (revoke/adjust access).

    This updates *existing* documents that were previously created by the same
    connector and have the same `documents.metadata.source_url`.

    Security:
    - We join against connector run tables to avoid touching manually-uploaded docs
      that happen to share the same source URL.
    - When source ACL changes, we re-apply the computed effective doc ACL to revoke
      access (fail-closed mapping already happens earlier).
    """
    if dataset_id is None:
        return 0
    source_url = str(source_url or "").strip()
    if not source_url:
        return 0

    # Query via joins to ensure "connector-managed" scope.
    q = (
        db.query(DBDocument)
        .join(ConnectorRunDocument, ConnectorRunDocument.document_id == DBDocument.id)
        .join(ConnectorRun, ConnectorRun.id == ConnectorRunDocument.run_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.dataset_id == dataset_id,
            ConnectorRun.connector_id == str(connector_id or "").strip(),
        )
        .filter(DBDocument.doc_metadata["source_url"].astext == source_url)  # type: ignore[attr-defined]
        .distinct()
        .order_by(DBDocument.created_at.desc())
    )

    max_docs = max(0, int(max_docs or 0))
    if max_docs:
        q = q.limit(max_docs)

    updated = 0
    for doc in q.yield_per(200):
        _apply_document_access_from_config(
            db,
            tenant_id=tenant_id,
            requested_by=requested_by,
            doc=doc,
            access=access,
            connector_id=connector_id,
        )
        if isinstance(acl_provenance, dict):
            try:
                meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                meta0["acl_provenance"] = dict(acl_provenance)
                doc.doc_metadata = meta0
            except Exception:
                # Best-effort: never fail due to metadata patching.
                pass
        updated += 1

    return int(updated)


def _soft_disable_connector_documents_by_source_url(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    connector_id: str,
    source_url: str,
    connector_config_id: UUID | None = None,
    max_docs: int = 50_000,
) -> int:
    """
    Best-effort soft-disable for connector-managed documents matching a source URL.

    This intentionally mirrors the scope guard used by ACL delta sync so we only
    touch documents previously created by the same connector.
    """
    if dataset_id is None:
        return 0
    source_url = str(source_url or "").strip()
    if not source_url:
        return 0

    q = (
        db.query(DBDocument)
        .join(ConnectorRunDocument, ConnectorRunDocument.document_id == DBDocument.id)
        .join(ConnectorRun, ConnectorRun.id == ConnectorRunDocument.run_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.dataset_id == dataset_id,
            ConnectorRun.connector_id == str(connector_id or "").strip(),
        )
        .filter(DBDocument.doc_metadata["source_url"].astext == source_url)  # type: ignore[attr-defined]
        .distinct()
        .order_by(DBDocument.created_at.desc())
    )
    if connector_config_id is not None:
        q = q.filter(ConnectorRun.stats["config_id"].astext == str(connector_config_id))  # type: ignore[attr-defined]

    max_docs = max(0, int(max_docs or 0))
    if max_docs:
        q = q.limit(max_docs)

    now = _now()
    disabled = 0
    for doc in q.yield_per(200):
        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


def _soft_disable_connector_documents_by_source_ref(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    connector_id: str,
    source_ref: str,
    connector_config_id: UUID | None = None,
    exclude_document_id: UUID | None = None,
    max_docs: int = 50_000,
) -> int:
    """
    Best-effort soft-disable for connector-managed documents matching a connector-run `source_ref`.

    This is useful when the underlying ingest pipeline does not persist a stable `doc_metadata.source_url`
    across runs (e.g. presigned URLs).
    """
    if dataset_id is None:
        return 0
    source_ref = str(source_ref or "").strip()
    if not source_ref:
        return 0

    q = (
        db.query(DBDocument)
        .join(ConnectorRunDocument, ConnectorRunDocument.document_id == DBDocument.id)
        .join(ConnectorRun, ConnectorRun.id == ConnectorRunDocument.run_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.dataset_id == dataset_id,
            ConnectorRun.connector_id == str(connector_id or "").strip(),
            ConnectorRunDocument.source_ref == source_ref,
        )
        .distinct()
        .order_by(DBDocument.created_at.desc())
    )
    if connector_config_id is not None:
        q = q.filter(ConnectorRun.stats["config_id"].astext == str(connector_config_id))  # type: ignore[attr-defined]
    if exclude_document_id is not None:
        q = q.filter(DBDocument.id != exclude_document_id)

    max_docs = max(0, int(max_docs or 0))
    if max_docs:
        q = q.limit(max_docs)

    now = _now()
    disabled = 0
    for doc in q.yield_per(200):
        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


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
            _apply_document_access_from_config(
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
            _apply_document_access_from_config(
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


def _delta_sync_jira_documents_acl_by_issue_url(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    issue_url: str,
    requested_by: str,
    access: dict | None,
    acl_provenance: dict | None,
    max_docs_scan: int = 5000,
) -> int:
    """
    ACL delta sync for Jira documents by `(base_url, project_key, issue_url)`.

    This updates both the issue doc and any attachment docs for the same issue
    because attachments inherit the same effective access.
    """
    if dataset_id is None:
        return 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    issue_url = str(issue_url or "").strip()
    if not base_url or not project_key or not issue_url:
        return 0

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
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "jira_project")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["issue_url"].astext == issue_url)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
        )
        for doc in q.yield_per(200):
            _apply_document_access_from_config(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                connector_id="jira_project",
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
            if str(conn.get("connector_id") or "") != "jira_project":
                continue
            if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
                continue
            if str(conn.get("project_key") or "").strip().upper() != project_key:
                continue
            if str(conn.get("issue_url") or "").strip() != issue_url:
                continue
            _apply_document_access_from_config(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                connector_id="jira_project",
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


def _soft_disable_jira_attachment_documents_missing_from_issue(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    issue_url: str,
    seen_attachment_urls: set[str],
    max_docs_scan: int = 5000,
) -> int:
    """
    Best-effort soft-disable for Jira attachment docs missing from a processed issue.
    """
    if dataset_id is None:
        return 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    issue_url = str(issue_url or "").strip()
    seen_urls = {
        str(url or "").strip()
        for url in (seen_attachment_urls or set())
        if str(url or "").strip()
    }
    if not base_url or not project_key or not issue_url:
        return 0

    docs: list[Any]
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "jira_project")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["doc_kind"].astext == "attachment")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["issue_url"].astext == issue_url)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
            .all()
        )
    except Exception:
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

    now = _now()
    disabled = 0
    for doc in docs or []:
        meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != "jira_project":
            continue
        if str(conn.get("doc_kind") or "") != "attachment":
            continue
        if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
            continue
        if str(conn.get("project_key") or "").strip().upper() != project_key:
            continue
        if str(conn.get("issue_url") or "").strip() != issue_url:
            continue

        download_url = str(conn.get("download_url") or meta.get("source_url") or "").strip()
        if not download_url or download_url in seen_urls:
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


def _soft_disable_jira_linked_artifact_documents_missing_from_issue(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    issue_url: str,
    seen_link_urls: set[str],
    max_docs_scan: int = 5000,
) -> int:
    """
    Best-effort soft-disable for Jira linked-artifact docs missing from a processed issue.
    """
    if dataset_id is None:
        return 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    issue_url = str(issue_url or "").strip()
    seen_urls = {
        str(url or "").strip()
        for url in (seen_link_urls or set())
        if str(url or "").strip()
    }
    if not base_url or not project_key or not issue_url:
        return 0

    docs: list[Any]
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "jira_project")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["doc_kind"].astext == "linked_artifact")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["issue_url"].astext == issue_url)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
            .all()
        )
    except Exception:
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

    now = _now()
    disabled = 0
    for doc in docs or []:
        meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != "jira_project":
            continue
        if str(conn.get("doc_kind") or "") != "linked_artifact":
            continue
        if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
            continue
        if str(conn.get("project_key") or "").strip().upper() != project_key:
            continue
        if str(conn.get("issue_url") or "").strip() != issue_url:
            continue

        link_url = str(conn.get("link_url") or meta.get("source_url") or "").strip()
        if not link_url or link_url in seen_urls:
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


async def _execute_github_repo_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for github_repo connector.

    Flow:
    - List repository files via GitHub API (tree)
    - Ingest selected files via raw.githubusercontent.com URLs
    """
    db = SessionLocal()
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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)

        repo = str(cfg.get("repo") or "").strip()
        if "/" not in repo:
            raise ValueError("invalid repo")
        owner, repo_name = repo.split("/", 1)
        owner = owner.strip()
        repo_name = repo_name.strip()
        if not owner or not repo_name:
            raise ValueError("invalid repo")

        branch = str(cfg.get("branch") or "main").strip() or "main"
        max_files = int(cfg.get("max_files") or 50)
        include_exts = cfg.get("include_extensions") if isinstance(cfg.get("include_extensions"), list) else []
        include_exts = [str(e or "").strip().lower() for e in include_exts if str(e or "").strip()]
        include_exts = [("." + e if not e.startswith(".") else e) for e in include_exts]
        include_set = set(include_exts) if include_exts else {".md", ".txt"}

        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
        source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None

        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")

        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
        auth_headers = _build_auth_headers(cfg)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": (user_agent or "MimirQ/1.0 (+github_repo)"),
        }
        headers.update(auth_headers)

        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{quote(branch, safe='')}?recursive=1"
        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []
        delta_acl_docs_updated = 0
        delta_acl_sources_updated = 0
        removed_documents_disabled = 0
        removed_paths_reconciled = 0

        # Optional: source ACL inheritance (org teams -> tenant groups by external_id).
        source_acl_mode = str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
        source_acl_fallback_mode = str(source_acl.get("fallback_mode") or "partial_members").strip().lower() if isinstance(source_acl, dict) else "partial_members"
        enable_source_acl = bool(source_acl_mode == "inherit" and not has_manual_access_override)
        source_acl_access: dict | None = None
        team_principal_keys: list[str] = []
        mapped_group_ids: set[UUID] = set()
        source_acl_provenance: dict | None = None

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"github api failed (status={resp.status_code})")
            data = resp.json()

            if enable_source_acl:
                # Best-effort: this can fail due to missing org permissions; we still ingest but fail-closed.
                with contextlib.suppress(Exception):
                    team_principal_keys = await _github_fetch_repo_team_principal_keys(
                        client=client,
                        owner=owner,
                        repo=repo_name,
                        headers=headers,
                    )

        if enable_source_acl:
            with contextlib.suppress(Exception):
                mapped_group_ids = _resolve_tenant_group_ids_by_external_id(
                    db,
                    tenant_id=tenant_id,
                    external_ids=team_principal_keys,
                )
            if mapped_group_ids:
                ordered = sorted(mapped_group_ids, key=lambda v: str(v))
                source_acl_access = {
                    "mode": "partial_members",
                    "partial_group_list": [str(gid) for gid in ordered],
                }
            else:
                source_acl_access = {"mode": source_acl_fallback_mode}

            # Best-effort audit log (do not block connector execution).
            with contextlib.suppress(Exception):
                from app.services.audit_log_service import audit_log_event

                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=requested_by,
                    action="github_repo.source_acl.applied",
                    resource_type="connector_run",
                    resource_id=str(run_id),
                    details={
                        "dataset_id": str(run.dataset_id),
                        "connector_id": "github_repo",
                        "repo": repo,
                        "team_principal_count": int(len(team_principal_keys)),
                        "mapped_group_count": int(len(mapped_group_ids)),
                        "fallback_mode": source_acl_fallback_mode,
                    },
                )

            with contextlib.suppress(Exception):
                from app.services.document_acl_provenance_service import build_document_acl_provenance

                source_acl_provenance = build_document_acl_provenance(
                    connector_id="github_repo",
                    connector_run_id=str(run_id),
                    effective_access=source_acl_access,
                    source_acl_mode=source_acl_mode,
                    source_acl_fallback_mode=source_acl_fallback_mode,
                    source_principal_external_ids=team_principal_keys,
                    mapped_group_ids=mapped_group_ids,
                    fallback_used=not bool(mapped_group_ids),
                )

        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        existing_manifest = normalize_source_manifest(state.get("source_manifest"))
        tracked_paths = set(existing_manifest)
        resume_cursor_raw = get_resume_cursor(state)

        tree = data.get("tree")
        items = tree if isinstance(tree, list) else []
        files: list[tuple[str, str]] = []
        observed_tracked_paths: set[str] = set()
        max_files_bound = max(1, min(max_files, 200))
        for it in items:
            if not isinstance(it, dict):
                continue
            if str(it.get("type") or "") != "blob":
                continue
            p = str(it.get("path") or "").strip()
            if not p:
                continue
            sha = str(it.get("sha") or "").strip()
            if p in tracked_paths:
                observed_tracked_paths.add(p)
            ext = Path(p).suffix.lower()
            if ext and ext not in include_set:
                continue
            if not ext and "" not in include_set:
                continue
            if len(files) < max_files_bound:
                files.append((p, sha))

        is_resume_run = bool((run.stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
        effective_mode = "incremental" if existing_manifest else "full"
        delta_files: list[tuple[str, str]] = []
        skipped_unchanged = 0
        for path, blob_sha in files:
            if (not enable_source_acl) and effective_mode == "incremental" and existing_manifest.get(path) == blob_sha:
                skipped_unchanged += 1
                continue
            delta_files.append((path, blob_sha))

        removed_paths = sorted(tracked_paths - observed_tracked_paths) if effective_mode == "incremental" else []
        resume_cursor = resume_cursor_raw if (is_resume_run and effective_mode == "full") else 0
        files_to_process, cursor_in = slice_items_from_cursor(delta_files, cursor=resume_cursor)
        source_manifest_state = {path: sha for path, sha in existing_manifest.items() if path not in removed_paths}
        processed_visible = skipped_unchanged + cursor_in
        stats0 = dict(run.stats or {})
        stats0.update(
            {
                "mode": effective_mode,
                "total_files": int(len(files)),
                "delta_files": int(len(delta_files)),
                "skipped_unchanged": int(skipped_unchanged),
                "processed_files": int(processed_visible),
                "cursor": int(cursor_in),
                "created": 0,
                "failed": 0,
                "failed_paths": [],
                "cursor_in": int(cursor_in),
                "resumed_from_state": bool(is_resume_run and ((effective_mode == "incremental") or cursor_in > 0)),
                "removed_paths": int(len(removed_paths)),
                "removed_paths_reconciled": int(removed_paths_reconciled),
                "removed_documents_disabled": int(removed_documents_disabled),
                "source_manifest": dict(source_manifest_state),
            }
        )
        run.stats = stats0
        db.commit()

        for idx, item in enumerate(files_to_process):
            path, blob_sha = item if isinstance(item, tuple) else (str(item or ""), "")
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            try:
                raw_url = _github_raw_url(owner=owner, repo=repo_name, branch=branch, path=path)
                effective_access = access
                if not has_manual_access_override and isinstance(source_acl_access, dict):
                    effective_access = source_acl_access

                # Delta sync: update existing connector-managed docs for this URL so ACL changes
                # in the source system can revoke access (idempotent; fail-closed).
                if effective_access is source_acl_access and isinstance(source_acl_access, dict):
                    updated_existing = _delta_sync_connector_documents_acl_by_source_url(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=run.dataset_id,
                        connector_id="github_repo",
                        source_url=raw_url,
                        requested_by=requested_by,
                        access=effective_access,
                        acl_provenance=source_acl_provenance,
                    )
                    delta_acl_docs_updated += int(updated_existing)
                    if updated_existing:
                        delta_acl_sources_updated += 1

                body = UrlUploadRequest(
                    url=raw_url,
                    dataset_id=run.dataset_id,
                    filename=Path(path).name,
                    fetch_headers=auth_headers or None,
                    user_agent=user_agent,
                    parser_backend=str(parser_backend),
                    chunk_strategy=str(chunk_strategy),
                    pipeline=pipeline,  # type: ignore[arg-type]
                )
                doc = await _ingest_url_upload_request(
                    background_tasks=None,
                    body=body,
                    tenant_id=tenant_id,
                    account_id=requested_by,
                    db=db,
                )

                _apply_document_access_from_config(
                    db,
                    tenant_id=tenant_id,
                    requested_by=requested_by,
                    doc=doc,
                    access=effective_access,
                    connector_id="github_repo",
                )

                if effective_access is source_acl_access and isinstance(source_acl_provenance, dict):
                    with contextlib.suppress(Exception):
                        from app.services.document_acl_provenance_service import apply_document_acl_provenance

                        apply_document_acl_provenance(doc, provenance=source_acl_provenance)
                _apply_connector_identity_metadata(
                    doc=doc,
                    run=run,
                    connector_id="github_repo",
                    source_ref=path,
                    source_id=path,
                )

                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        document_id=doc.id,
                        source_ref=path,
                        status="created",
                    )
                )
                created += 1
                created_doc_ids.append(doc.id)
                if path and blob_sha:
                    source_manifest_state[path] = blob_sha
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=path, exc=exc)
                run.stats = stats
            finally:
                processed = cursor_in + idx + 1
                processed_visible = skipped_unchanged + processed
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "mode": effective_mode,
                        "total_files": int(len(files)),
                        "delta_files": int(len(delta_files)),
                        "skipped_unchanged": int(skipped_unchanged),
                        "processed_files": int(processed_visible),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
                        "document_ids": [str(d) for d in created_doc_ids],
                        "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                        "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
                        "removed_paths": int(len(removed_paths)),
                        "removed_paths_reconciled": int(removed_paths_reconciled),
                        "removed_documents_disabled": int(removed_documents_disabled),
                        "source_manifest": dict(source_manifest_state),
                    }
                )
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        if effective_mode == "incremental" and removed_paths:
            for path in removed_paths:
                raw_url = _github_raw_url(owner=owner, repo=repo_name, branch=branch, path=path)
                try:
                    disabled = _soft_disable_connector_documents_by_source_url(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=run.dataset_id,
                        connector_id="github_repo",
                        source_url=raw_url,
                    )
                except Exception as exc:  # noqa: BLE001
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=path, exc=exc)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    continue
                removed_documents_disabled += int(disabled)
                if disabled:
                    removed_paths_reconciled += 1

        stats = dict(run.stats or {})
        stats.update(
            {
                "mode": effective_mode,
                "delta_files": int(len(delta_files)),
                "skipped_unchanged": int(skipped_unchanged),
                "document_ids": [str(d) for d in created_doc_ids],
                "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
                "removed_paths": int(len(removed_paths)),
                "removed_paths_reconciled": int(removed_paths_reconciled),
                "removed_documents_disabled": int(removed_documents_disabled),
                "source_manifest": dict(source_manifest_state),
            }
        )
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        if enable_source_acl:
            with contextlib.suppress(Exception):
                from app.services.audit_log_service import audit_log_event

                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=requested_by,
                    action="github_repo.source_acl.delta_sync",
                    resource_type="connector_run",
                    resource_id=str(run_id),
                    details={
                        "dataset_id": str(run.dataset_id),
                        "connector_id": "github_repo",
                        "repo": repo,
                        "branch": branch,
                        "updated_documents": int(delta_acl_docs_updated),
                        "updated_sources": int(delta_acl_sources_updated),
                    },
                )
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


async def _execute_drive_files_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for drive_files connector.
    """
    db = SessionLocal()
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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)
        urls = cfg.get("urls") if isinstance(cfg.get("urls"), list) else []
        urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
        filename = cfg.get("filename") if isinstance(cfg.get("filename"), str) else None
        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
        source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None

        auth_headers = _build_auth_headers(cfg)

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []
        delta_acl_docs_updated = 0
        delta_acl_sources_updated = 0

        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        existing_manifest = normalize_source_manifest(state.get("source_manifest"))
        tracked_source_refs = set(existing_manifest)
        resume_cursor_raw = get_resume_cursor(state)
        is_resume_run = bool((run.stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
        effective_mode = "incremental" if existing_manifest else "full"
        resume_cursor = resume_cursor_raw if (is_resume_run and effective_mode == "full") else 0

        source_acl_mode = str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
        source_acl_fallback_mode = str(source_acl.get("fallback_mode") or "partial_members").strip().lower() if isinstance(source_acl, dict) else "partial_members"
        allow_anyone = bool(source_acl.get("allow_anyone", False)) if isinstance(source_acl, dict) else False

        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")
        enable_source_acl = bool(source_acl_mode == "inherit" and not has_manual_access_override)

        drive_client: httpx.AsyncClient | None = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        removed_source_refs: list[str] = []
        removed_paths_reconciled = 0
        removed_documents_disabled = 0

        try:
            discovered_sources: list[tuple[str, str, str, str]] = []
            observed_tracked_refs: set[str] = set()
            for source_url in urls:
                file_id_raw = _extract_drive_file_id(source_url)
                file_id = str(file_id_raw or "").strip()
                source_ref = _drive_source_ref(file_id=file_id_raw, source_url=source_url)
                if source_ref in tracked_source_refs:
                    observed_tracked_refs.add(source_ref)
                source_token = await _drive_fetch_file_sync_token(
                    client=drive_client,
                    file_id=file_id,
                    source_url=source_url,
                    headers=auth_headers,
                )
                discovered_sources.append((source_url, source_ref, file_id, source_token))

            delta_sources: list[tuple[str, str, str, str]] = []
            skipped_unchanged = 0
            for source_url, source_ref, file_id, source_token in discovered_sources:
                if (
                    (not enable_source_acl)
                    and effective_mode == "incremental"
                    and existing_manifest.get(source_ref) == source_token
                ):
                    skipped_unchanged += 1
                    continue
                delta_sources.append((source_url, source_ref, file_id, source_token))

            removed_source_refs = (
                sorted(tracked_source_refs - observed_tracked_refs) if effective_mode == "incremental" else []
            )
            sources_to_process, cursor_in = slice_items_from_cursor(delta_sources, cursor=resume_cursor)
            source_manifest_state = {
                source_ref: token for source_ref, token in existing_manifest.items() if source_ref not in removed_source_refs
            }
            processed_visible = skipped_unchanged + cursor_in

            stats0 = dict(run.stats or {})
            stats0.update(
                {
                    "mode": effective_mode,
                    "total_urls": int(len(discovered_sources)),
                    "delta_urls": int(len(delta_sources)),
                    "skipped_unchanged": int(skipped_unchanged),
                    "processed_urls": int(processed_visible),
                    "cursor": int(cursor_in),
                    "created": 0,
                    "failed": 0,
                    "failed_urls": [],
                    "cursor_in": int(cursor_in),
                    "resumed_from_state": bool(is_resume_run and ((effective_mode == "incremental") or cursor_in > 0)),
                    "removed_paths": int(len(removed_source_refs)),
                    "removed_paths_reconciled": int(removed_paths_reconciled),
                    "removed_documents_disabled": int(removed_documents_disabled),
                    "source_manifest": dict(source_manifest_state),
                }
            )
            run.stats = _finalize_connector_stats(stats0)
            db.commit()

            for idx, (source_url, source_ref, file_id, source_token) in enumerate(sources_to_process):
                try:
                    db.refresh(run)
                except Exception:
                    pass
                if str(run.status or "").lower() == "cancelled":
                    break

                succeeded = False
                try:
                    if not file_id:
                        raise ValueError("unsupported_drive_url")

                    effective_access = access
                    acl_provenance: dict | None = None
                    if enable_source_acl and drive_client is not None:
                        ext_ids: list[str] = []
                        mapped_gids: set[UUID] = set()
                        has_anyone = False
                        fallback_used = False
                        try:
                            perms = await _drive_fetch_file_permissions(
                                client=drive_client,
                                file_id=file_id,
                                headers=auth_headers,
                            )

                            seen_ext: set[str] = set()
                            for p in perms or []:
                                if not isinstance(p, dict):
                                    continue
                                if bool(p.get("deleted", False)):
                                    continue
                                t = str(p.get("type") or "").strip().lower()
                                if t == "anyone":
                                    has_anyone = True
                                    continue
                                if t == "group":
                                    key = _drive_group_principal_key(str(p.get("emailAddress") or ""))
                                    if key and key not in seen_ext:
                                        seen_ext.add(key)
                                        ext_ids.append(key)
                                        if len(ext_ids) >= 200:
                                            break

                            if has_anyone and bool(allow_anyone):
                                effective_access = {"mode": "all_team_members"}
                                fallback_used = False
                            else:
                                mapped_gids = _resolve_tenant_group_ids_by_external_id(
                                    db,
                                    tenant_id=tenant_id,
                                    external_ids=ext_ids,
                                )
                                if mapped_gids:
                                    ordered = sorted(mapped_gids, key=lambda v: str(v))
                                    effective_access = {
                                        "mode": "partial_members",
                                        "partial_group_list": [str(gid) for gid in ordered],
                                    }
                                    fallback_used = False
                                else:
                                    effective_access = {"mode": source_acl_fallback_mode}
                                    fallback_used = True
                        except Exception:
                            effective_access = {"mode": source_acl_fallback_mode}
                            fallback_used = True

                        with contextlib.suppress(Exception):
                            from app.services.document_acl_provenance_service import build_document_acl_provenance

                            acl_provenance = build_document_acl_provenance(
                                connector_id="drive_files",
                                connector_run_id=str(run_id),
                                effective_access=effective_access,
                                source_acl_mode=source_acl_mode,
                                source_acl_fallback_mode=source_acl_fallback_mode,
                                source_principal_external_ids=ext_ids,
                                mapped_group_ids=mapped_gids,
                                fallback_used=fallback_used,
                                allow_anyone=allow_anyone,
                                anyone_detected=has_anyone,
                            )

                    dl_url = _drive_direct_download_url(file_id)
                    if enable_source_acl:
                        updated_existing = _delta_sync_connector_documents_acl_by_source_url(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=run.dataset_id,
                            connector_id="drive_files",
                            source_url=dl_url,
                            requested_by=requested_by,
                            access=effective_access,
                            acl_provenance=acl_provenance,
                        )
                        delta_acl_docs_updated += int(updated_existing)
                        if updated_existing:
                            delta_acl_sources_updated += 1
                    body = UrlUploadRequest(
                        url=dl_url,
                        dataset_id=run.dataset_id,
                        filename=filename,
                        fetch_headers=auth_headers or None,
                        user_agent=user_agent,
                        parser_backend=str(parser_backend),
                        chunk_strategy=str(chunk_strategy),
                        pipeline=pipeline,  # type: ignore[arg-type]
                    )
                    doc = await _ingest_url_upload_request(
                        background_tasks=None,
                        body=body,
                        tenant_id=tenant_id,
                        account_id=requested_by,
                        db=db,
                    )
                    _apply_document_access_from_config(
                        db,
                        tenant_id=tenant_id,
                        requested_by=requested_by,
                        doc=doc,
                        access=effective_access,
                        connector_id="drive_files",
                    )
                    if isinstance(acl_provenance, dict):
                        with contextlib.suppress(Exception):
                            from app.services.document_acl_provenance_service import apply_document_acl_provenance

                            apply_document_acl_provenance(doc, provenance=acl_provenance)
                    _apply_connector_identity_metadata(
                        doc=doc,
                        run=run,
                        connector_id="drive_files",
                        source_ref=source_ref,
                        source_id=file_id,
                    )
                    db.add(
                        ConnectorRunDocument(
                            tenant_id=tenant_id,
                            run_id=run.id,
                            document_id=doc.id,
                            source_ref=source_ref,
                            status="created",
                        )
                    )
                    created += 1
                    created_doc_ids.append(doc.id)
                    succeeded = True
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=source_url or source_ref, exc=exc)
                    run.stats = stats
                finally:
                    processed = cursor_in + idx + 1
                    processed_visible = skipped_unchanged + processed
                    if succeeded:
                        source_manifest_state[source_ref] = source_token
                    stats = dict(run.stats or {})
                    stats.update(
                        {
                            "mode": effective_mode,
                            "total_urls": int(len(discovered_sources)),
                            "delta_urls": int(len(delta_sources)),
                            "skipped_unchanged": int(skipped_unchanged),
                            "processed_urls": int(processed_visible),
                            "cursor": int(processed),
                            "created": int(created),
                            "failed": int(failed),
                            "removed_paths": int(len(removed_source_refs)),
                            "removed_paths_reconciled": int(removed_paths_reconciled),
                            "removed_documents_disabled": int(removed_documents_disabled),
                            "source_manifest": dict(source_manifest_state),
                            "document_ids": [str(d) for d in created_doc_ids],
                            "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                            "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
                        }
                    )
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
        finally:
            if drive_client is not None:
                with contextlib.suppress(Exception):
                    await drive_client.aclose()

        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        if effective_mode == "incremental" and removed_source_refs:
            for source_ref in removed_source_refs:
                try:
                    if str(source_ref).startswith("url:"):
                        disabled = _soft_disable_connector_documents_by_source_ref(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=run.dataset_id,
                            connector_id="drive_files",
                            source_ref=source_ref,
                        )
                    else:
                        disabled = _soft_disable_connector_documents_by_source_url(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=run.dataset_id,
                            connector_id="drive_files",
                            source_url=_drive_direct_download_url(source_ref),
                        )
                except Exception as exc:  # noqa: BLE001
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=source_ref, exc=exc)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    continue
                removed_documents_disabled += int(disabled)
                if disabled:
                    removed_paths_reconciled += 1

        stats = dict(run.stats or {})
        stats.update(
            {
                "mode": effective_mode,
                "delta_urls": int(len(delta_sources)),
                "skipped_unchanged": int(skipped_unchanged),
                "document_ids": [str(d) for d in created_doc_ids],
                "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
                "removed_paths": int(len(removed_source_refs)),
                "removed_paths_reconciled": int(removed_paths_reconciled),
                "removed_documents_disabled": int(removed_documents_disabled),
                "source_manifest": dict(source_manifest_state),
            }
        )
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        if enable_source_acl:
            with contextlib.suppress(Exception):
                from app.services.audit_log_service import audit_log_event

                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=requested_by,
                    action="drive_files.source_acl.delta_sync",
                    resource_type="connector_run",
                    resource_id=str(run_id),
                    details={
                        "dataset_id": str(run.dataset_id),
                        "connector_id": "drive_files",
                        "updated_documents": int(delta_acl_docs_updated),
                        "updated_sources": int(delta_acl_sources_updated),
                        "allow_anyone": bool(allow_anyone),
                        "fallback_mode": source_acl_fallback_mode,
                    },
                )
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


async def _execute_minio_bucket_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for minio_bucket connector.
    """
    db = SessionLocal()
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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)
        bucket = cfg.get("bucket") if isinstance(cfg.get("bucket"), str) else None
        prefix = cfg.get("prefix") if isinstance(cfg.get("prefix"), str) else None
        max_objects = int(cfg.get("max_objects") or 50)
        expiry = int(cfg.get("presign_expiry_sec") or 3600)
        include_exts = cfg.get("include_extensions") if isinstance(cfg.get("include_extensions"), list) else []
        include_exts = [str(e or "").strip().lower() for e in include_exts if str(e or "").strip()]
        include_exts = [("." + e if not e.startswith(".") else e) for e in include_exts]
        include_set = set(include_exts) if include_exts else {".pdf", ".md", ".txt"}

        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None

        from app.storage.object.minio import minio_service

        client = minio_service._get_client()  # noqa: SLF001
        bucket_name = str(bucket or getattr(minio_service, "_bucket_name", "") or "").strip()
        if not bucket_name:
            raise RuntimeError("minio bucket is required")

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []
        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        existing_manifest = normalize_source_manifest(state.get("source_manifest"))

        # If a run is associated with a saved connector config, use it as a scoping guard for
        # soft-delete operations so multiple configs of the same connector do not interfere.
        stats = dict(run.stats or {})
        cfg_id = stats.get("config_id")
        connector_config_id: UUID | None = None
        try:
            if cfg_id:
                connector_config_id = UUID(str(cfg_id))
        except Exception:
            connector_config_id = None

        scope_parts = [
            f"bucket={bucket_name}",
            f"prefix={str(prefix or '').strip()}",
            f"include={','.join(sorted(include_set))}",
        ]
        scope_hash = hashlib.sha256("|".join(scope_parts).encode("utf-8")).hexdigest()[:16]
        existing_scope_hash = str(state.get("source_scope_hash") or "").strip()
        if existing_scope_hash and existing_scope_hash != scope_hash:
            existing_manifest = {}

        tracked_keys = set(existing_manifest)
        observed_tracked_keys: set[str] = set()

        def _minio_object_token(obj) -> str:  # noqa: ANN001
            etag = str(getattr(obj, "etag", "") or "").strip()

            last_modified_raw = getattr(obj, "last_modified", None)
            if isinstance(last_modified_raw, datetime):
                last_modified = (
                    last_modified_raw.astimezone(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            else:
                last_modified = str(last_modified_raw or "").strip()

            parts: list[str] = []
            if etag:
                parts.append(f"etag:{etag}")
            if last_modified:
                parts.append(f"last_modified:{last_modified}")

            # Some SDKs expose size; include it as a best-effort extra staleness signal.
            size_raw = getattr(obj, "size", None)
            with contextlib.suppress(Exception):
                size = int(size_raw or 0) if size_raw is not None else 0
                if size:
                    parts.append(f"size:{size}")

            return "|".join(parts) or "unknown"

        resume_cursor_raw = get_resume_cursor(state)
        is_resume_run = bool((run.stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
        effective_mode = "incremental" if existing_manifest else "full"
        resume_cursor = resume_cursor_raw if (is_resume_run and effective_mode == "full") else 0

        total_objects = 0
        delta_objects_total = 0
        skipped_unchanged = 0
        max_objects_bound = max(1, min(int(max_objects or 0), 200))
        objects_to_process: list[tuple[str, str]] = []
        for obj in client.list_objects(bucket_name=bucket_name, prefix=(prefix or None), recursive=True):
            name = str(getattr(obj, "object_name", "") or "").strip()
            if not name:
                continue

            if name in tracked_keys:
                observed_tracked_keys.add(name)

            ext = Path(name).suffix.lower()
            if ext:
                if ext not in include_set:
                    continue
            else:
                if "" not in include_set:
                    continue

            total_objects += 1
            token = _minio_object_token(obj)

            if effective_mode == "incremental" and existing_manifest.get(name) == token:
                skipped_unchanged += 1
                continue

            delta_objects_total += 1
            if effective_mode == "full" and delta_objects_total <= resume_cursor:
                continue

            if len(objects_to_process) < max_objects_bound:
                objects_to_process.append((name, token))

        cursor_in = min(max(0, int(resume_cursor or 0)), int(delta_objects_total))
        removed_paths = sorted(tracked_keys - observed_tracked_keys) if effective_mode == "incremental" else []
        source_manifest_state = {path: sha for path, sha in existing_manifest.items() if path not in removed_paths}
        processed_visible = skipped_unchanged + cursor_in
        removed_paths_reconciled = 0
        removed_documents_disabled = 0
        updated_documents_disabled = 0

        stats0 = dict(run.stats or {})
        stats0.update(
            {
                "mode": effective_mode,
                "total_objects": int(total_objects),
                "delta_objects": int(delta_objects_total),
                "skipped_unchanged": int(skipped_unchanged),
                "processed_objects": int(processed_visible),
                "cursor": int(cursor_in),
                "created": 0,
                "failed": 0,
                "cursor_in": int(cursor_in),
                "resumed_from_state": bool(cursor_in > 0),
                "removed_paths": int(len(removed_paths)),
                "removed_paths_reconciled": int(removed_paths_reconciled),
                "removed_documents_disabled": int(removed_documents_disabled),
                "updated_documents_disabled": int(updated_documents_disabled),
                "source_manifest": dict(source_manifest_state),
                "source_scope_hash": str(scope_hash),
            }
        )
        run.stats = stats0
        db.commit()

        for idx, (object_name, object_token) in enumerate(objects_to_process):
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            try:
                url = client.presigned_get_object(bucket_name=bucket_name, object_name=object_name, expires=expiry)
                body = UrlUploadRequest(
                    url=url,
                    dataset_id=run.dataset_id,
                    filename=Path(object_name).name,
                    parser_backend=str(parser_backend),
                    chunk_strategy=str(chunk_strategy),
                    pipeline=pipeline,  # type: ignore[arg-type]
                )
                doc = await _ingest_url_upload_request(
                    background_tasks=None,
                    body=body,
                    tenant_id=tenant_id,
                    account_id=requested_by,
                    db=db,
                )
                _apply_document_access_from_config(
                    db,
                    tenant_id=tenant_id,
                    requested_by=requested_by,
                    doc=doc,
                    access=access,
                    connector_id="minio_bucket",
                )
                _apply_connector_identity_metadata(
                    doc=doc,
                    run=run,
                    connector_id="minio_bucket",
                    source_ref=object_name,
                    source_id=object_name,
                )
                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        document_id=doc.id,
                        source_ref=object_name,
                        status="created",
                    )
                )
                if effective_mode == "incremental" and object_name in source_manifest_state:
                    with contextlib.suppress(Exception):
                        updated_documents_disabled += _soft_disable_connector_documents_by_source_ref(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=run.dataset_id,
                            connector_id="minio_bucket",
                            source_ref=object_name,
                            connector_config_id=connector_config_id,
                            exclude_document_id=doc.id,
                        )
                created += 1
                created_doc_ids.append(doc.id)
                source_manifest_state[object_name] = object_token
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=object_name, exc=exc)
                run.stats = stats
            finally:
                processed = cursor_in + idx + 1
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "mode": effective_mode,
                        "total_objects": int(total_objects),
                        "delta_objects": int(delta_objects_total),
                        "skipped_unchanged": int(skipped_unchanged),
                        "processed_objects": int(skipped_unchanged + processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
                        "removed_paths": int(len(removed_paths)),
                        "removed_paths_reconciled": int(removed_paths_reconciled),
                        "removed_documents_disabled": int(removed_documents_disabled),
                        "updated_documents_disabled": int(updated_documents_disabled),
                        "source_manifest": dict(source_manifest_state),
                        "source_scope_hash": str(scope_hash),
                        "document_ids": [str(d) for d in created_doc_ids],
                    }
                )
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        if effective_mode == "incremental" and removed_paths:
            for source_ref in removed_paths:
                try:
                    disabled = _soft_disable_connector_documents_by_source_ref(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=run.dataset_id,
                        connector_id="minio_bucket",
                        source_ref=source_ref,
                        connector_config_id=connector_config_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=source_ref, exc=exc)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    continue

                removed_documents_disabled += int(disabled)
                if disabled:
                    removed_paths_reconciled += 1

        stats = dict(run.stats or {})
        stats.update(
            {
                "mode": effective_mode,
                "delta_objects": int(delta_objects_total),
                "skipped_unchanged": int(skipped_unchanged),
                "removed_paths": int(len(removed_paths)),
                "removed_paths_reconciled": int(removed_paths_reconciled),
                "removed_documents_disabled": int(removed_documents_disabled),
                "updated_documents_disabled": int(updated_documents_disabled),
                "source_manifest": dict(source_manifest_state),
                "source_scope_hash": str(scope_hash),
                "document_ids": [str(d) for d in created_doc_ids],
            }
        )
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


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
    if _is_http_or_https_url(w):
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


def _jira_attachment_limits(cfg: dict) -> tuple[bool, int, int]:
    """
    Parse and clamp Jira attachments ingestion limits from a raw config dict.
    """
    raw = cfg if isinstance(cfg, dict) else {}
    include = bool(raw.get("include_attachments", False))

    per_issue = int(raw.get("max_attachments_per_issue") or 10)
    per_issue = max(1, min(per_issue, 50))

    total = int(raw.get("max_total_attachments") or 200)
    total = max(1, min(total, 2000))

    return include, per_issue, total


def _jira_linked_artifact_limits(cfg: dict) -> tuple[bool, int, int]:
    """
    Parse and clamp Jira linked-artifact ingestion limits from a raw config dict.

    Linked artifacts are URL-like resources referenced by an issue (e.g. Confluence pages, PRs).
    """
    raw = cfg if isinstance(cfg, dict) else {}
    include = bool(raw.get("include_linked_artifacts", False))

    per_issue = int(raw.get("max_linked_artifacts_per_issue") or 10)
    per_issue = max(1, min(per_issue, 50))

    total = int(raw.get("max_total_linked_artifacts") or 200)
    total = max(1, min(total, 2000))

    return include, per_issue, total


def _jira_extract_attachments(issue: dict, *, limit: int) -> list[dict[str, str]]:
    """
    Extract Jira issue attachment refs from the issue payload.

    Returns a bounded list of dicts with:
    - attachment_id
    - filename
    - download_url
    """
    if not isinstance(issue, dict):
        return []

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    items = fields.get("attachment") if isinstance(fields.get("attachment"), list) else []
    out: list[dict[str, str]] = []

    for raw in items:
        if len(out) >= lim:
            break
        if not isinstance(raw, dict):
            continue

        attachment_id = str(raw.get("id") or "").strip()
        if not attachment_id:
            continue

        filename = str(raw.get("filename") or raw.get("title") or raw.get("name") or "").strip()
        if not filename:
            filename = f"jira-attachment-{attachment_id}"

        download_url = str(raw.get("content") or raw.get("downloadUrl") or raw.get("download_url") or "").strip()
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


def _jira_extract_urls_from_text(value: object, *, limit: int) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    # Simple URL matcher: good enough for connector-side enrichment (ingest pipeline still validates).
    url_re = re.compile(r"https?://[^\s<>\")\]]+", flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for m in url_re.finditer(text):
        url = str(m.group(0) or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= lim:
            break
    return out


def _jira_extract_urls_from_adf(value: object, *, limit: int) -> list[str]:
    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    out: list[str] = []
    seen: set[str] = set()

    def _push(raw: object) -> None:
        if len(out) >= lim:
            return
        url = str(raw or "").strip()
        if not url:
            return
        if not _is_http_or_https_url(url):
            return
        if url in seen:
            return
        seen.add(url)
        out.append(url)

    def _walk(node: object, *, depth: int = 0) -> None:
        if len(out) >= lim or depth > 60:
            return
        if node is None:
            return
        if isinstance(node, str):
            for u in _jira_extract_urls_from_text(node, limit=lim - len(out)):
                _push(u)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, depth=depth + 1)
            return
        if not isinstance(node, dict):
            return

        node_type = str(node.get("type") or "").strip().lower()
        if node_type == "text":
            marks = node.get("marks") if isinstance(node.get("marks"), list) else []
            for mark in marks:
                if not isinstance(mark, dict):
                    continue
                if str(mark.get("type") or "").strip().lower() != "link":
                    continue
                attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
                _push(attrs.get("href"))
        elif node_type == "inlinecard":
            attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
            _push(attrs.get("url"))

        content = node.get("content")
        items = content if isinstance(content, list) else []
        for item in items:
            _walk(item, depth=depth + 1)

    _walk(value)
    return out


def _jira_extract_linked_artifact_urls(issue: dict, *, include_comments: bool, max_comments: int, limit: int) -> list[str]:
    """
    Extract linked artifact URLs referenced by the issue payload.

    This is best-effort and intentionally bounded/deterministic.
    """
    if not isinstance(issue, dict):
        return []

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    out: list[str] = []
    seen: set[str] = set()

    def _extend(urls: list[str]) -> None:
        nonlocal out
        for url in urls:
            if len(out) >= lim:
                return
            u = str(url or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(u)

    desc = fields.get("description")
    if _jira_adf_is_doc(desc):
        _extend(_jira_extract_urls_from_adf(desc, limit=lim - len(out)))
    else:
        _extend(_jira_extract_urls_from_text(desc, limit=lim - len(out)))

    if include_comments:
        comments_obj = fields.get("comment") if isinstance(fields.get("comment"), dict) else {}
        comment_items = comments_obj.get("comments") if isinstance(comments_obj.get("comments"), list) else []
        lim_comments = max(0, int(max_comments or 0))
        for comment in comment_items[:lim_comments]:
            if len(out) >= lim:
                break
            if not isinstance(comment, dict):
                continue
            body = comment.get("body")
            if _jira_adf_is_doc(body):
                _extend(_jira_extract_urls_from_adf(body, limit=lim - len(out)))
            else:
                _extend(_jira_extract_urls_from_text(body, limit=lim - len(out)))

    # Stable/deterministic ordering: sort for reconciliation + ingestion reproducibility.
    out_sorted = sorted(out)
    return out_sorted[:lim]


def _jira_attachment_connector_metadata(
    *,
    base_url: str,
    project_key: str,
    issue_id: str | None,
    issue_key: str | None,
    issue_url: str,
    attachment_id: str,
    filename: str,
    download_url: str,
    run_id: str,
    mode: str,
) -> dict[str, Any]:
    """
    Build doc_metadata.connector for a Jira attachment document.
    """
    return {
        "connector_id": "jira_project",
        "doc_kind": "attachment",
        "base_url": str(base_url or "").strip(),
        "project_key": str(project_key or "").strip().upper(),
        "issue_id": (str(issue_id or "").strip() or None),
        "issue_key": (str(issue_key or "").strip() or None),
        "issue_url": str(issue_url or "").strip(),
        "attachment_id": str(attachment_id or "").strip(),
        "filename": str(filename or "").strip(),
        "download_url": str(download_url or "").strip(),
        "run_id": str(run_id or "").strip(),
        "mode": str(mode or "").strip(),
    }


def _jira_linked_artifact_connector_metadata(
    *,
    base_url: str,
    project_key: str,
    issue_id: str | None,
    issue_key: str | None,
    issue_url: str,
    link_url: str,
    run_id: str,
    mode: str,
) -> dict[str, Any]:
    """
    Build doc_metadata.connector for a Jira linked-artifact document.

    Linked artifacts are URL-derived child documents that inherit issue-scoped ACL.
    """
    return {
        "connector_id": "jira_project",
        "doc_kind": "linked_artifact",
        "base_url": str(base_url or "").strip(),
        "project_key": str(project_key or "").strip().upper(),
        "issue_id": (str(issue_id or "").strip() or None),
        "issue_key": (str(issue_key or "").strip() or None),
        "issue_url": str(issue_url or "").strip(),
        "link_url": str(link_url or "").strip(),
        "run_id": str(run_id or "").strip(),
        "mode": str(mode or "").strip(),
    }


def _jira_should_send_auth_headers(*, base_url: str, url: str) -> bool:
    """
    Decide whether it's safe to attach Jira auth headers when fetching `url`.

    We only send headers to the same origin as the Jira base URL to avoid leaking
    credentials to third-party sites.
    """
    base = str(base_url or "").strip()
    target = str(url or "").strip()
    if not base or not target:
        return False
    try:
        b = urlparse(base)
        u = urlparse(target)
    except Exception:
        return False
    if not b.scheme or not b.netloc or not u.scheme or not u.netloc:
        return False
    if str(u.scheme or "").lower() not in {"http", "https"}:
        return False
    return str(b.netloc).lower() == str(u.netloc).lower()

def _jira_api_base_url(base_url: str) -> str:
    """
    Normalize a Jira base URL to the Jira Cloud REST v3 API base.

    Examples:
    - https://<site>.atlassian.net -> https://<site>.atlassian.net/rest/api/3
    - https://<site>.atlassian.net/rest/api/3 -> unchanged
    """
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/rest/api/3"):
        return base
    if base.endswith("/rest/api"):
        return f"{base}/3"
    if "/rest/api/" in base:
        prefix = base.split("/rest/api/", 1)[0].rstrip("/")
        return f"{prefix}/rest/api/3"
    return f"{base}/rest/api/3"


async def _jira_request(pool, method: str, url: str, **kwargs):  # noqa: ANN001, ANN201
    """
    Jira API requests are always third-party outbound HTTP calls.
    """
    return await pool.request_with_retry(method, url, use_external_client=True, **kwargs)


def _jira_extract_issue_updated(issue: dict) -> str | None:
    """
    Best-effort extraction of the Jira issue updated timestamp for incremental cursoring.
    """
    if not isinstance(issue, dict):
        return None
    fields = issue.get("fields")
    if isinstance(fields, dict):
        updated = str(fields.get("updated") or "").strip()
        if updated:
            return updated
    updated = str(issue.get("updated") or "").strip()
    return updated or None


def _jira_principal_value(raw: object) -> str:
    value = str(raw or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    return value[:255]


def _jira_group_principal_key(group_name: str) -> str:
    name = _jira_principal_value(group_name)
    return f"jira:group:{name}"[:255] if name else ""


def _jira_role_principal_key(role_name: str) -> str:
    name = _jira_principal_value(role_name)
    return f"jira:role:{name}"[:255] if name else ""


def _jira_security_level_principal_key(security: object) -> str:
    if not isinstance(security, dict):
        return ""
    level_id = str(security.get("id") or "").strip()
    if level_id:
        return f"jira:policy:security-level/{level_id}"[:255]
    name = _jira_principal_value(security.get("name"))
    if not name:
        return ""
    return f"jira:policy:security-level/{name}"[:255]


def _jira_issue_acl_principal_keys(issue: dict, *, include_comments: bool, max_comments: int) -> tuple[bool, list[str]]:
    """
    Collect best-effort Jira visibility/security handles for source ACL inheritance.

    We do not attempt to resolve Jira memberships here. Instead we expose stable external ids
    that operators can map onto tenant groups via `tenant_groups.external_id`.
    """
    if not isinstance(issue, dict):
        return False, []

    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return False, []

    keys: set[str] = set()

    security_key = _jira_security_level_principal_key(fields.get("security"))
    if security_key:
        keys.add(security_key)

    if include_comments:
        lim = max(0, int(max_comments or 0))
        comments_obj = fields.get("comment")
        comments = comments_obj.get("comments") if isinstance(comments_obj, dict) else None
        items = comments if isinstance(comments, list) else []
        for comment in items[:lim]:
            if not isinstance(comment, dict):
                continue
            visibility = comment.get("visibility")
            if not isinstance(visibility, dict):
                continue
            vis_type = str(visibility.get("type") or "").strip().lower()
            vis_value = visibility.get("value") or visibility.get("identifier") or visibility.get("name")
            if vis_type == "group":
                key = _jira_group_principal_key(str(vis_value or ""))
            elif vis_type == "role":
                key = _jira_role_principal_key(str(vis_value or ""))
            else:
                key = ""
            if key:
                keys.add(key)

    ordered = sorted(keys)
    return bool(ordered), ordered


def _jira_adf_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_jira_adf_to_text(item) for item in value)
    if not isinstance(value, dict):
        return str(value)

    node_type = str(value.get("type") or "").strip().lower()
    if node_type == "text":
        return str(value.get("text") or "")
    if node_type == "hardbreak":
        return "\n"

    content = value.get("content")
    child_items = content if isinstance(content, list) else []
    text = "".join(_jira_adf_to_text(item) for item in child_items)
    if node_type in {"paragraph", "heading", "listitem", "blockquote", "tablecell", "tableheader"} and text and not text.endswith("\n"):
        text += "\n"
    return text


def _jira_adf_is_doc(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return str(value.get("type") or "").strip().lower() == "doc" and isinstance(value.get("content"), list)


def _jira_adf_text_node_html(value: dict) -> str:
    text = html.escape(str(value.get("text") or ""))

    marks = value.get("marks") if isinstance(value.get("marks"), list) else []
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mtype = str(mark.get("type") or "").strip().lower()
        if mtype == "link":
            attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
            href = str(attrs.get("href") or "").strip()
            if _is_link_href_allowed(href):
                text = f'<a href="{html.escape(href)}">{text}</a>'
            continue
        if mtype == "strong":
            text = f"<strong>{text}</strong>"
            continue
        if mtype == "em":
            text = f"<em>{text}</em>"
            continue
        if mtype == "code":
            text = f"<code>{text}</code>"
            continue
        if mtype in {"strike", "strikethrough"}:
            text = f"<s>{text}</s>"

    return text


def _jira_adf_node_to_html(value: object, *, depth: int = 0) -> str:
    if depth > 50:
        return ""
    if value is None:
        return ""
    if isinstance(value, str):
        return html.escape(value)
    if isinstance(value, list):
        return "\n".join(
            part for part in (_jira_adf_node_to_html(item, depth=depth + 1) for item in value) if part
        )
    if not isinstance(value, dict):
        return html.escape(str(value))

    node_type = str(value.get("type") or "").strip().lower()
    content = value.get("content")
    child_items = content if isinstance(content, list) else []

    if node_type == "text":
        return _jira_adf_text_node_html(value)
    if node_type == "hardbreak":
        return "<br />"

    if node_type == "paragraph":
        inner = "".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<p>{inner}</p>"

    if node_type == "heading":
        attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
        try:
            level = int(attrs.get("level") or 3)
        except Exception:
            level = 3
        level = max(1, min(level, 6))
        inner = "".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        # Keep ADF headings slightly lower in the document hierarchy to avoid competing with issue-level headings.
        safe_level = min(6, max(3, level + 1))
        return f"<h{safe_level}>{inner}</h{safe_level}>"

    if node_type == "blockquote":
        inner = "\n".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<blockquote>{inner}</blockquote>"

    if node_type == "rule":
        return "<hr />"

    if node_type in {"bulletlist", "orderedlist"}:
        tag = "ul" if node_type == "bulletlist" else "ol"
        inner = "\n".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<{tag}>{inner}</{tag}>"

    if node_type == "listitem":
        inner = "\n".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<li>{inner}</li>"

    if node_type == "codeblock":
        # Render as plain escaped text to preserve code fidelity.
        code_text = _jira_adf_to_text(value).strip("\n")
        if not code_text.strip():
            return ""
        return f"<pre><code>{html.escape(code_text)}</code></pre>"

    if node_type == "table":
        inner = "\n".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<table><tbody>{inner}</tbody></table>"

    if node_type == "tablerow":
        inner = "".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<tr>{inner}</tr>"

    if node_type in {"tablecell", "tableheader"}:
        tag = "th" if node_type == "tableheader" else "td"
        inner = "\n".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()
        if not inner:
            return ""
        return f"<{tag}>{inner}</{tag}>"

    if node_type == "inlinecard":
        attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
        url = str(attrs.get("url") or "").strip()
        if _is_http_or_https_url(url):
            esc = html.escape(url)
            return f'<a href="{esc}">{esc}</a>'
        return html.escape(url) if url else ""

    if node_type == "mention":
        attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
        text = str(attrs.get("text") or attrs.get("displayName") or "").strip()
        if text:
            return html.escape(text)
        return ""

    if node_type == "emoji":
        attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
        text = str(attrs.get("text") or attrs.get("shortName") or "").strip()
        if text:
            return html.escape(text)
        return ""

    # Fallback: render children.
    return "\n".join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()


def _jira_adf_to_html(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "\n".join(f"<p>{html.escape(line.strip())}</p>" for line in value.splitlines() if line.strip())
    if isinstance(value, dict) and not _jira_adf_is_doc(value):
        # Accept rendering of a node (not only doc root) as a best-effort helper.
        return _jira_adf_node_to_html(value)
    return _jira_adf_node_to_html(value)


def _jira_value_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if _jira_adf_is_doc(value):
        return _jira_adf_to_text(value)
    if isinstance(value, list):
        parts = [(_jira_value_to_text(item) or "").strip() for item in value]
        parts = [p for p in parts if p]
        return ", ".join(parts)
    if isinstance(value, dict):
        for k in ("displayName", "name", "value", "key", "title", "summary"):
            raw = value.get(k)
            if raw is None:
                continue
            if isinstance(raw, (str, int, float, bool)):
                text = str(raw).strip()
                if text:
                    return text
        return ""
    return str(value).strip()


def _jira_html_from_value(raw: object) -> str:
    if raw is None:
        return ""
    if _jira_adf_is_doc(raw):
        return _jira_adf_to_html(raw)
    text = _jira_value_to_text(raw).strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)


def _jira_html_from_field(*, rendered: object, raw: object) -> str:
    rendered_text = str(rendered or "").strip() if isinstance(rendered, str) else ""
    if rendered_text:
        return rendered_text

    if _jira_adf_is_doc(raw):
        return _jira_adf_to_html(raw)

    return _jira_html_from_value(raw)


def _jira_issue_url(*, base_url: str, issue_key: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    key = str(issue_key or "").strip()
    if not base or not key:
        return ""
    return f"{base}/browse/{quote(key, safe='')}"


def _soft_disable_jira_documents_missing_from_full_sync(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    seen_issue_urls: set[str],
    connector_id: str = "jira_project",
    max_docs_scan: int = 5000,
) -> tuple[int, int]:
    """
    Best-effort soft-disable for Jira issue documents missing from a complete full sync.

    Scope is limited to connector-managed Jira docs for the same tenant/dataset/base URL/project.
    """
    if dataset_id is None:
        return 0, 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    connector_id = str(connector_id or "jira_project").strip() or "jira_project"
    seen_urls = {
        str(url or "").strip()
        for url in (seen_issue_urls or set())
        if str(url or "").strip()
    }
    if not base_url or not project_key:
        return 0, 0

    docs: list[Any]
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == connector_id)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
            .all()
        )
    except Exception:
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

    now = _now()
    disabled = 0
    reconciled_issue_urls: set[str] = set()
    for doc in docs or []:
        if getattr(doc, "archived_at", None) is not None:
            continue
        meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != connector_id:
            continue
        if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
            continue
        if str(conn.get("project_key") or "").strip().upper() != project_key:
            continue

        issue_url = str(conn.get("issue_url") or meta.get("source_url") or "").strip()
        if not issue_url or issue_url in seen_urls:
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            reconciled_issue_urls.add(issue_url)
            disabled += 1

    return len(reconciled_issue_urls), int(disabled)


def _jira_jql_updated_after(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    normalized = _normalize_datetime_utc_iso(text)
    if not normalized:
        return text
    dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d %H:%M")


def _jira_render_issue_html(*, base_url: str, issue: dict, include_comments: bool, max_comments: int) -> str:
    """
    Render a Jira issue into a stable HTML document shape that works with `jira_ticket`.
    """
    issue = issue if isinstance(issue, dict) else {}
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    rendered = issue.get("renderedFields") if isinstance(issue.get("renderedFields"), dict) else {}

    issue_key = str(issue.get("key") or "").strip()
    summary = str(fields.get("summary") or issue_key or "Jira issue").strip()
    issue_url = _jira_issue_url(base_url=base_url, issue_key=issue_key)
    updated = _jira_extract_issue_updated(issue) or ""

    issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip() if isinstance(fields.get("issuetype"), dict) else ""
    priority = str((fields.get("priority") or {}).get("name") or "").strip() if isinstance(fields.get("priority"), dict) else ""
    status = str((fields.get("status") or {}).get("name") or "").strip() if isinstance(fields.get("status"), dict) else ""
    labels = fields.get("labels") if isinstance(fields.get("labels"), list) else []
    label_text = ", ".join(str(label or "").strip() for label in labels if str(label or "").strip())

    description_html = _jira_html_from_field(
        rendered=rendered.get("description"),
        raw=fields.get("description"),
    )

    comments_html: list[str] = []
    if include_comments:
        comments_obj = fields.get("comment") if isinstance(fields.get("comment"), dict) else {}
        comment_items = comments_obj.get("comments") if isinstance(comments_obj.get("comments"), list) else []
        rendered_comments_obj = rendered.get("comment") if isinstance(rendered.get("comment"), dict) else {}
        rendered_comment_items = rendered_comments_obj.get("comments") if isinstance(rendered_comments_obj.get("comments"), list) else []

        lim = max(0, int(max_comments or 0))
        for idx, comment in enumerate(comment_items[:lim], start=1):
            if not isinstance(comment, dict):
                continue
            rendered_comment = rendered_comment_items[idx - 1] if idx - 1 < len(rendered_comment_items) and isinstance(rendered_comment_items[idx - 1], dict) else {}
            author = str((comment.get("author") or {}).get("displayName") or "").strip() if isinstance(comment.get("author"), dict) else ""
            created = str(comment.get("created") or "").strip()
            body_html = _jira_html_from_field(
                rendered=rendered_comment.get("body"),
                raw=comment.get("body"),
            )
            meta_bits = [bit for bit in [author, created] if bit]
            meta_html = ""
            if meta_bits:
                meta_html = f"<p><strong>Meta:</strong> {html.escape(' | '.join(meta_bits))}</p>"
            comments_html.append(
                "<article>"
                f"<h3>Comment {idx}</h3>"
                f"{meta_html}"
                f"{body_html}"
                "</article>"
            )

    parts = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8" />',
        f"  <title>{html.escape(issue_key or summary)}</title>",
        f'  <base href="{html.escape(issue_url or str(base_url or ""))}" />' if (issue_url or base_url) else "",
        "</head>",
        "<body>",
        f"  <h1>{html.escape(issue_key or 'Jira Issue')}</h1>",
        "  <h2>Summary</h2>",
        f"  <p>{html.escape(summary)}</p>",
    ]

    if issue_url:
        parts.append(f'  <p><strong>Issue URL:</strong> <a href="{html.escape(issue_url)}">{html.escape(issue_url)}</a></p>')
    if issue_type:
        parts.append(f"  <p><strong>Issue Type:</strong> {html.escape(issue_type)}</p>")
    if priority:
        parts.append(f"  <p><strong>Priority:</strong> {html.escape(priority)}</p>")
    if status:
        parts.append(f"  <p><strong>Status:</strong> {html.escape(status)}</p>")
    if updated:
        parts.append(f"  <p><strong>Updated:</strong> {html.escape(updated)}</p>")
    if label_text:
        parts.append(f"  <p><strong>Labels:</strong> {html.escape(label_text)}</p>")

    custom_fields: list[tuple[str, object]] = []
    for k, v in (fields or {}).items():
        key = str(k or "").strip()
        if not key.startswith("customfield_"):
            continue
        custom_fields.append((key, v))
    custom_fields.sort(key=lambda item: item[0])

    custom_field_sections: list[str] = []
    for key, raw_value in custom_fields:
        value_html = _jira_html_from_field(
            rendered=rendered.get(key),
            raw=raw_value,
        )
        if not value_html:
            continue
        custom_field_sections.append(
            "<article>"
            f"<h3>{html.escape(key)}</h3>"
            f"{value_html}"
            "</article>"
        )

    if custom_field_sections:
        parts.extend(["  <h2>Custom Fields</h2>", *custom_field_sections])

    if description_html:
        parts.extend(["  <h2>Description</h2>", description_html])

    if comments_html:
        parts.extend(["  <h2>Comments</h2>", *comments_html])

    parts.extend(["</body>", "</html>"])
    return "\n".join(part for part in parts if part)


async def _execute_confluence_space_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for confluence_space connector.

    Flow:
    - List pages in a Confluence space (full or incremental based on state/sync_mode)
    - For each page, ingest its web UI URL via the existing URL ingestion pipeline
    """
    db = SessionLocal()
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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)

        base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
        space_key = str(cfg.get("space_key") or "").strip()
        if not base_url or not space_key:
            raise ValueError("base_url and space_key are required")

        sync_mode = str(cfg.get("sync_mode") or "auto").strip().lower()
        if sync_mode not in {"auto", "full", "incremental"}:
            sync_mode = "auto"

        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        cursor_last_modified = str(state.get("last_modified") or "").strip() if isinstance(state, dict) else ""
        cursor_last_modified_ids = set(normalize_boundary_ids(state.get("last_modified_ids"))) if isinstance(state, dict) else set()

        effective_mode = sync_mode
        if effective_mode == "auto":
            effective_mode = "incremental" if cursor_last_modified else "full"
        if effective_mode == "incremental" and not cursor_last_modified:
            # No cursor available; fall back to full to avoid silently doing nothing.
            effective_mode = "full"

        max_pages = int(cfg.get("max_pages") or 50)
        max_pages = max(1, min(max_pages, 500))
        page_size = int(cfg.get("page_size") or 25)
        page_size = max(1, min(page_size, 100))
        soft_delete = bool(cfg.get("soft_delete", False))

        include_attachments, max_attachments_per_page, max_total_attachments = _confluence_attachment_limits(cfg)

        ingest_method = _confluence_ingest_method(cfg)

        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
        source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None

        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
        auth_headers = _build_auth_headers(cfg)

        api_base = _confluence_api_base_url(base_url)
        search_url = f"{api_base}/content/search"

        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": (user_agent or "MimirQ/1.0 (+confluence_space)"),
        }
        headers.update(auth_headers)

        # CQL: keep it simple and stable. Prefer ordering to make cursor updates monotonic.
        cql = f'space="{space_key}" and type=page and status=current'
        if effective_mode == "incremental" and cursor_last_modified:
            cql += f' and lastmodified >= "{cursor_last_modified}"'
        cql += " ORDER BY lastmodified ASC"

        created = 0
        failed = 0
        processed = 0
        attachments_processed = 0
        attachments_created = 0
        attachments_failed = 0
        attachments_skipped = 0
        created_doc_ids: list[UUID] = []
        delta_acl_docs_updated = 0
        delta_acl_pages_updated = 0
        observed_page_ids: set[str] = set()
        last_modified_seen: str | None = None
        last_modified_ids_seen: set[str] = set()
        skipped_boundary_duplicates = 0

        stats0 = dict(run.stats or {})
        stats0.update(
            {
                "mode": effective_mode,
                "ingest_method": ingest_method,
                "space_key": space_key,
                "base_url": base_url,
                "max_pages": int(max_pages),
                "page_size": int(page_size),
                "processed_pages": 0,
                "cursor": 0,
                "created": 0,
                "failed": 0,
                "include_attachments": bool(include_attachments),
                "max_attachments_per_page": int(max_attachments_per_page),
                "max_total_attachments": int(max_total_attachments),
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
        if cursor_last_modified:
            stats0["cursor_in"] = cursor_last_modified
        run.stats = _finalize_connector_stats(stats0)
        db.commit()

        pool = get_http_client_pool()
        start = 0
        listing_complete = False
        stopped_mid_batch = False

        source_acl_mode = str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
        source_acl_fallback_mode = str(source_acl.get("fallback_mode") or "partial_members").strip().lower() if isinstance(source_acl, dict) else "partial_members"
        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")
        enable_source_acl = bool(source_acl_mode == "inherit" and not has_manual_access_override)

        while processed < max_pages:
            # Best-effort cancellation check between API pages.
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            params = {
                "cql": cql,
                "start": int(start),
                "limit": int(page_size),
                "expand": "version",
            }
            resp = await _confluence_request(pool, "GET", search_url, params=params, headers=headers)
            data = resp.json() if resp is not None else {}

            links = data.get("_links") if isinstance(data, dict) else None
            link_base = links.get("base") if isinstance(links, dict) and isinstance(links.get("base"), str) else base_url

            results = data.get("results") if isinstance(data, dict) else None
            pages = results if isinstance(results, list) else []
            if not pages:
                listing_complete = True
                break

            batch_processed0 = processed
            for page in pages:
                if processed >= max_pages:
                    break

                # Per-item cancellation check (best-effort).
                try:
                    db.refresh(run)
                except Exception:
                    pass
                if str(run.status or "").lower() == "cancelled":
                    break

                page_id = str((page or {}).get("id") or "").strip() if isinstance(page, dict) else ""
                title = str((page or {}).get("title") or "").strip() if isinstance(page, dict) else ""
                lm = _confluence_extract_last_modified(page if isinstance(page, dict) else {})

                if effective_mode == "incremental" and _should_skip_timestamp_boundary_item(
                    item_id=page_id,
                    item_timestamp=lm,
                    cursor_timestamp=cursor_last_modified,
                    boundary_ids=cursor_last_modified_ids,
                ):
                    skipped_boundary_duplicates += 1
                    stats = dict(run.stats or {})
                    stats["skipped_boundary_duplicates"] = int(skipped_boundary_duplicates)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    continue

                if lm:
                    # Results are ordered by lastmodified ASC; track the latest processed
                    # timestamp plus the ids seen at that boundary to avoid equal-timestamp loss.
                    last_modified_seen, last_modified_ids_seen = _advance_timestamp_boundary(
                        last_timestamp=last_modified_seen,
                        boundary_ids=last_modified_ids_seen,
                        item_timestamp=lm,
                        item_id=page_id,
                    )

                page_links = page.get("_links") if isinstance(page, dict) else None
                webui = str(page_links.get("webui") or "").strip() if isinstance(page_links, dict) else ""
                if not webui and isinstance(page_links, dict):
                    webui = str(page_links.get("tinyui") or "").strip()

                page_url = _confluence_join_webui(base=str(link_base or base_url), webui=webui)
                if not page_url:
                    failed += 1
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=(page_id or title or "confluence_page"), exc=ValueError("missing page url"))
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    processed += 1
                    continue

                try:
                    # Optional: source ACL inheritance (Confluence page restrictions -> tenant groups).
                    effective_access = access
                    acl_provenance: dict | None = None
                    if (
                        not has_manual_access_override
                        and source_acl_mode == "inherit"
                        and page_id
                    ):
                        ext_ids: list[str] = []
                        gids: set[UUID] = set()
                        restricted_flag: bool | None = None
                        fallback_used = False
                        restrictions_url = f"{api_base}/content/{page_id}/restriction/byOperation/read"
                        restrictions_params = {"expand": "restrictions.group,restrictions.user"}
                        try:
                            r_resp = await _confluence_request(
                                pool,
                                "GET",
                                restrictions_url,
                                params=restrictions_params,
                                headers=headers,
                            )
                            if r_resp is not None and int(getattr(r_resp, "status_code", 0) or 0) == 404:
                                # Unrestricted (best-effort): treat as no override.
                                effective_access = access
                                restricted_flag = False
                            else:
                                r_data = r_resp.json() if r_resp is not None else {}
                                restricted, group_names, _user_count = _confluence_parse_read_restriction_groups(r_data)
                                if not restricted:
                                    effective_access = access
                                    restricted_flag = False
                                else:
                                    restricted_flag = True
                                    ext_ids = [_confluence_group_principal_key(n) for n in (group_names or [])]
                                    ext_ids = [e for e in ext_ids if e]
                                    gids = _resolve_tenant_group_ids_by_external_id(
                                        db,
                                        tenant_id=tenant_id,
                                        external_ids=ext_ids,
                                    )
                                    if gids:
                                        ordered = sorted(gids, key=lambda v: str(v))
                                        effective_access = {
                                            "mode": "partial_members",
                                            "partial_group_list": [str(gid) for gid in ordered],
                                        }
                                    else:
                                        effective_access = {"mode": source_acl_fallback_mode}
                                        fallback_used = True
                        except Exception:
                            # Fail-closed when source ACL is enabled but restrictions can't be fetched/parsed.
                            effective_access = {"mode": source_acl_fallback_mode}
                            restricted_flag = None
                            fallback_used = True

                        with contextlib.suppress(Exception):
                            from app.services.document_acl_provenance_service import build_document_acl_provenance

                            acl_provenance = build_document_acl_provenance(
                                connector_id="confluence_space",
                                connector_run_id=str(run_id),
                                effective_access=effective_access,
                                source_acl_mode=source_acl_mode,
                                source_acl_fallback_mode=source_acl_fallback_mode,
                                source_principal_external_ids=ext_ids,
                                mapped_group_ids=gids,
                                fallback_used=fallback_used,
                                restricted=restricted_flag,
                            )

                        updated_existing = _delta_sync_confluence_documents_acl_by_page_id(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=run.dataset_id,
                            base_url=base_url,
                            space_key=space_key,
                            page_id=page_id,
                            requested_by=requested_by,
                            access=effective_access,
                            acl_provenance=acl_provenance,
                        )
                        delta_acl_docs_updated += int(updated_existing)
                        if updated_existing:
                            delta_acl_pages_updated += 1

                    filename = None
                    if page_id:
                        base_name = f"{page_id}-{title}".strip("-").strip() if title else str(page_id)
                    else:
                        base_name = title or "confluence-page"
                    if base_name:
                        filename = base_name
                        if not filename.lower().endswith((".html", ".htm")):
                            filename = filename + ".html"

                    if ingest_method == "webui":
                        body = UrlUploadRequest(
                            url=page_url,
                            dataset_id=run.dataset_id,
                            filename=filename,
                            fetch_headers=auth_headers or None,
                            user_agent=user_agent,
                            parser_backend=str(parser_backend),
                            chunk_strategy=str(chunk_strategy),
                            pipeline=pipeline,  # type: ignore[arg-type]
                        )
                        doc = await _ingest_url_upload_request(
                            background_tasks=None,
                            body=body,
                            tenant_id=tenant_id,
                            account_id=requested_by,
                            db=db,
                        )
                    else:
                        # Fetch page HTML via REST (body.view) to avoid web UI session/cookie requirements.
                        if not page_id:
                            raise ValueError("missing page id")
                        content_url = f"{api_base}/content/{page_id}"
                        content_params = {"expand": "body.view,version"}
                        content_resp = await _confluence_request(
                            pool,
                            "GET",
                            content_url,
                            params=content_params,
                            headers=headers,
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

                        html_body = LocalHtmlIngestRequest(
                            html=full_html,
                            source_url=page_url,
                            dataset_id=run.dataset_id,
                            filename=filename,
                            parser_backend=str(parser_backend),
                            chunk_strategy=str(chunk_strategy),
                            pipeline=pipeline,  # type: ignore[arg-type]
                        )
                        doc = await _ingest_local_html_request(
                            background_tasks=None,
                            body=html_body,
                            tenant_id=tenant_id,
                            account_id=requested_by,
                            db=db,
                            ingestion_kind="upload_url",
                        )

                    _apply_document_access_from_config(
                        db,
                        tenant_id=tenant_id,
                        requested_by=requested_by,
                        doc=doc,
                        access=effective_access,
                        connector_id="confluence_space",
                    )

                    # Attach connector metadata (must not affect pipeline_hash).
                    try:
                        meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                        if lm:
                            lm_iso = _normalize_datetime_utc_iso(lm) or lm
                            meta0["source_last_modified_at"] = lm_iso
                            meta0["source_last_modified_source"] = "connector:confluence:last_modified"
                            meta0["source_last_modified_raw"] = meta0.get("source_last_modified_raw") or lm
                        if isinstance(acl_provenance, dict):
                            meta0["acl_provenance"] = dict(acl_provenance)
                        meta0["connector"] = {
                            "connector_id": "confluence_space",
                            "base_url": base_url,
                            "space_key": space_key,
                            "page_id": (page_id or None),
                            "page_title": (title or None),
                            "page_url": page_url,
                            "last_modified": (lm or None),
                            "run_id": str(run.id),
                            "mode": effective_mode,
                            "ingest_method": ingest_method,
                        }
                        doc.doc_metadata = meta0
                        _apply_connector_identity_metadata(
                            doc=doc,
                            run=run,
                            connector_id="confluence_space",
                            source_ref=(page_id or page_url),
                            source_id=(page_id or page_url),
                        )
                        db.commit()
                    except Exception:
                        # Best-effort: never fail the run due to metadata patching.
                        pass

                    db.add(
                        ConnectorRunDocument(
                            tenant_id=tenant_id,
                            run_id=run.id,
                            document_id=doc.id,
                            source_ref=(page_id or page_url)[:1000] or None,
                            status="created",
                        )
                    )
                    created += 1
                    created_doc_ids.append(doc.id)
                    if page_id:
                        observed_page_ids.add(page_id)

                    # Optional: ingest page attachments (bounded, best-effort).
                    if (
                        include_attachments
                        and page_id
                        and attachments_processed < max_total_attachments
                        and str(run.status or "").lower() != "cancelled"
                    ):
                        remaining_total = int(max_total_attachments) - int(attachments_processed)
                        per_page_limit_eff = int(min(int(max_attachments_per_page), max(0, remaining_total)))
                        if per_page_limit_eff > 0:
                            attachments_url = f"{api_base}/content/{page_id}/child/attachment"
                            attachments_params = {"start": 0, "limit": int(per_page_limit_eff)}
                            try:
                                att_resp = await _confluence_request(
                                    pool,
                                    "GET",
                                    attachments_url,
                                    params=attachments_params,
                                    headers=headers,
                                )
                                att_data = att_resp.json() if att_resp is not None else {}
                                att_refs = _confluence_extract_attachments(
                                    att_data if isinstance(att_data, dict) else {},
                                    link_base_fallback=str(link_base or base_url),
                                    limit=int(per_page_limit_eff),
                                )
                            except Exception as exc:  # noqa: BLE001
                                failed += 1
                                attachments_failed += 1
                                stats = dict(run.stats or {})
                                stats = _append_connector_error(stats, url=f"confluence_attachments:{page_id}", exc=exc)
                                run.stats = _finalize_connector_stats(stats)
                            else:
                                for aref in att_refs:
                                    if attachments_processed >= max_total_attachments:
                                        break

                                    # Per-attachment cancellation check (best-effort).
                                    try:
                                        db.refresh(run)
                                    except Exception:
                                        pass
                                    if str(run.status or "").lower() == "cancelled":
                                        break

                                    attachment_id = str(aref.get("attachment_id") or "").strip()
                                    filename_att = str(aref.get("filename") or "").strip()
                                    download_url = str(aref.get("download_url") or "").strip()
                                    attachments_processed += 1

                                    if not attachment_id or not download_url:
                                        attachments_skipped += 1
                                        continue

                                    # Quick skip for obvious unsupported types (URL ingest will enforce again).
                                    ext = Path(filename_att).suffix.lower()
                                    if ext and ext not in settings.allowed_extensions_list:
                                        attachments_skipped += 1
                                        continue

                                    try:
                                        att_body = UrlUploadRequest(
                                            url=download_url,
                                            dataset_id=run.dataset_id,
                                            filename=filename_att,
                                            fetch_headers=auth_headers or None,
                                            user_agent=user_agent,
                                            parser_backend=str(parser_backend),
                                            chunk_strategy=str(chunk_strategy),
                                            pipeline=pipeline,  # type: ignore[arg-type]
                                        )
                                        att_doc = await _ingest_url_upload_request(
                                            background_tasks=None,
                                            body=att_body,
                                            tenant_id=tenant_id,
                                            account_id=requested_by,
                                            db=db,
                                        )

                                        _apply_document_access_from_config(
                                            db,
                                            tenant_id=tenant_id,
                                            requested_by=requested_by,
                                            doc=att_doc,
                                            access=effective_access,
                                            connector_id="confluence_space",
                                        )

                                        # Attach connector metadata (must not affect pipeline_hash).
                                        try:
                                            meta_att = dict(getattr(att_doc, "doc_metadata", None) or {})
                                            if isinstance(acl_provenance, dict):
                                                meta_att["acl_provenance"] = dict(acl_provenance)
                                            meta_att["connector"] = _confluence_attachment_connector_metadata(
                                                base_url=base_url,
                                                space_key=space_key,
                                                page_id=(page_id or None),
                                                page_title=(title or None),
                                                page_url=page_url,
                                                attachment_id=attachment_id,
                                                filename=filename_att,
                                                download_url=download_url,
                                                run_id=str(run.id),
                                                mode=effective_mode,
                                                ingest_method=ingest_method,
                                            )
                                            att_doc.doc_metadata = meta_att
                                            _apply_connector_identity_metadata(
                                                doc=att_doc,
                                                run=run,
                                                connector_id="confluence_space",
                                                source_ref=(attachment_id or download_url),
                                                source_id=(attachment_id or download_url),
                                            )
                                        except Exception:
                                            # Best-effort: never fail the run due to metadata patching.
                                            pass

                                        db.add(
                                            ConnectorRunDocument(
                                                tenant_id=tenant_id,
                                                run_id=run.id,
                                                document_id=att_doc.id,
                                                source_ref=(attachment_id or download_url)[:1000] or None,
                                                status="created",
                                            )
                                        )
                                        created += 1
                                        created_doc_ids.append(att_doc.id)
                                        attachments_created += 1
                                    except Exception as exc:  # noqa: BLE001
                                        failed += 1
                                        attachments_failed += 1
                                        stats = dict(run.stats or {})
                                        stats = _append_connector_error(stats, url=(download_url or attachment_id), exc=exc)
                                        run.stats = _finalize_connector_stats(stats)
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=page_url, exc=exc)
                    run.stats = _finalize_connector_stats(stats)
                finally:
                    processed += 1
                    stats = dict(run.stats or {})
                    stats.update(
                        {
                            "processed_pages": int(processed),
                            "cursor": int(processed),
                            "created": int(created),
                            "failed": int(failed),
                            "processed_attachments": int(attachments_processed),
                            "created_attachments": int(attachments_created),
                            "failed_attachments": int(attachments_failed),
                            "skipped_attachments": int(attachments_skipped),
                            "skipped_boundary_duplicates": int(skipped_boundary_duplicates),
                            "document_ids": [str(d) for d in created_doc_ids],
                            "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                            "acl_delta_sync_updated_sources": int(delta_acl_pages_updated),
                        }
                    )
                    if last_modified_seen:
                        stats["last_modified"] = last_modified_seen
                        stats["last_modified_ids"] = sorted(last_modified_ids_seen)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()

            # If we reached the max_pages cap in the middle of an API batch, do not treat this
            # as a full listing (soft-delete must not run in this case).
            if processed >= max_pages and (batch_processed0 + len(pages)) > max_pages:
                stopped_mid_batch = True

            # Advance pagination by page size; Confluence returns stable paging via start+limit.
            start += int(len(pages))
            if processed >= max_pages:
                break
            if len(pages) < page_size:
                listing_complete = True
                break

        # If we stopped exactly at the page cap boundary, do a tiny probe to determine whether the
        # listing was actually complete (avoid incorrect soft-deletes when max_pages == total pages).
        if (
            effective_mode == "full"
            and soft_delete
            and run.dataset_id
            and observed_page_ids
            and (not listing_complete)
            and (not stopped_mid_batch)
            and processed >= max_pages
            and str(run.status or "").lower() != "cancelled"
        ):
            try:
                probe_params = {
                    "cql": cql,
                    "start": int(start),
                    "limit": 1,
                }
                probe = await _confluence_request(pool, "GET", search_url, params=probe_params, headers=headers)
                probe_data = probe.json() if probe is not None else {}
                probe_results = probe_data.get("results") if isinstance(probe_data, dict) else None
                probe_pages = probe_results if isinstance(probe_results, list) else []
                if not probe_pages:
                    listing_complete = True
            except Exception:
                listing_complete = False

        # Soft-delete only makes sense on a full listing.
        if effective_mode == "full" and soft_delete and run.dataset_id and observed_page_ids and listing_complete:
            now = _now()
            disabled = 0
            try:
                # Prefer Postgres JSONB filtering when available.
                docs = (
                    db.query(DBDocument)
                    .filter(
                        DBDocument.tenant_id == tenant_id,
                        DBDocument.dataset_id == run.dataset_id,
                        DBDocument.archived_at.is_(None),
                    )
                    .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "confluence_space")  # type: ignore[attr-defined]
                    .filter(DBDocument.doc_metadata["connector"]["space_key"].astext == space_key)  # type: ignore[attr-defined]
                    .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
                    .all()
                )
            except Exception:
                # Best-effort fallback: scan a bounded window.
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

            for doc in docs or []:
                meta = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
                conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
                if str(conn.get("connector_id") or "") != "confluence_space":
                    continue
                if str(conn.get("space_key") or "") != space_key:
                    continue
                if str(conn.get("base_url") or "") != base_url:
                    continue
                pid = str(conn.get("page_id") or "").strip()
                if not pid:
                    continue
                if pid in observed_page_ids:
                    continue
                if getattr(doc, "disabled_at", None) is None:
                    doc.disabled_at = now
                    disabled += 1

            if disabled:
                stats = dict(run.stats or {})
                stats["soft_deleted"] = int(disabled)
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        stats = dict(run.stats or {})
        stats.update(
            {
                "document_ids": [str(d) for d in created_doc_ids],
                "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                "acl_delta_sync_updated_sources": int(delta_acl_pages_updated),
                "skipped_boundary_duplicates": int(skipped_boundary_duplicates),
            }
        )
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        if enable_source_acl:
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
                        "base_url": base_url,
                        "space_key": space_key,
                        "mode": effective_mode,
                        "updated_documents": int(delta_acl_docs_updated),
                        "updated_pages": int(delta_acl_pages_updated),
                        "fallback_mode": source_acl_fallback_mode,
                    },
                )
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


async def _execute_jira_project_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for jira_project connector.

    Flow:
    - List issues in a Jira project (full or incremental based on state/sync_mode)
    - Render each issue into a structured local HTML document
    - Apply best-effort Jira source ACL inheritance from security level / comment visibility
    """
    db = SessionLocal()
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
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)

        base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
        project_key = str(cfg.get("project_key") or "").strip().upper()
        if not base_url or not project_key:
            raise ValueError("base_url and project_key are required")

        sync_mode = str(cfg.get("sync_mode") or "auto").strip().lower()
        if sync_mode not in {"auto", "full", "incremental"}:
            sync_mode = "auto"

        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        cursor_last_modified = str(state.get("last_modified") or "").strip() if isinstance(state, dict) else ""
        cursor_last_modified_ids = set(normalize_boundary_ids(state.get("last_modified_ids"))) if isinstance(state, dict) else set()

        effective_mode = sync_mode
        if effective_mode == "auto":
            effective_mode = "incremental" if cursor_last_modified else "full"
        if effective_mode == "incremental" and not cursor_last_modified:
            effective_mode = "full"

        max_issues = int(cfg.get("max_issues") or 50)
        max_issues = max(1, min(max_issues, 500))
        page_size = int(cfg.get("page_size") or 25)
        page_size = max(1, min(page_size, 100))
        include_comments = bool(cfg.get("include_comments", True))
        max_comments_per_issue = int(cfg.get("max_comments_per_issue") or 20)
        max_comments_per_issue = max(0, min(max_comments_per_issue, 200))
        custom_fields_raw = cfg.get("custom_fields")
        custom_fields_in = custom_fields_raw if isinstance(custom_fields_raw, list) else []
        custom_fields: list[str] = []
        custom_fields_seen: set[str] = set()
        for raw in custom_fields_in:
            key = str(raw or "").strip().lower()
            if not key:
                continue
            if len(key) > 80:
                continue
            if not re.fullmatch(r"customfield_\d+", key):
                continue
            if key in custom_fields_seen:
                continue
            custom_fields_seen.add(key)
            custom_fields.append(key)
            if len(custom_fields) >= 30:
                break
        include_attachments, max_attachments_per_issue, max_total_attachments = _jira_attachment_limits(cfg)
        include_linked_artifacts, max_linked_artifacts_per_issue, max_total_linked_artifacts = _jira_linked_artifact_limits(cfg)

        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "jira_ticket"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
        source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None
        extra_jql = str(cfg.get("jql") or "").strip()

        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
        auth_headers = _build_auth_headers(cfg)

        api_base = _jira_api_base_url(base_url)
        search_url = f"{api_base}/search"

        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": (user_agent or "MimirQ/1.0 (+jira_project)"),
        }
        headers.update(auth_headers)

        jql_parts = [f'project = "{project_key}"']
        if extra_jql:
            jql_parts.append(f"({extra_jql})")
        if effective_mode == "incremental" and cursor_last_modified:
            after = _jira_jql_updated_after(cursor_last_modified)
            if after:
                jql_parts.append(f'updated >= "{after}"')
        jql = " AND ".join(jql_parts) + " ORDER BY updated ASC"

        created = 0
        failed = 0
        processed = 0
        created_doc_ids: list[UUID] = []
        delta_acl_docs_updated = 0
        delta_acl_sources_updated = 0
        last_modified_seen: str | None = None
        last_modified_ids_seen: set[str] = set()
        observed_issue_urls: set[str] = set()
        removed_issues_reconciled = 0
        removed_documents_disabled = 0
        attachments_processed = 0
        attachments_created = 0
        removed_attachment_documents_disabled = 0
        linked_artifacts_processed = 0
        linked_artifacts_created = 0
        removed_linked_artifact_documents_disabled = 0
        skipped_boundary_duplicates = 0
        listing_complete = False
        total_issues_available: int | None = None

        stats0 = dict(run.stats or {})
        stats0.update(
            {
                "mode": effective_mode,
                "project_key": project_key,
                "base_url": base_url,
                "max_issues": int(max_issues),
                "page_size": int(page_size),
                "include_comments": bool(include_comments),
                "max_comments_per_issue": int(max_comments_per_issue),
                "include_attachments": bool(include_attachments),
                "max_attachments_per_issue": int(max_attachments_per_issue),
                "max_total_attachments": int(max_total_attachments),
                "include_linked_artifacts": bool(include_linked_artifacts),
                "max_linked_artifacts_per_issue": int(max_linked_artifacts_per_issue),
                "max_total_linked_artifacts": int(max_total_linked_artifacts),
                "processed_issues": 0,
                "processed_attachments": 0,
                "cursor": 0,
                "created": 0,
                "created_attachments": 0,
                "processed_linked_artifacts": 0,
                "created_linked_artifacts": 0,
                "removed_linked_artifact_documents_disabled": 0,
                "failed": 0,
                "skipped_boundary_duplicates": 0,
                "failed_urls": [],
                "errors": [],
                "error_groups": [],
                "removed_issues_reconciled": 0,
                "removed_documents_disabled": 0,
                "removed_attachment_documents_disabled": 0,
            }
        )
        if cursor_last_modified:
            stats0["cursor_in"] = cursor_last_modified
        run.stats = _finalize_connector_stats(stats0)
        db.commit()

        source_acl_mode = str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
        source_acl_fallback_mode = str(source_acl.get("fallback_mode") or "partial_members").strip().lower() if isinstance(source_acl, dict) else "partial_members"
        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")
        enable_source_acl = bool(source_acl_mode == "inherit" and not has_manual_access_override)

        pool = get_http_client_pool()
        start_at = 0

        while processed < max_issues:
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            page_request_size = int(min(page_size, max_issues - processed))
            params = {
                "jql": jql,
                "startAt": int(start_at),
                "maxResults": page_request_size,
                "fields": ",".join(
                    [
                        "summary",
                        "description",
                        "updated",
                        "issuetype",
                        "priority",
                        "status",
                        "labels",
                        "comment",
                        "security",
                        "attachment",
                        *custom_fields,
                    ]
                ),
                "expand": "renderedFields",
            }
            resp = await _jira_request(pool, "GET", search_url, params=params, headers=headers)
            data = resp.json() if resp is not None else {}
            total_raw = data.get("total") if isinstance(data, dict) else None
            if isinstance(total_raw, (int, float)) and not isinstance(total_raw, bool):
                total_issues_available = max(0, int(total_raw))
            issues = data.get("issues") if isinstance(data, dict) and isinstance(data.get("issues"), list) else []
            if not issues:
                if total_issues_available is None or start_at >= total_issues_available:
                    listing_complete = True
                break

            for issue in issues:
                if processed >= max_issues:
                    break

                try:
                    db.refresh(run)
                except Exception:
                    pass
                if str(run.status or "").lower() == "cancelled":
                    break

                issue_key = str((issue or {}).get("key") or "").strip() if isinstance(issue, dict) else ""
                issue_id = str((issue or {}).get("id") or "").strip() if isinstance(issue, dict) else ""
                issue_url = _jira_issue_url(base_url=base_url, issue_key=issue_key)
                updated = _jira_extract_issue_updated(issue if isinstance(issue, dict) else {})

                if effective_mode == "incremental" and _should_skip_timestamp_boundary_item(
                    item_id=issue_id,
                    item_timestamp=updated,
                    cursor_timestamp=cursor_last_modified,
                    boundary_ids=cursor_last_modified_ids,
                ):
                    skipped_boundary_duplicates += 1
                    stats = dict(run.stats or {})
                    stats["skipped_boundary_duplicates"] = int(skipped_boundary_duplicates)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    continue

                if updated:
                    last_modified_seen, last_modified_ids_seen = _advance_timestamp_boundary(
                        last_timestamp=last_modified_seen,
                        boundary_ids=last_modified_ids_seen,
                        item_timestamp=updated,
                        item_id=issue_id,
                    )

                if not issue_url:
                    failed += 1
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=(issue_key or issue_id or "jira_issue"), exc=ValueError("missing issue url"))
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()
                    processed += 1
                    continue

                observed_issue_urls.add(issue_url)

                try:
                    effective_access = access
                    acl_provenance: dict | None = None

                    if enable_source_acl:
                        ext_ids: list[str] = []
                        gids: set[UUID] = set()
                        restricted, ext_ids = _jira_issue_acl_principal_keys(
                            issue if isinstance(issue, dict) else {},
                            include_comments=include_comments,
                            max_comments=max_comments_per_issue,
                        )
                        fallback_used = False

                        if restricted:
                            try:
                                gids = _resolve_tenant_group_ids_by_external_id(
                                    db,
                                    tenant_id=tenant_id,
                                    external_ids=ext_ids,
                                )
                                if gids:
                                    ordered = sorted(gids, key=lambda v: str(v))
                                    effective_access = {
                                        "mode": "partial_members",
                                        "partial_group_list": [str(gid) for gid in ordered],
                                    }
                                else:
                                    effective_access = {"mode": source_acl_fallback_mode}
                                    fallback_used = True
                            except Exception:
                                effective_access = {"mode": source_acl_fallback_mode}
                                fallback_used = True

                            with contextlib.suppress(Exception):
                                from app.services.document_acl_provenance_service import build_document_acl_provenance

                                acl_provenance = build_document_acl_provenance(
                                    connector_id="jira_project",
                                    connector_run_id=str(run_id),
                                    effective_access=effective_access,
                                    source_acl_mode=source_acl_mode,
                                    source_acl_fallback_mode=source_acl_fallback_mode,
                                    source_principal_external_ids=ext_ids,
                                    mapped_group_ids=gids,
                                    fallback_used=fallback_used,
                                    restricted=restricted,
                                )

                            updated_existing = _delta_sync_jira_documents_acl_by_issue_url(
                                db,
                                tenant_id=tenant_id,
                                dataset_id=run.dataset_id,
                                base_url=base_url,
                                project_key=project_key,
                                issue_url=issue_url,
                                requested_by=requested_by,
                                access=effective_access,
                                acl_provenance=acl_provenance,
                            )
                            delta_acl_docs_updated += int(updated_existing)
                            if updated_existing:
                                delta_acl_sources_updated += 1

                    filename = f"{issue_key}.html" if issue_key else "jira-issue.html"
                    issue_html = _jira_render_issue_html(
                        base_url=base_url,
                        issue=issue if isinstance(issue, dict) else {},
                        include_comments=include_comments,
                        max_comments=max_comments_per_issue,
                    )
                    if not issue_html.strip():
                        raise ValueError("missing rendered issue html")

                    html_body = LocalHtmlIngestRequest(
                        html=issue_html,
                        source_url=issue_url,
                        dataset_id=run.dataset_id,
                        filename=filename,
                        parser_backend=str(parser_backend),
                        chunk_strategy=str(chunk_strategy),
                        pipeline=pipeline,  # type: ignore[arg-type]
                    )
                    doc = await _ingest_local_html_request(
                        background_tasks=None,
                        body=html_body,
                        tenant_id=tenant_id,
                        account_id=requested_by,
                        db=db,
                        ingestion_kind="upload_url",
                    )

                    _apply_document_access_from_config(
                        db,
                        tenant_id=tenant_id,
                        requested_by=requested_by,
                        doc=doc,
                        access=effective_access,
                        connector_id="jira_project",
                    )

                    try:
                        meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                        if updated:
                            lm_iso = _normalize_datetime_utc_iso(updated) or updated
                            meta0["source_last_modified_at"] = lm_iso
                            meta0["source_last_modified_source"] = JIRA_UPDATED_SOURCE
                            meta0["source_last_modified_raw"] = meta0.get("source_last_modified_raw") or updated
                        if isinstance(acl_provenance, dict):
                            meta0["acl_provenance"] = dict(acl_provenance)
                        meta0["connector"] = {
                            "connector_id": "jira_project",
                            "base_url": base_url,
                            "project_key": project_key,
                            "issue_id": (issue_id or None),
                            "issue_key": (issue_key or None),
                            "issue_url": issue_url,
                            "last_modified": (updated or None),
                            "run_id": str(run.id),
                            "mode": effective_mode,
                        }
                        doc.doc_metadata = meta0
                        _apply_connector_identity_metadata(
                            doc=doc,
                            run=run,
                            connector_id="jira_project",
                            source_ref=(issue_key or issue_id or issue_url),
                            source_id=(issue_id or issue_key or issue_url),
                        )
                        db.commit()
                    except Exception:
                        pass

                    db.add(
                        ConnectorRunDocument(
                            tenant_id=tenant_id,
                            run_id=run.id,
                            document_id=doc.id,
                            source_ref=(issue_key or issue_id or issue_url)[:1000] or None,
                            status="created",
                        )
                    )
                    created += 1
                    created_doc_ids.append(doc.id)

                    if (
                        include_linked_artifacts
                        and issue_url
                        and linked_artifacts_processed < max_total_linked_artifacts
                        and str(run.status or "").lower() != "cancelled"
                    ):
                        remaining_total = int(max_total_linked_artifacts) - int(linked_artifacts_processed)
                        per_issue_limit_eff = int(min(int(max_linked_artifacts_per_issue), max(0, remaining_total)))
                        linked_listing_complete = False
                        seen_link_urls: set[str] = set()

                        if per_issue_limit_eff > 0:
                            # Extract one extra URL to detect truncation (listing completeness).
                            extract_limit = per_issue_limit_eff + 1
                            urls = _jira_extract_linked_artifact_urls(
                                issue if isinstance(issue, dict) else {},
                                include_comments=include_comments,
                                max_comments=max_comments_per_issue,
                                limit=extract_limit,
                            )
                            linked_listing_complete = bool(len(urls) <= per_issue_limit_eff)
                            urls = urls[:per_issue_limit_eff]

                            for link_url in urls:
                                if linked_artifacts_processed >= max_total_linked_artifacts:
                                    linked_listing_complete = False
                                    break

                                try:
                                    db.refresh(run)
                                except Exception:
                                    pass
                                if str(run.status or "").lower() == "cancelled":
                                    linked_listing_complete = False
                                    break

                                link_url = str(link_url or "").strip()
                                if not link_url:
                                    continue
                                if link_url == issue_url:
                                    continue
                                if not _is_http_or_https_url(link_url):
                                    continue
                                seen_link_urls.add(link_url)
                                linked_artifacts_processed += 1

                                # Avoid leaking Jira credentials to third-party domains.
                                fetch_headers = auth_headers if (_jira_should_send_auth_headers(base_url=base_url, url=link_url) and auth_headers) else None

                                try:
                                    link_body = UrlUploadRequest(
                                        url=link_url,
                                        dataset_id=run.dataset_id,
                                        filename=None,
                                        fetch_headers=fetch_headers,
                                        user_agent=user_agent,
                                        parser_backend=str(parser_backend),
                                        chunk_strategy=str(chunk_strategy),
                                        pipeline=pipeline,  # type: ignore[arg-type]
                                    )
                                    link_doc = await _ingest_url_upload_request(
                                        background_tasks=None,
                                        body=link_body,
                                        tenant_id=tenant_id,
                                        account_id=requested_by,
                                        db=db,
                                    )

                                    _apply_document_access_from_config(
                                        db,
                                        tenant_id=tenant_id,
                                        requested_by=requested_by,
                                        doc=link_doc,
                                        access=effective_access,
                                        connector_id="jira_project",
                                    )

                                    try:
                                        meta_link = dict(getattr(link_doc, "doc_metadata", None) or {})
                                        if updated:
                                            lm_iso = _normalize_datetime_utc_iso(updated) or updated
                                            meta_link["source_last_modified_at"] = lm_iso
                                            meta_link["source_last_modified_source"] = JIRA_UPDATED_SOURCE
                                            meta_link["source_last_modified_raw"] = meta_link.get("source_last_modified_raw") or updated
                                        if isinstance(acl_provenance, dict):
                                            meta_link["acl_provenance"] = dict(acl_provenance)
                                        meta_link["connector"] = _jira_linked_artifact_connector_metadata(
                                            base_url=base_url,
                                            project_key=project_key,
                                            issue_id=(issue_id or None),
                                            issue_key=(issue_key or None),
                                            issue_url=issue_url,
                                            link_url=link_url,
                                            run_id=str(run.id),
                                            mode=effective_mode,
                                        )
                                        link_doc.doc_metadata = meta_link
                                        _apply_connector_identity_metadata(
                                            doc=link_doc,
                                            run=run,
                                            connector_id="jira_project",
                                            source_ref=link_url,
                                            source_id=link_url,
                                        )
                                        db.commit()
                                    except Exception:
                                        pass

                                    db.add(
                                        ConnectorRunDocument(
                                            tenant_id=tenant_id,
                                            run_id=run.id,
                                            document_id=link_doc.id,
                                            source_ref=link_url[:1000] or None,
                                            status="created",
                                        )
                                    )
                                    created += 1
                                    created_doc_ids.append(link_doc.id)
                                    linked_artifacts_created += 1
                                except Exception as exc:  # noqa: BLE001
                                    failed += 1
                                    stats = dict(run.stats or {})
                                    stats = _append_connector_error(stats, url=(link_url or "jira_linked_artifact"), exc=exc)
                                    run.stats = _finalize_connector_stats(stats)

                        if linked_listing_complete:
                            removed_linked_artifact_documents_disabled += _soft_disable_jira_linked_artifact_documents_missing_from_issue(
                                db,
                                tenant_id=tenant_id,
                                dataset_id=run.dataset_id,
                                base_url=base_url,
                                project_key=project_key,
                                issue_url=issue_url,
                                seen_link_urls=seen_link_urls,
                            )

                    if (
                        include_attachments
                        and issue_url
                        and attachments_processed < max_total_attachments
                        and str(run.status or "").lower() != "cancelled"
                    ):
                        remaining_total = int(max_total_attachments) - int(attachments_processed)
                        per_issue_limit_eff = int(min(int(max_attachments_per_issue), max(0, remaining_total)))
                        fields = issue.get("fields") if isinstance(issue, dict) and isinstance(issue.get("fields"), dict) else {}
                        raw_attachments = fields.get("attachment") if isinstance(fields.get("attachment"), list) else []
                        attachment_listing_complete = bool(per_issue_limit_eff >= len(raw_attachments))
                        seen_attachment_urls: set[str] = set()

                        if per_issue_limit_eff > 0:
                            attachment_refs = _jira_extract_attachments(issue if isinstance(issue, dict) else {}, limit=per_issue_limit_eff)
                            for aref in attachment_refs:
                                if attachments_processed >= max_total_attachments:
                                    attachment_listing_complete = False
                                    break

                                try:
                                    db.refresh(run)
                                except Exception:
                                    pass
                                if str(run.status or "").lower() == "cancelled":
                                    attachment_listing_complete = False
                                    break

                                attachment_id = str(aref.get("attachment_id") or "").strip()
                                filename_att = str(aref.get("filename") or "").strip()
                                download_url = str(aref.get("download_url") or "").strip()
                                attachments_processed += 1

                                if not attachment_id or not download_url:
                                    continue
                                seen_attachment_urls.add(download_url)

                                ext = Path(filename_att).suffix.lower()
                                if ext and ext not in settings.allowed_extensions_list:
                                    continue

                                try:
                                    att_body = UrlUploadRequest(
                                        url=download_url,
                                        dataset_id=run.dataset_id,
                                        filename=filename_att,
                                        fetch_headers=auth_headers or None,
                                        user_agent=user_agent,
                                        parser_backend=str(parser_backend),
                                        chunk_strategy=str(chunk_strategy),
                                        pipeline=pipeline,  # type: ignore[arg-type]
                                    )
                                    att_doc = await _ingest_url_upload_request(
                                        background_tasks=None,
                                        body=att_body,
                                        tenant_id=tenant_id,
                                        account_id=requested_by,
                                        db=db,
                                    )

                                    _apply_document_access_from_config(
                                        db,
                                        tenant_id=tenant_id,
                                        requested_by=requested_by,
                                        doc=att_doc,
                                        access=effective_access,
                                        connector_id="jira_project",
                                    )

                                    try:
                                        meta_att = dict(getattr(att_doc, "doc_metadata", None) or {})
                                        if updated:
                                            lm_iso = _normalize_datetime_utc_iso(updated) or updated
                                            meta_att["source_last_modified_at"] = lm_iso
                                            meta_att["source_last_modified_source"] = JIRA_UPDATED_SOURCE
                                            meta_att["source_last_modified_raw"] = meta_att.get("source_last_modified_raw") or updated
                                        if isinstance(acl_provenance, dict):
                                            meta_att["acl_provenance"] = dict(acl_provenance)
                                        meta_att["connector"] = _jira_attachment_connector_metadata(
                                            base_url=base_url,
                                            project_key=project_key,
                                            issue_id=(issue_id or None),
                                            issue_key=(issue_key or None),
                                            issue_url=issue_url,
                                            attachment_id=attachment_id,
                                            filename=filename_att,
                                            download_url=download_url,
                                            run_id=str(run.id),
                                            mode=effective_mode,
                                        )
                                        att_doc.doc_metadata = meta_att
                                        _apply_connector_identity_metadata(
                                            doc=att_doc,
                                            run=run,
                                            connector_id="jira_project",
                                            source_ref=(attachment_id or download_url),
                                            source_id=(attachment_id or download_url),
                                        )
                                        db.commit()
                                    except Exception:
                                        pass

                                    db.add(
                                        ConnectorRunDocument(
                                            tenant_id=tenant_id,
                                            run_id=run.id,
                                            document_id=att_doc.id,
                                            source_ref=(attachment_id or download_url)[:1000] or None,
                                            status="created",
                                        )
                                    )
                                    created += 1
                                    created_doc_ids.append(att_doc.id)
                                    attachments_created += 1
                                except Exception as exc:  # noqa: BLE001
                                    failed += 1
                                    stats = dict(run.stats or {})
                                    stats = _append_connector_error(stats, url=(download_url or attachment_id), exc=exc)
                                    run.stats = _finalize_connector_stats(stats)

                        if attachment_listing_complete:
                            removed_attachment_documents_disabled += _soft_disable_jira_attachment_documents_missing_from_issue(
                                db,
                                tenant_id=tenant_id,
                                dataset_id=run.dataset_id,
                                base_url=base_url,
                                project_key=project_key,
                                issue_url=issue_url,
                                seen_attachment_urls=seen_attachment_urls,
                            )
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    stats = dict(run.stats or {})
                    stats = _append_connector_error(stats, url=(issue_url or issue_key or issue_id or "jira_issue"), exc=exc)
                    run.stats = _finalize_connector_stats(stats)
                finally:
                    processed += 1
                    stats = dict(run.stats or {})
                    stats.update(
                        {
                            "processed_issues": int(processed),
                            "processed_attachments": int(attachments_processed),
                            "processed_linked_artifacts": int(linked_artifacts_processed),
                            "cursor": int(processed),
                            "created": int(created),
                            "created_attachments": int(attachments_created),
                            "created_linked_artifacts": int(linked_artifacts_created),
                            "failed": int(failed),
                            "skipped_boundary_duplicates": int(skipped_boundary_duplicates),
                            "document_ids": [str(d) for d in created_doc_ids],
                            "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
                            "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
                            "removed_issues_reconciled": int(removed_issues_reconciled),
                            "removed_documents_disabled": int(removed_documents_disabled),
                            "removed_attachment_documents_disabled": int(removed_attachment_documents_disabled),
                            "removed_linked_artifact_documents_disabled": int(removed_linked_artifact_documents_disabled),
                        }
                    )
                    if last_modified_seen:
                        stats["last_modified"] = last_modified_seen
                        stats["last_modified_ids"] = sorted(last_modified_ids_seen)
                    run.stats = _finalize_connector_stats(stats)
                    db.commit()

            start_at += int(len(issues))
            if total_issues_available is not None and start_at >= total_issues_available:
                listing_complete = True
            if len(issues) < page_request_size:
                listing_complete = True
                break

        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
            return

        if effective_mode == "full" and run.dataset_id and listing_complete:
            try:
                removed_issues_reconciled, removed_documents_disabled = _soft_disable_jira_documents_missing_from_full_sync(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    base_url=base_url,
                    project_key=project_key,
                    seen_issue_urls=observed_issue_urls,
                )
            except Exception as exc:  # noqa: BLE001
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=f"jira://{project_key}", exc=exc)
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        stats = dict(run.stats or {})
        stats.update(
	            {
	                "document_ids": [str(d) for d in created_doc_ids],
	                "acl_delta_sync_updated_documents": int(delta_acl_docs_updated),
	                "acl_delta_sync_updated_sources": int(delta_acl_sources_updated),
	                "removed_issues_reconciled": int(removed_issues_reconciled),
	                "removed_documents_disabled": int(removed_documents_disabled),
	                "processed_attachments": int(attachments_processed),
	                "created_attachments": int(attachments_created),
	                "removed_attachment_documents_disabled": int(removed_attachment_documents_disabled),
	                "processed_linked_artifacts": int(linked_artifacts_processed),
	                "created_linked_artifacts": int(linked_artifacts_created),
	                "removed_linked_artifact_documents_disabled": int(removed_linked_artifact_documents_disabled),
	                "skipped_boundary_duplicates": int(skipped_boundary_duplicates),
	            }
	        )
        if last_modified_seen:
            stats["last_modified"] = last_modified_seen
            stats["last_modified_ids"] = sorted(last_modified_ids_seen)
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = _connector_run_completion_status(created=created, failed=failed)
        if enable_source_acl:
            with contextlib.suppress(Exception):
                from app.services.audit_log_service import audit_log_event

                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=requested_by,
                    action="jira_project.source_acl.delta_sync",
                    resource_type="connector_run",
                    resource_id=str(run_id),
                    details={
                        "dataset_id": str(run.dataset_id),
                        "connector_id": "jira_project",
                        "base_url": base_url,
                        "project_key": project_key,
                        "mode": effective_mode,
                        "updated_documents": int(delta_acl_docs_updated),
                        "updated_sources": int(delta_acl_sources_updated),
                        "fallback_mode": source_acl_fallback_mode,
                    },
                )
        db.commit()
        with contextlib.suppress(Exception):
            _sync_connector_config_from_run(db, run=run)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
                with contextlib.suppress(Exception):
                    _sync_connector_config_from_run(db, run=run)
    finally:
        db.close()


@router.post("/runs", response_model=ConnectorRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_connector_run(
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Create a connector run (currently supports url_batch).

    Requires dataset write permission.
    """
    connector_id = str(payload.connector_id or "").strip()
    url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space", "jira_project"}
    db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}

    if connector_id in url_connectors and not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)
    if connector_id in db_catalog_connectors and not bool(getattr(settings, "DB_CATALOG_ENABLED", False)):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, payload.dataset_id)

    if connector_id == "url_batch":
        cfg = UrlBatchConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "web_crawl":
        cfg = WebCrawlConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "github_repo":
        cfg = GitHubRepoConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "drive_files":
        cfg = DriveFilesConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "minio_bucket":
        cfg = MinioBucketConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "confluence_space":
        cfg = ConfluenceSpaceConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "jira_project":
        cfg = JiraProjectConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "mysql_catalog":
        cfg = MySQLCatalogConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "sqlserver_catalog":
        cfg = SQLServerCatalogConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    else:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)

    # Validate tenant groups referenced in config (fail-closed; prevents typos silently weakening ACLs).
    group_ids_to_check: list[UUID] = []
    access = getattr(cfg, "access", None)
    group_ids_to_check.extend(list(getattr(access, "partial_group_list", None) or []))
    source_acl = getattr(cfg, "source_acl", None)
    for rule in getattr(source_acl, "group_mappings", None) or []:
        gid = getattr(rule, "group_id", None)
        if gid:
            group_ids_to_check.append(gid)

    if group_ids_to_check:
        missing = _unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=group_ids_to_check)
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tenant groups: {', '.join(missing[:20])}")

    run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        connector_id=connector_id,
        requested_by=account_id,
        status="pending",
        config=cfg_dict,
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Execute asynchronously after response (prefer queue when enabled).
    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        job_id = f"connector:{tenant_id}:{run.id}"
        task_id = None
        try:
            task_id = await enqueue_connector_run(tenant_id=tenant_id, run_id=run.id, requested_by=account_id, job_id=job_id)
        except Exception:
            task_id = None
        if task_id:
            run.task_id = task_id
            db.commit()
            db.refresh(run)
            return _run_out(run)

    # Fallback: API background tasks.
    if connector_id == "url_batch":
        background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "web_crawl":
        background_tasks.add_task(_execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "github_repo":
        background_tasks.add_task(_execute_github_repo_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "drive_files":
        background_tasks.add_task(_execute_drive_files_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "minio_bucket":
        background_tasks.add_task(_execute_minio_bucket_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "confluence_space":
        background_tasks.add_task(_execute_confluence_space_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "jira_project":
        background_tasks.add_task(_execute_jira_project_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
        background_tasks.add_task(_execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)

    return _run_out(run)


@router.get("/runs", response_model=ConnectorRunListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_connector_runs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    dataset_id: UUID | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List connector runs (requires dataset write permission for each returned run's dataset)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorRun).filter(ConnectorRun.tenant_id == tenant_id)
    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorRun.dataset_id == dataset_id)

    total = int(query.count())
    runs = (
        query.options(selectinload(ConnectorRun.documents))
        .order_by(ConnectorRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # If dataset_id isn't provided, filter to writable datasets only (avoid leaking URLs/config to readers).
    if not dataset_id:
        allowed: list[ConnectorRun] = []
        for run in runs:
            if not run.dataset_id:
                continue
            try:
                ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
                DatasetService.assert_dataset_writable(db, ds, account_id)
            except HTTPException:
                continue
            allowed.append(run)
        runs = allowed

    summaries = _fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[r.id for r in runs],
    )

    return {"total": total, "items": [_run_out(r, acl_summary=summaries.get(r.id)) for r in runs]}


@router.get("/runs/{run_id}", response_model=ConnectorRunOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get connector run detail (requires dataset write permission)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=CONNECTOR_RUN_NOT_FOUND_DETAIL)

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    summary = _fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id],
    ).get(run.id)

    return _run_out(run, acl_summary=summary)


def _extract_failed_urls(stats: dict) -> list[str]:
    urls: list[str] = []
    raw_failed = stats.get("failed_urls")
    if isinstance(raw_failed, list):
        urls = [str(u or "").strip() for u in raw_failed if str(u or "").strip()]
    if not urls:
        raw_errors = stats.get("errors")
        if isinstance(raw_errors, list):
            urls = [str((e or {}).get("url") or "").strip() for e in raw_errors if isinstance(e, dict)]
            urls = [u for u in urls if u]
    # Dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


@router.post("/runs/{run_id}/retry-failed", response_model=ConnectorRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_failed_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new connector run that retries only the failed URLs (best-effort)."""
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)

    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=CONNECTOR_RUN_NOT_FOUND_DETAIL)

    status = str(run.status or "").lower()
    if status in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="Connector run is still active")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    stats = dict(run.stats or {})
    failed_urls = _extract_failed_urls(stats)
    # Keep it bounded (web_crawl max_pages <= 500).
    failed_urls = failed_urls[:500]
    if not failed_urls:
        raise HTTPException(status_code=400, detail="No failed URLs to retry")

    base_cfg = dict(run.config or {})
    connector_id = str(run.connector_id or "").strip()
    new_connector_id = "url_batch"
    new_cfg: dict[str, Any] = {"urls": failed_urls}

    if connector_id == "url_batch":
        new_cfg = dict(base_cfg)
        new_cfg["urls"] = failed_urls
    elif connector_id == "web_crawl":
        for k in ("filename", "user_agent", "auth", "parser_backend", "chunk_strategy", "pipeline", "access"):
            if k in base_cfg:
                new_cfg[k] = base_cfg.get(k)
    else:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)

    new_run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=run.dataset_id,
        connector_id=new_connector_id,
        requested_by=account_id,
        status="pending",
        config=new_cfg,
        stats={"retry_of": str(run.id), "retry_kind": "failed_only"},
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        job_id = f"connector:{tenant_id}:{new_run.id}"
        task_id = None
        try:
            task_id = await enqueue_connector_run(tenant_id=tenant_id, run_id=new_run.id, requested_by=account_id, job_id=job_id)
        except Exception:
            task_id = None
        if task_id:
            new_run.task_id = task_id
            db.commit()
            db.refresh(new_run)
            return _run_out(new_run)

    background_tasks.add_task(_execute_url_batch_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    return _run_out(new_run)


@router.post("/runs/{run_id}/resume", response_model=ConnectorRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def resume_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new connector run that resumes from where the previous run stopped (best-effort)."""
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)

    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=CONNECTOR_RUN_NOT_FOUND_DETAIL)

    status = str(run.status or "").lower()
    if status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=400, detail="Connector run is not resumable")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    connector_id = str(run.connector_id or "").strip()
    connector_definition = get_connector_definition(connector_id)
    if connector_definition is None or not connector_definition.supports_resume:
        raise HTTPException(status_code=400, detail=f"Resume is not supported for {connector_id or 'this connector'}")

    base_cfg = dict(run.config or {})
    stats = dict(run.stats or {})
    new_cfg = dict(base_cfg)
    resume_stats: dict[str, Any] = {"resume_of": str(run.id)}

    if connector_id == "url_batch":
        cursor_raw = stats.get("cursor", stats.get("processed_urls", 0))
        try:
            cursor = max(0, int(cursor_raw or 0))
        except Exception:
            cursor = 0

        urls = base_cfg.get("urls") if isinstance(base_cfg.get("urls"), list) else []
        urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
        remaining = urls[cursor:] if cursor < len(urls) else []
        if not remaining:
            raise HTTPException(status_code=400, detail="No remaining URLs to resume")
        new_cfg["urls"] = remaining
        resume_stats["resume_cursor"] = int(cursor)
    else:
        existing_state = base_cfg.get("_state") if isinstance(base_cfg.get("_state"), dict) else {}
        resume_state = build_persisted_state(
            connector_id=connector_id,
            existing_state=dict(existing_state or {}),
            stats=stats,
            run_id=run.id,
        )
        cursor = get_resume_cursor(resume_state)
        total_key = next((key for key in connector_definition.state_keys if key != "cursor"), None)
        has_incremental_manifest = bool(normalize_source_manifest(resume_state.get("source_manifest")))
        if total_key and not has_incremental_manifest:
            try:
                total_items = max(0, int(stats.get(total_key) or 0))
            except Exception:
                total_items = 0
            if total_items > 0 and cursor >= total_items:
                raise HTTPException(status_code=400, detail="No remaining items to resume")
        if not resume_state:
            raise HTTPException(status_code=400, detail="No saved resume state found")
        new_cfg["_state"] = resume_state
        resume_stats["resume_cursor"] = int(cursor)

    new_run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        requested_by=account_id,
        status="pending",
        config=new_cfg,
        stats=resume_stats,
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        job_id = f"connector:{tenant_id}:{new_run.id}"
        task_id = None
        try:
            task_id = await enqueue_connector_run(tenant_id=tenant_id, run_id=new_run.id, requested_by=account_id, job_id=job_id)
        except Exception:
            task_id = None
        if task_id:
            new_run.task_id = task_id
            db.commit()
            db.refresh(new_run)
            return _run_out(new_run)

    if connector_id == "url_batch":
        background_tasks.add_task(_execute_url_batch_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "web_crawl":
        background_tasks.add_task(_execute_web_crawl_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "github_repo":
        background_tasks.add_task(_execute_github_repo_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "drive_files":
        background_tasks.add_task(_execute_drive_files_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "minio_bucket":
        background_tasks.add_task(_execute_minio_bucket_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)
    return _run_out(new_run)


@router.post("/runs/{run_id}/cancel", response_model=ConnectorRunOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def cancel_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Cancel a running connector run (best-effort)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=CONNECTOR_RUN_NOT_FOUND_DETAIL)

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    status = str(run.status or "").lower()
    if status in {"completed", "failed"}:
        return _run_out(run)

    run.status = "cancelled"
    run.finished_at = _now()
    db.commit()
    db.refresh(run)

    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)) and isinstance(getattr(run, "task_id", None), str) and run.task_id:
        try:
            from arq.jobs import Job as job_cls
        except ImportError:
            job_cls = None  # type: ignore[assignment]
        if job_cls is not None:
            try:
                q = await get_queue()
            except Exception:
                q = None
            if q is not None:
                queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
                job = job_cls(str(run.task_id), q, _queue_name=queue_name)
                with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                    await job.abort(timeout=0.2)
    return _run_out(run)


@router.get("/configs", response_model=ConnectorConfigListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_connector_configs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    dataset_id: UUID | None = None,
    connector_id: str | None = None,
    enabled: bool | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List saved connector configurations.

    Note: configs may contain secrets (even if encrypted); we enforce dataset write permission
    semantics similar to connector runs to avoid leaking URLs/auth details to readers.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorConfig).filter(ConnectorConfig.tenant_id == tenant_id)
    if dataset_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)
        query = query.filter(ConnectorConfig.dataset_id == dataset_id)
    if connector_id:
        query = query.filter(ConnectorConfig.connector_id == str(connector_id))
    if enabled is not None:
        query = query.filter(ConnectorConfig.enabled.is_(bool(enabled)))

    total = int(query.count())
    items = (
        query.order_by(ConnectorConfig.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # If dataset_id isn't provided, filter to writable datasets only.
    if dataset_id is None:
        allowed: list[ConnectorConfig] = []
        for cfg in items:
            try:
                ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
                DatasetService.assert_dataset_writable(db, ds, account_id)
            except HTTPException:
                continue
            allowed.append(cfg)
        items = allowed

    return {"total": total, "items": [_config_out(c) for c in items]}


@router.post("/configs", response_model=ConnectorConfigOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_connector_config(
    payload: ConnectorConfigCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    cfg_dict = encrypt_connector_config_secrets(dict(payload.config or {}))

    cfg = ConnectorConfig(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        connector_id=str(payload.connector_id or "").strip(),
        name=str(payload.name or "").strip(),
        enabled=bool(payload.enabled),
        schedule_cron=(str(payload.schedule_cron).strip() if isinstance(payload.schedule_cron, str) and payload.schedule_cron.strip() else None),
        config=cfg_dict,
        state={},
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return _config_out(cfg)


@router.put("/configs/{config_id}", response_model=ConnectorConfigOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_connector_config(
    config_id: UUID,
    payload: ConnectorConfigUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update a saved connector configuration (best-effort)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    if payload.name is not None:
        cfg.name = str(payload.name or "").strip()  # type: ignore[assignment]
    if payload.enabled is not None:
        cfg.enabled = bool(payload.enabled)  # type: ignore[assignment]
    if payload.schedule_cron is not None:
        cfg.schedule_cron = (str(payload.schedule_cron).strip() if str(payload.schedule_cron or "").strip() else None)  # type: ignore[assignment]
    if payload.config is not None:
        cfg.config = encrypt_connector_config_secrets(dict(payload.config or {}))  # type: ignore[assignment]
    if payload.state is not None:
        cfg.state = dict(payload.state or {})  # type: ignore[assignment]

    db.commit()
    db.refresh(cfg)
    return _config_out(cfg)


@router.delete("/configs/{config_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_connector_config(
    config_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    db.delete(cfg)
    db.commit()
    return Response(status_code=204)


@router.post("/configs/{config_id}/run", response_model=ConnectorRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def run_connector_config(
    config_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a connector run from a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    connector_id = str(cfg.connector_id or "").strip()
    url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space", "jira_project"}
    db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}
    if connector_id in url_connectors and not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=URL_INGEST_DISABLED_DETAIL)
    if connector_id in db_catalog_connectors and not bool(getattr(settings, "DB_CATALOG_ENABLED", False)):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")

    run_cfg = dict(cfg.config or {})
    connector_definition = get_connector_definition(connector_id)
    if connector_definition is not None and connector_definition.supports_incremental:
        run_cfg["_state"] = dict(cfg.state or {})

    run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=connector_id,
        requested_by=account_id,
        status="pending",
        config=run_cfg,
        stats={"config_id": str(cfg.id)},
    )
    db.add(run)
    cfg.last_run_at = _now()  # type: ignore[assignment]
    cfg.last_error = None  # type: ignore[assignment]
    db.commit()
    db.refresh(run)

    # Execute asynchronously after response.
    if connector_id == "url_batch":
        background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "web_crawl":
        background_tasks.add_task(_execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "github_repo":
        background_tasks.add_task(_execute_github_repo_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "drive_files":
        background_tasks.add_task(_execute_drive_files_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "minio_bucket":
        background_tasks.add_task(_execute_minio_bucket_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "confluence_space":
        background_tasks.add_task(_execute_confluence_space_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "jira_project":
        background_tasks.add_task(_execute_jira_project_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
        background_tasks.add_task(_execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_CONNECTOR_ID_DETAIL)

    return _run_out(run)


@router.post("/configs/{config_id}/reconcile", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def reconcile_connector_config(
    config_id: UUID,
    apply: Annotated[bool, Query(description='Apply the reconcile plan; default is dry-run')] = False,
    sample_limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Reconcile connector-managed documents for a saved config using the last known local source set.

    Single-node scope:
    - dry-run: show stale / disabled / missing refs
    - apply: disable stale docs and re-enable matching disabled docs
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    desired_refs = resolve_connector_reconcile_source_refs(
        connector_id=str(cfg.connector_id or "").strip(),
        config=dict(cfg.config or {}),
        state=dict(cfg.state or {}),
    )
    if not desired_refs:
        raise HTTPException(
            status_code=400,
            detail="No reconcile source manifest available for this connector config",
        )

    docs = (
        db.query(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == cfg.dataset_id)
        .all()
    )
    report = plan_connector_reconcile(
        connector_id=str(cfg.connector_id or "").strip(),
        config_id=str(cfg.id),
        dataset_id=str(cfg.dataset_id),
        documents=docs,
        desired_source_refs=desired_refs,
        apply=bool(apply),
        now=_now(),
        sample_limit=int(sample_limit),
    )

    if apply:
        db.commit()

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="connectors.reconcile.apply" if apply else "connectors.reconcile.dry_run",
        resource_type="connector_config",
        resource_id=str(cfg.id),
        details={
            "connector_id": str(cfg.connector_id or ""),
            "dataset_id": str(cfg.dataset_id),
            "desired_source_refs": int(report.get("desired_source_refs") or 0),
            "stale_source_refs": int(report.get("stale_source_refs") or 0),
            "reenable_source_refs": int(report.get("reenable_source_refs") or 0),
            "missing_source_refs": int(report.get("missing_source_refs") or 0),
            "disabled_documents": int(report.get("disabled_documents") or 0),
            "reenabled_documents": int(report.get("reenabled_documents") or 0),
        },
    )
    db.commit()
    return report


@router.post("/scheduled/tick", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def scheduled_tick(
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Evaluate saved connector schedules and enqueue due runs (best-effort).

    This endpoint is intentionally simple and deterministic; it is a "tick hook" for an external scheduler.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    now = _now()
    rows = (
        db.query(ConnectorConfig)
        .filter(
            ConnectorConfig.tenant_id == tenant_id,
            ConnectorConfig.enabled.is_(True),
            ConnectorConfig.schedule_cron.isnot(None),
        )
        .order_by(ConnectorConfig.created_at.asc())
        .limit(200)
        .all()
    )

    enqueued = 0
    skipped = 0
    for cfg in rows:
        schedule = str(cfg.schedule_cron or "").strip()
        if not schedule:
            skipped += 1
            continue
        if not _schedule_due(schedule=schedule, now=now, last_run_at=(cfg.last_run_at or None)):
            skipped += 1
            continue
        # Best-effort permission enforcement: skip datasets the caller can't write.
        try:
            ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
            DatasetService.assert_dataset_writable(db, ds, account_id)
        except HTTPException:
            skipped += 1
            continue

        # Create run and enqueue execution.
        connector_id = str(cfg.connector_id or "").strip()
        run_cfg = dict(cfg.config or {})
        connector_definition = get_connector_definition(connector_id)
        if connector_definition is not None and connector_definition.supports_incremental:
            run_cfg["_state"] = dict(cfg.state or {})

        run = ConnectorRun(
            tenant_id=tenant_id,
            dataset_id=cfg.dataset_id,
            connector_id=connector_id,
            requested_by=account_id,
            status="pending",
            config=run_cfg,
            stats={"config_id": str(cfg.id), "scheduled": True},
        )
        db.add(run)
        cfg.last_run_at = now  # type: ignore[assignment]
        cfg.last_error = None  # type: ignore[assignment]
        db.commit()
        db.refresh(run)

        url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space", "jira_project"}
        db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}

        if connector_id in url_connectors and not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
            run.status = "failed"
            run.error_message = "url_ingest_disabled"
            run.finished_at = now
            cfg.last_error = "url_ingest_disabled"  # type: ignore[assignment]
            db.commit()
            enqueued += 1
            continue
        if connector_id in db_catalog_connectors and not bool(getattr(settings, "DB_CATALOG_ENABLED", False)):
            run.status = "failed"
            run.error_message = "db_catalog_disabled"
            run.finished_at = now
            cfg.last_error = "db_catalog_disabled"  # type: ignore[assignment]
            db.commit()
            enqueued += 1
            continue

        if connector_id == "url_batch":
            background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "web_crawl":
            background_tasks.add_task(_execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "github_repo":
            background_tasks.add_task(_execute_github_repo_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "drive_files":
            background_tasks.add_task(_execute_drive_files_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "minio_bucket":
            background_tasks.add_task(_execute_minio_bucket_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "confluence_space":
            background_tasks.add_task(_execute_confluence_space_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "jira_project":
            background_tasks.add_task(_execute_jira_project_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
            background_tasks.add_task(_execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        else:
            # Unknown connector: mark as failed (best-effort) and continue.
            run.status = "failed"
            run.error_message = "unsupported_connector_id"
            run.finished_at = now
            cfg.last_error = "unsupported_connector_id"  # type: ignore[assignment]
            db.commit()
        enqueued += 1

    return {"enqueued": int(enqueued), "skipped": int(skipped)}
