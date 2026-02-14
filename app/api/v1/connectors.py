"""
Connector API (enterprise ingestion framework).

This is a minimal v1 implementation focused on:
- URL batch ingestion as the first connector
- Run tracking (status/stats/error)
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import ValidationError
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
    _resolve_writable_dataset,
)
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.http_client import get_http_client_pool
from app.core.secrets import decrypt_connector_config_secrets, encrypt_connector_config_secrets, redact_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.connector_config import ConnectorConfig
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.services.document_permission_service import DocumentPermissionService
from app.services.security_redaction import redact_connection_info
from app.services.web_crawler import crawl_site
from app.tasks.queue import enqueue_connector_run, get_queue

router = APIRouter()
_DB_CONNECTOR_IDS = {"mysql_catalog", "sqlserver_catalog"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _run_out(run: ConnectorRun) -> ConnectorRunOut:
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
    if connector_id == "url_batch":
        state = dict(getattr(cfg, "state", None) or {})
        with contextlib.suppress(Exception):
            state["cursor"] = int(stats.get("cursor", 0) or 0)
            state["total_urls"] = int(stats.get("total_urls", 0) or 0)
            state["last_run_id"] = str(run.id)
        cfg.state = state  # type: ignore[assignment]
    elif connector_id == "confluence_space":
        state = dict(getattr(cfg, "state", None) or {})
        with contextlib.suppress(Exception):
            last_modified = str(stats.get("last_modified") or "").strip()
            if last_modified:
                state["last_modified"] = last_modified
            state["last_run_id"] = str(run.id)
        cfg.state = state  # type: ignore[assignment]

    db.commit()


@router.get("", response_model=list[ConnectorInfo])
def list_connectors() -> list[ConnectorInfo]:
    """List available connectors (static registry)."""
    return [
        ConnectorInfo(
            id="url_batch",
            name="URL 批量导入",
            description="从多个 http(s) URL 拉取内容并入库（支持 URL_INGEST_* 安全开关）",
            supports_incremental=True,
        ),
        ConnectorInfo(
            id="web_crawl",
            name="网站抓取（站点级）",
            description="从站点种子 URL 开始抓取链接并批量入库（支持 Cookie/Bearer/Basic 登录态；配置中的密钥会被加密存储并在响应中脱敏）",
            supports_incremental=False,
        ),
        ConnectorInfo(
            id="github_repo",
            name="GitHub Repo 导入",
            description="从 GitHub 仓库列出文件并通过 raw.githubusercontent.com 拉取入库（可选 Bearer token；用于私有仓库/更高 API 限额）",
            supports_incremental=False,
        ),
        ConnectorInfo(
            id="drive_files",
            name="Google Drive 文件导入（链接）",
            description="从 Google Drive 文件分享链接解析 file_id 并构造直链下载入库（仅文件；不支持文件夹）",
            supports_incremental=False,
        ),
        ConnectorInfo(
            id="minio_bucket",
            name="MinIO/S3 Bucket 导入",
            description="列出 MinIO bucket 对象并用 presigned URL 拉取入库（需要 MINIO_ENABLED=true；URL_INGEST 需允许访问 MinIO 端点）",
            supports_incremental=False,
        ),
        ConnectorInfo(
            id="confluence_space",
            name="Confluence Space 导入",
            description="从 Confluence Space 列出页面并入库（支持增量 cursor；配置中的 Cookie/Token/Password 会被加密存储并在响应中脱敏）",
            supports_incremental=True,
        ),
        ConnectorInfo(
            id="sqlserver_catalog",
            name="SQLServer Catalog 导入",
            description="从 SQLServer 同步 schema/table/column 目录与安全画像（仅聚合统计；不外发原始行）",
            supports_incremental=True,
        ),
        ConnectorInfo(
            id="mysql_catalog",
            name="MySQL Catalog 导入",
            description="从 MySQL 同步 schema/table/column 目录与安全画像（仅聚合统计；不外发原始行）",
            supports_incremental=True,
        ),
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
    elif connector_id == "mysql_catalog":
        cfg_obj = MySQLCatalogConnectorConfig.model_validate(config or {})
    elif connector_id == "sqlserver_catalog":
        cfg_obj = SQLServerCatalogConnectorConfig.model_validate(config or {})
    else:
        raise ValueError("Unsupported connector_id")

    cfg_dict = cfg_obj.model_dump(exclude_none=True)
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

    return checks, warnings


@router.post("/validate", response_model=ConnectorValidateResponse)
async def validate_connector_config(
    payload: ConnectorValidateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


async def _execute_db_catalog_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
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

                # Apply document-level ACL overrides for connector-created docs (no impact on pipeline_hash).
                doc.access_mode = None if access_mode == "inherit" else access_mode
                if not (getattr(doc, "owner_id", None) or "").strip():
                    doc.owner_id = requested_by

                if access_mode == "partial_members":
                    DocumentPermissionService.update_partial_member_list(
                        db,
                        tenant_id,
                        doc.id,
                        list(access_members),
                    )
                else:
                    DocumentPermissionService.clear_partial_member_list(db, tenant_id, doc.id)

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
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
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

        stats = dict(run.stats or {})
        stats.update(
            {
                "visited": int(crawl.visited),
                "queued": int(crawl.queued),
                "discovered": int(len(crawl.urls)),
                "total_urls": int(len(crawl.urls)),
                "processed_urls": 0,
                "cursor": 0,
                "created": 0,
                "failed": 0,
                "failed_urls": [],
                "errors": [],
                "error_groups": [],
            }
        )
        if crawl.errors:
            stats["crawl_errors"] = list(crawl.errors)[:20]
        run.stats = _finalize_connector_stats(stats)
        db.commit()

        for idx, url in enumerate(crawl.urls):
            # Observe cancellation from another DB session (best-effort).
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

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

                # Apply document-level ACL overrides for connector-created docs (no impact on pipeline_hash).
                doc.access_mode = None if access_mode == "inherit" else access_mode
                if not (getattr(doc, "owner_id", None) or "").strip():
                    doc.owner_id = requested_by

                if access_mode == "partial_members":
                    DocumentPermissionService.update_partial_member_list(
                        db,
                        tenant_id,
                        document_id=doc.id,
                        owner_id=requested_by,
                        member_ids=access_members,
                    )
                else:
                    DocumentPermissionService.clear_partial_member_list(db, tenant_id, doc.id)

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
                        "total_urls": int(len(crawl.urls)),
                        "processed_urls": int(processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
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

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
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

    doc.access_mode = None if access_mode == "inherit" else access_mode
    if not (getattr(doc, "owner_id", None) or "").strip():
        doc.owner_id = requested_by

    if access_mode == "partial_members":
        DocumentPermissionService.update_partial_member_list(
            db,
            tenant_id,
            document_id=doc.id,
            owner_id=requested_by,
            member_ids=access_members,
        )
    else:
        DocumentPermissionService.clear_partial_member_list(db, tenant_id, doc.id)


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

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"github api failed (status={resp.status_code})")
            data = resp.json()

        tree = data.get("tree")
        items = tree if isinstance(tree, list) else []
        paths: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if str(it.get("type") or "") != "blob":
                continue
            p = str(it.get("path") or "").strip()
            if not p:
                continue
            ext = Path(p).suffix.lower()
            if ext and ext not in include_set:
                continue
            if ext and ext in include_set:
                paths.append(p)
            elif not ext and "" in include_set:
                paths.append(p)
            if len(paths) >= max(1, min(max_files, 200)):
                break

        stats0 = dict(run.stats or {})
        stats0.update({"total_files": int(len(paths)), "processed_files": 0, "cursor": 0, "created": 0, "failed": 0, "failed_paths": []})
        run.stats = stats0
        db.commit()

        for idx, path in enumerate(paths):
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            try:
                raw_url = _github_raw_url(owner=owner, repo=repo_name, branch=branch, path=path)
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

                _apply_document_access_from_config(db, tenant_id=tenant_id, requested_by=requested_by, doc=doc, access=access)

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
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=path, exc=exc)
                run.stats = stats
            finally:
                processed = idx + 1
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "total_files": int(len(paths)),
                        "processed_files": int(processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
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

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
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

        auth_headers = _build_auth_headers(cfg)

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []

        stats0 = dict(run.stats or {})
        stats0.update({"total_urls": int(len(urls)), "processed_urls": 0, "cursor": 0, "created": 0, "failed": 0, "failed_urls": []})
        run.stats = stats0
        db.commit()

        for idx, url in enumerate(urls):
            try:
                db.refresh(run)
            except Exception:
                pass
            if str(run.status or "").lower() == "cancelled":
                break

            try:
                file_id = _extract_drive_file_id(url)
                if not file_id:
                    raise ValueError("unsupported_drive_url")
                dl_url = _drive_direct_download_url(file_id)
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
                _apply_document_access_from_config(db, tenant_id=tenant_id, requested_by=requested_by, doc=doc, access=access)
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

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
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

        object_names: list[str] = []
        for obj in client.list_objects(bucket_name=bucket_name, prefix=(prefix or None), recursive=True):
            name = str(getattr(obj, "object_name", "") or "").strip()
            if not name:
                continue
            ext = Path(name).suffix.lower()
            if ext and ext not in include_set:
                continue
            object_names.append(name)
            if len(object_names) >= max(1, min(max_objects, 200)):
                break

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []

        stats0 = dict(run.stats or {})
        stats0.update({"total_objects": int(len(object_names)), "processed_objects": 0, "cursor": 0, "created": 0, "failed": 0})
        run.stats = stats0
        db.commit()

        for idx, object_name in enumerate(object_names):
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
                _apply_document_access_from_config(db, tenant_id=tenant_id, requested_by=requested_by, doc=doc, access=access)
                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        document_id=doc.id,
                        source_ref=object_name,
                        status="created",
                    )
                )
                created += 1
                created_doc_ids.append(doc.id)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=object_name, exc=exc)
                run.stats = stats
            finally:
                processed = idx + 1
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "total_objects": int(len(object_names)),
                        "processed_objects": int(processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
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

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
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
    if w.startswith(("http://", "https://")):
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


def _confluence_ingest_method(cfg: dict) -> str:
    """
    Normalize Confluence page ingestion method.

    Backward compatibility:
    - If ingest_method is missing (older saved configs), default to api_view.
    """
    raw = cfg.get("ingest_method") if isinstance(cfg, dict) else None
    m = str(raw or "api_view").strip().lower()
    return m if m in {"api_view", "webui"} else "api_view"


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

        ingest_method = _confluence_ingest_method(cfg)

        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None

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
            cql += f' and lastmodified > "{cursor_last_modified}"'
        cql += " ORDER BY lastmodified ASC"

        created = 0
        failed = 0
        processed = 0
        created_doc_ids: list[UUID] = []
        observed_page_ids: set[str] = set()
        last_modified_seen: str | None = None

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
            resp = await pool.request_with_retry("GET", search_url, params=params, headers=headers)
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
                if lm:
                    # Results are ordered by lastmodified ASC; the latest processed timestamp is the cursor.
                    last_modified_seen = lm

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
                        content_resp = await pool.request_with_retry("GET", content_url, params=content_params, headers=headers)
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

                    _apply_document_access_from_config(db, tenant_id=tenant_id, requested_by=requested_by, doc=doc, access=access)

                    # Attach connector metadata (must not affect pipeline_hash).
                    try:
                        meta0 = dict(getattr(doc, "doc_metadata", None) or {})
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
                            "document_ids": [str(d) for d in created_doc_ids],
                        }
                    )
                    if last_modified_seen:
                        stats["last_modified"] = last_modified_seen
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
                probe = await pool.request_with_retry("GET", search_url, params=probe_params, headers=headers)
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
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
        run.finished_at = _now()
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
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


@router.post("/runs", response_model=ConnectorRunOut, status_code=201)
async def create_connector_run(
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Create a connector run (currently supports url_batch).

    Requires dataset write permission.
    """
    connector_id = str(payload.connector_id or "").strip()
    url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space"}
    db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}

    if connector_id in url_connectors and not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")
    if connector_id in db_catalog_connectors and not bool(getattr(settings, "DB_CATALOG_ENABLED", False)):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, payload.dataset_id)

    if connector_id == "url_batch":
        cfg = UrlBatchConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "web_crawl":
        cfg = WebCrawlConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "github_repo":
        cfg = GitHubRepoConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "drive_files":
        cfg = DriveFilesConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "minio_bucket":
        cfg = MinioBucketConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "confluence_space":
        cfg = ConfluenceSpaceConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "mysql_catalog":
        cfg = MySQLCatalogConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    elif connector_id == "sqlserver_catalog":
        cfg = SQLServerCatalogConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

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
    elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
        background_tasks.add_task(_execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

    return _run_out(run)


@router.get("/runs", response_model=ConnectorRunListResponse)
def list_connector_runs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    dataset_id: UUID | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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

    return {"total": total, "items": [_run_out(r) for r in runs]}


@router.get("/runs/{run_id}", response_model=ConnectorRunOut)
def get_connector_run(
    run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        raise HTTPException(status_code=404, detail="Connector run not found")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    return _run_out(run)


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


@router.post("/runs/{run_id}/retry-failed", response_model=ConnectorRunOut, status_code=201)
async def retry_failed_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a new connector run that retries only the failed URLs (best-effort)."""
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

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
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

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


@router.post("/runs/{run_id}/resume", response_model=ConnectorRunOut, status_code=201)
async def resume_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a new connector run that resumes from where the previous run stopped (best-effort)."""
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

    status = str(run.status or "").lower()
    if status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=400, detail="Connector run is not resumable")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    connector_id = str(run.connector_id or "").strip()
    if connector_id != "url_batch":
        raise HTTPException(status_code=400, detail="Resume is only supported for url_batch")

    stats = dict(run.stats or {})
    cursor_raw = stats.get("cursor", stats.get("processed_urls", 0))
    try:
        cursor = max(0, int(cursor_raw or 0))
    except Exception:
        cursor = 0

    base_cfg = dict(run.config or {})
    urls = base_cfg.get("urls") if isinstance(base_cfg.get("urls"), list) else []
    urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
    remaining = urls[cursor:] if cursor < len(urls) else []
    if not remaining:
        raise HTTPException(status_code=400, detail="No remaining URLs to resume")

    new_cfg = dict(base_cfg)
    new_cfg["urls"] = remaining
    new_run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=run.dataset_id,
        connector_id="url_batch",
        requested_by=account_id,
        status="pending",
        config=new_cfg,
        stats={"resume_of": str(run.id), "resume_cursor": int(cursor)},
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


@router.post("/runs/{run_id}/cancel", response_model=ConnectorRunOut)
async def cancel_connector_run(
    run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Cancel a running connector run (best-effort)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

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


@router.get("/configs", response_model=ConnectorConfigListResponse)
def list_connector_configs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    dataset_id: UUID | None = None,
    connector_id: str | None = None,
    enabled: bool | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.post("/configs", response_model=ConnectorConfigOut, status_code=201)
def create_connector_config(
    payload: ConnectorConfigCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.put("/configs/{config_id}", response_model=ConnectorConfigOut)
def update_connector_config(
    config_id: UUID,
    payload: ConnectorConfigUpdateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Update a saved connector configuration (best-effort)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Connector config not found")

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


@router.delete("/configs/{config_id}", status_code=204)
def delete_connector_config(
    config_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Delete a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Connector config not found")

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    db.delete(cfg)
    db.commit()
    return Response(status_code=204)


@router.post("/configs/{config_id}/run", response_model=ConnectorRunOut, status_code=201)
async def run_connector_config(
    config_id: UUID,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a connector run from a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Connector config not found")

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    connector_id = str(cfg.connector_id or "").strip()
    url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space"}
    db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}
    if connector_id in url_connectors and not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")
    if connector_id in db_catalog_connectors and not bool(getattr(settings, "DB_CATALOG_ENABLED", False)):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")

    run_cfg = dict(cfg.config or {})
    # Attach connector config state for incremental connectors (best-effort; executor may ignore).
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
    elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
        background_tasks.add_task(_execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

    return _run_out(run)


@router.post("/scheduled/tick")
async def scheduled_tick(
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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

        url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space"}
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
