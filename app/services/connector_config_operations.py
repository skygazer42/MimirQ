from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.connector import (
    ConnectorConfigCreateRequest,
    ConnectorConfigOut,
    ConnectorConfigUpdateRequest,
    ConnectorRunOut,
)
from app.core.config import settings
from app.core.secrets import encrypt_connector_config_secrets, redact_secrets
from app.models.connector_config import ConnectorConfig
from app.models.document import Document as DBDocument
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.connector_egress_policy import validate_db_connector_config
from app.services.connector_execution.shared.runtime import _now
from app.services.connector_reconcile_service import plan_connector_reconcile, resolve_connector_reconcile_source_refs
from app.services.connector_registry import get_connector_definition
from app.services.connector_run_operations import (
    _DB_CATALOG_CONNECTOR_IDS,
    _URL_INGEST_CONNECTOR_IDS,
    CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR,
    _create_pending_connector_run,
    _writable_dataset_ids_subquery,
    enqueue_or_schedule_run,
)
from app.services.dataset_service import EDIT_ROLES
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.security_redaction import redact_connection_info

CONNECTOR_CONFIG_NOT_FOUND_DETAIL = "Connector config not found"
_DB_CONNECTOR_IDS = _DB_CATALOG_CONNECTOR_IDS
_DB_CONNECTOR_PERMISSION_DETAIL = "No permission to run DB connectors"


def build_saved_connector_run_config(config: ConnectorConfig) -> dict[str, Any]:
    run_config = dict(config.config or {})
    definition = get_connector_definition(config.connector_id.strip())
    if definition is not None and definition.supports_incremental:
        run_config["_state"] = dict(config.state or {})
    return run_config


def _config_out(cfg: ConnectorConfig) -> ConnectorConfigOut:
    connector_id = cfg.connector_id
    config = redact_connection_info(
        redact_secrets(dict(cfg.config)),
        enabled=connector_id.strip() in _DB_CONNECTOR_IDS,
    )
    return ConnectorConfigOut(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=connector_id,
        name=cfg.name,
        enabled=cfg.enabled,
        schedule_cron=cfg.schedule_cron,
        config=config,
        state=dict(cfg.state),
        last_run_at=cfg.last_run_at,
        last_error=cfg.last_error,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


def list_configs(
    *,
    skip: int,
    limit: int,
    dataset_id: UUID | None,
    connector_id: str | None,
    enabled: bool | None,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> dict[str, Any]:
    """
    List saved connector configurations.

    Note: configs may contain secrets (even if encrypted); we enforce dataset write permission
    semantics similar to connector runs to avoid leaking URLs/auth details to readers.
    """
    member = dataset_service.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorConfig).filter(ConnectorConfig.tenant_id == tenant_id)
    if dataset_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorConfig.dataset_id == dataset_id)
    if connector_id:
        query = query.filter(ConnectorConfig.connector_id == connector_id)
    if enabled is not None:
        query = query.filter(ConnectorConfig.enabled.is_(enabled))

    if dataset_id is None:
        if member.role.lower() not in EDIT_ROLES:
            return {"total": 0, "items": []}
        query = query.filter(
            ConnectorConfig.dataset_id.in_(_writable_dataset_ids_subquery(tenant_id=tenant_id, account_id=account_id))
        )

    total = query.count()
    items = query.order_by(ConnectorConfig.created_at.desc()).offset(skip).limit(limit).all()

    return {"total": total, "items": [_config_out(cfg) for cfg in items]}


def create_config(
    payload: ConnectorConfigCreateRequest,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorConfigOut:
    """Create a saved connector configuration."""
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, payload.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)

    cfg_dict = encrypt_connector_config_secrets(dict(payload.config))

    cfg = ConnectorConfig(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        connector_id=payload.connector_id.strip(),
        name=payload.name.strip(),
        enabled=payload.enabled,
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
    return _config_out(cfg)


def update_config(
    config_id: UUID,
    payload: ConnectorConfigUpdateRequest,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorConfigOut:
    """Update a saved connector configuration (best-effort)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    dataset = dataset_service.get_dataset(db, tenant_id, cfg.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)

    if payload.name is not None:
        cfg.name = payload.name.strip()  # type: ignore[assignment]
    if payload.enabled is not None:
        cfg.enabled = payload.enabled  # type: ignore[assignment]
    if payload.schedule_cron is not None:
        schedule = payload.schedule_cron.strip()
        cfg.schedule_cron = schedule or None  # type: ignore[assignment]
    if payload.config is not None:
        cfg.config = encrypt_connector_config_secrets(dict(payload.config))  # type: ignore[assignment]
    if payload.state is not None:
        cfg.state = dict(payload.state)  # type: ignore[assignment]

    db.commit()
    db.refresh(cfg)
    return _config_out(cfg)


def delete_config(
    config_id: UUID,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> None:
    """Delete a saved connector configuration."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    dataset = dataset_service.get_dataset(db, tenant_id, cfg.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)

    db.delete(cfg)
    db.commit()


async def run_saved_config(
    config_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> ConnectorRunOut:
    """Create a connector run from a saved connector configuration."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    connector_id = cfg.connector_id.strip()
    if connector_id in _DB_CONNECTOR_IDS:
        ensure_tenant_permission(
            db,
            tenant_id,
            account_id,
            TenantPermissions.SETTINGS_WRITE,
            detail=_DB_CONNECTOR_PERMISSION_DETAIL,
        )

    dataset = dataset_service.get_dataset(db, tenant_id, cfg.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)

    if connector_id in _URL_INGEST_CONNECTOR_IDS and not settings.URL_INGEST_ENABLED:
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")
    if connector_id in _DB_CONNECTOR_IDS and not settings.DB_CATALOG_ENABLED:
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")
    if connector_id in _DB_CONNECTOR_IDS:
        try:
            validate_db_connector_config(dict(cfg.config or {}))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_cfg = build_saved_connector_run_config(cfg)

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
        result = await enqueue_or_schedule_run(
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

    cfg.last_run_at = _now()
    cfg.last_error = None  # type: ignore[assignment]
    db.commit()
    return result


def reconcile_config(
    config_id: UUID,
    *,
    apply: bool = False,
    sample_limit: int = 20,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> dict[str, object]:
    """
    Reconcile connector-managed documents for a saved config using the last known local source set.

    Single-node scope:
    - dry-run: show stale / disabled / missing refs
    - apply: disable stale docs and re-enable matching disabled docs
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=CONNECTOR_CONFIG_NOT_FOUND_DETAIL)

    dataset = dataset_service.get_dataset(db, tenant_id, cfg.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)

    desired_refs = resolve_connector_reconcile_source_refs(
        connector_id=cfg.connector_id.strip(),
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
    report = plan_connector_reconcile(
        connector_id=cfg.connector_id.strip(),
        config_id=str(cfg.id),
        dataset_id=str(cfg.dataset_id),
        documents=documents,
        desired_source_refs=desired_refs,
        apply=apply,
        now=_now(),
        sample_limit=sample_limit,
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
            "connector_id": cfg.connector_id,
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
