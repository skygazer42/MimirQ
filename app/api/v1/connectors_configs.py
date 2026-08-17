from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    ConnectorConfigCreateRequest,
    ConnectorConfigListResponse,
    ConnectorConfigOut,
    ConnectorConfigUpdateRequest,
    ConnectorRunOut,
)
from app.api.v1 import connectors as connectors_module
from app.api.v1.connectors_runs import (
    CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR,
    _create_pending_connector_run,
    _enqueue_or_schedule_connector_run,
    _writable_dataset_ids_subquery,
)
from app.core.database import get_db
from app.models.connector_config import ConnectorConfig
from app.models.document import Document as DBDocument
from app.services.connector_egress_policy import validate_db_connector_config
from app.services.dataset_service import EDIT_ROLES
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter(responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
_DB_CONNECTOR_PERMISSION_DETAIL = "No permission to run DB connectors"


@router.get(
    "/configs",
    response_model=ConnectorConfigListResponse,
    responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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
    member = connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorConfig).filter(ConnectorConfig.tenant_id == tenant_id)
    if dataset_id is not None:
        dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, dataset_id)
        connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorConfig.dataset_id == dataset_id)
    if connector_id:
        query = query.filter(ConnectorConfig.connector_id == str(connector_id))
    if enabled is not None:
        query = query.filter(ConnectorConfig.enabled.is_(bool(enabled)))

    if dataset_id is None:
        if str(getattr(member, "role", "") or "").lower() not in EDIT_ROLES:
            return {"total": 0, "items": []}
        query = query.filter(
            ConnectorConfig.dataset_id.in_(_writable_dataset_ids_subquery(tenant_id=tenant_id, account_id=account_id))
        )

    total = int(query.count())
    items = query.order_by(ConnectorConfig.created_at.desc()).offset(skip).limit(limit).all()

    return {"total": total, "items": [connectors_module._config_out(cfg) for cfg in items]}


@router.post(
    "/configs",
    response_model=ConnectorConfigOut,
    status_code=201,
    responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_connector_config(
    payload: ConnectorConfigCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a saved connector configuration."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    cfg_dict = connectors_module.encrypt_connector_config_secrets(dict(payload.config or {}))

    cfg = ConnectorConfig(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        connector_id=str(payload.connector_id or "").strip(),
        name=str(payload.name or "").strip(),
        enabled=bool(payload.enabled),
        schedule_cron=(
            str(payload.schedule_cron).strip()
            if isinstance(payload.schedule_cron, str) and payload.schedule_cron.strip()
            else None
        ),
        config=cfg_dict,
        state={},
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return connectors_module._config_out(cfg)


@router.put(
    "/configs/{config_id}",
    response_model=ConnectorConfigOut,
    responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def update_connector_config(
    config_id: UUID,
    payload: ConnectorConfigUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update a saved connector configuration (best-effort)."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    if payload.name is not None:
        cfg.name = str(payload.name or "").strip()  # type: ignore[assignment]
    if payload.enabled is not None:
        cfg.enabled = bool(payload.enabled)  # type: ignore[assignment]
    if payload.schedule_cron is not None:
        cfg.schedule_cron = str(payload.schedule_cron).strip() if str(payload.schedule_cron or "").strip() else None  # type: ignore[assignment]
    if payload.config is not None:
        cfg.config = connectors_module.encrypt_connector_config_secrets(dict(payload.config or {}))  # type: ignore[assignment]
    if payload.state is not None:
        cfg.state = dict(payload.state or {})  # type: ignore[assignment]

    db.commit()
    db.refresh(cfg)
    return connectors_module._config_out(cfg)


@router.delete("/configs/{config_id}", status_code=204, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_connector_config(
    config_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a saved connector configuration."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    db.delete(cfg)
    db.commit()
    return Response(status_code=204)


@router.post(
    "/configs/{config_id}/run",
    response_model=ConnectorRunOut,
    status_code=201,
    responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def run_connector_config(
    config_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a connector run from a saved connector configuration."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    connector_id = str(cfg.connector_id or "").strip()
    if connector_id in {"mysql_catalog", "sqlserver_catalog"}:
        ensure_tenant_permission(
            db,
            tenant_id,
            account_id,
            TenantPermissions.SETTINGS_WRITE,
            detail=_DB_CONNECTOR_PERMISSION_DETAIL,
        )

    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    url_connectors = {
        "url_batch",
        "web_crawl",
        "github_repo",
        "drive_files",
        "minio_bucket",
        "confluence_space",
        "jira_project",
    }
    db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}
    if connector_id in url_connectors and not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)
    if connector_id in db_catalog_connectors and not bool(
        getattr(connectors_module.settings, "DB_CATALOG_ENABLED", False)
    ):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")
    if connector_id in db_catalog_connectors:
        try:
            validate_db_connector_config(dict(cfg.config or {}))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_cfg = dict(cfg.config or {})
    connector_definition = connectors_module.get_connector_definition(connector_id)
    if connector_definition is not None and connector_definition.supports_incremental:
        run_cfg["_state"] = dict(cfg.state or {})

    run = _create_pending_connector_run(
        db,
        values={
            "tenant_id": tenant_id,
            "dataset_id": cfg.dataset_id,
            "connector_id": connector_id,
            "requested_by": account_id,
            "config": run_cfg,
            "stats": {"config_id": str(cfg.id)},
        },
    )
    try:
        result = await _enqueue_or_schedule_connector_run(
            db,
            background_tasks=background_tasks,
            run=run,
            tenant_id=tenant_id,
            requested_by=account_id,
        )
    except HTTPException as exc:
        if exc.status_code == 503:
            cfg.last_error = CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR  # type: ignore[assignment]
            db.commit()
        raise

    cfg.last_run_at = connectors_module._now()  # type: ignore[assignment]
    cfg.last_error = None  # type: ignore[assignment]
    db.commit()
    return result


@router.post("/configs/{config_id}/reconcile", responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
def reconcile_connector_config(
    config_id: UUID,
    apply: Annotated[bool, Query(description="Apply the reconcile plan; default is dry-run")] = False,
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
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    desired_refs = connectors_module.resolve_connector_reconcile_source_refs(
        connector_id=str(cfg.connector_id or "").strip(),
        config=dict(cfg.config or {}),
        state=dict(cfg.state or {}),
    )
    if not desired_refs:
        raise HTTPException(
            status_code=400,
            detail="No reconcile source manifest available for this connector config",
        )

    documents = (
        db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == cfg.dataset_id).all()
    )
    report = connectors_module.plan_connector_reconcile(
        connector_id=str(cfg.connector_id or "").strip(),
        config_id=str(cfg.id),
        dataset_id=str(cfg.dataset_id),
        documents=documents,
        desired_source_refs=desired_refs,
        apply=bool(apply),
        now=connectors_module._now(),
        sample_limit=int(sample_limit),
    )

    if apply:
        db.commit()

    connectors_module.audit_log_event(
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
