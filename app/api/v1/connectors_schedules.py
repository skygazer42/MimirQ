from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import connectors as connectors_module
from app.core.database import get_db
from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig

router = APIRouter(responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/scheduled/tick", responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    now = connectors_module._now()
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
        if not connectors_module._schedule_due(schedule=schedule, now=now, last_run_at=(cfg.last_run_at or None)):
            skipped += 1
            continue
        try:
            dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
            connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
        except HTTPException:
            skipped += 1
            continue

        connector_id = str(cfg.connector_id or "").strip()
        run_cfg = dict(cfg.config or {})
        connector_definition = connectors_module.get_connector_definition(connector_id)
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

        if connector_id in url_connectors and not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
            run.status = "failed"
            run.error_message = "url_ingest_disabled"
            run.finished_at = now
            cfg.last_error = "url_ingest_disabled"  # type: ignore[assignment]
            db.commit()
            enqueued += 1
            continue
        if connector_id in db_catalog_connectors and not bool(getattr(connectors_module.settings, "DB_CATALOG_ENABLED", False)):
            run.status = "failed"
            run.error_message = "db_catalog_disabled"
            run.finished_at = now
            cfg.last_error = "db_catalog_disabled"  # type: ignore[assignment]
            db.commit()
            enqueued += 1
            continue

        if connector_id == "url_batch":
            background_tasks.add_task(connectors_module._execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "web_crawl":
            background_tasks.add_task(connectors_module._execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "github_repo":
            background_tasks.add_task(connectors_module._execute_github_repo_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "drive_files":
            background_tasks.add_task(connectors_module._execute_drive_files_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "minio_bucket":
            background_tasks.add_task(connectors_module._execute_minio_bucket_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "confluence_space":
            background_tasks.add_task(connectors_module._execute_confluence_space_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "jira_project":
            background_tasks.add_task(connectors_module._execute_jira_project_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
            background_tasks.add_task(connectors_module._execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        else:
            run.status = "failed"
            run.error_message = "unsupported_connector_id"
            run.finished_at = now
            cfg.last_error = "unsupported_connector_id"  # type: ignore[assignment]
            db.commit()
        enqueued += 1

    return {"enqueued": int(enqueued), "skipped": int(skipped)}
