from __future__ import annotations

import contextlib
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun


def _get_db_catalog_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        return None
    if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
        return None
    return run


def _mark_db_catalog_run_running(db: Session, *, run: ConnectorRun) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.

    run.status = "running"
    run.started_at = connectors_module._now()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    with contextlib.suppress(Exception):
        db.refresh(run)


def _db_catalog_connector_config_id(stats: dict[str, Any]) -> UUID | None:
    cfg_id = stats.get("config_id")
    try:
        return UUID(str(cfg_id)) if cfg_id else None
    except Exception:
        return None


def _build_db_catalog_run_context(db: Session, *, run: ConnectorRun) -> tuple[str, dict[str, Any], dict[str, Any], UUID | None, Any]:
    from app.connectors.db.catalog_store_sqlalchemy import SqlAlchemyCatalogStore
    from app.core.secrets import decrypt_connector_config_secrets

    connector_id = str(run.connector_id or "").strip()
    cfg = decrypt_connector_config_secrets(dict(run.config or {}))
    stats = dict(run.stats or {})
    connector_config_id = _db_catalog_connector_config_id(stats)
    store = SqlAlchemyCatalogStore(db=db)
    return connector_id, cfg, stats, connector_config_id, store


def _run_db_catalog_sync(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    connector_id: str,
    cfg: dict[str, Any],
    store: Any,
    connector_config_id: UUID | None,
) -> tuple[dict[str, Any], float]:
    import time

    from app.connectors.db.catalog_runner import run_catalog_sync

    t0_sync = time.time()
    result = run_catalog_sync(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id=connector_id,
        config=dict(cfg or {}),
        store=store,
        connector_config_id=connector_config_id,
    )
    return dict(result or {}), time.time() - t0_sync


def _emit_db_catalog_sync_completed(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    run_id: UUID,
    connector_id: str,
    sync_elapsed: float,
    result: dict[str, Any],
) -> None:
    with contextlib.suppress(Exception):
        import app.services.db_catalog_observability as obs

        obs.emit_db_catalog_sync_completed(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            run_id=str(run_id),
            connector_id=connector_id,
            elapsed_sec=float(sync_elapsed),
            result=dict(result or {}),
        )


def _emit_db_catalog_schema_doc_completed(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    run_id: UUID,
    connector_id: str,
    doc_elapsed: float,
    schema_doc: dict[str, Any],
) -> None:
    with contextlib.suppress(Exception):
        import app.services.db_catalog_observability as obs

        obs.emit_db_catalog_schema_doc_completed(
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            run_id=str(run_id),
            connector_id=connector_id,
            elapsed_sec=float(doc_elapsed),
            document_id=str(schema_doc.get("document_id") or ""),
            chunks=int(schema_doc.get("chunks") or 0),
            tables=int(schema_doc.get("tables") or 0),
            catalog_last_seen_at=schema_doc.get("catalog_last_seen_at"),
            catalog_age_sec=schema_doc.get("catalog_age_sec"),
        )


def _attach_db_catalog_schema_doc(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    connector_id: str,
    stats: dict[str, Any],
) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.

    try:
        import time

        from app.services.db_catalog_schema_doc_service import upsert_and_index_virtual_schema_doc

        t0_doc = time.time()
        schema_doc = upsert_and_index_virtual_schema_doc(
            db=db,
            tenant_id=tenant_id,
            dataset_id=run.dataset_id,
            requested_by=requested_by,
            connector_run_id=run.id,
        )
        doc_elapsed = time.time() - t0_doc
        if not isinstance(schema_doc, dict):
            return
        schema_doc.setdefault("elapsed_sec", float(doc_elapsed))
        stats["schema_doc"] = schema_doc
        _emit_db_catalog_schema_doc_completed(
            tenant_id=tenant_id,
            dataset_id=run.dataset_id,
            run_id=run.id,
            connector_id=connector_id,
            doc_elapsed=doc_elapsed,
            schema_doc=schema_doc,
        )
    except Exception as exc:  # noqa: BLE001
        stats["schema_doc_error"] = connectors_module._safe_error_str(exc)


def _db_catalog_row_sync_settings(cfg: dict[str, Any]) -> tuple[bool, int, int, int]:
    from app.core.config import settings

    enabled = bool(getattr(settings, "DB_CATALOG_ROW_SYNC_ENABLED", False) and cfg.get("row_sync_enabled"))
    max_tables = int(cfg.get("row_sync_max_tables") or getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_TABLES", 20) or 20)
    max_rows = int(
        cfg.get("row_sync_max_rows_per_table")
        or getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE", 50)
        or 50
    )
    max_cols = int(cfg.get("row_sync_max_cols") or getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_COLS", 50) or 50)
    return enabled, max_tables, max_rows, max_cols


def _attach_db_catalog_row_sync(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    connector_id: str,
    cfg: dict[str, Any],
    stats: dict[str, Any],
) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.
    from app.connectors.db.catalog_runner import extract_row_snapshots

    enabled, max_tables, max_rows, max_cols = _db_catalog_row_sync_settings(cfg)
    stats["row_sync_enabled"] = bool(enabled)
    if not enabled:
        return

    try:
        snapshots = extract_row_snapshots(
            tenant_id=tenant_id,
            dataset_id=run.dataset_id,
            connector_id=connector_id,
            config=dict(cfg or {}),
            max_tables=max_tables,
            max_rows_per_table=max_rows,
            max_cols=max_cols,
        )
        stats["total_tables"] = int(len(snapshots))
        stats["source_manifest"] = connectors_module._build_db_row_source_manifest(snapshots)

        sidecar = connectors_module._upsert_db_row_sidecar_document(
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
        stats["row_sync_error"] = connectors_module._safe_error_str(exc)


def _nested_diff_count(diff: dict[str, Any], key: str) -> int:
    value = diff.get(key)
    bucket = value if isinstance(value, dict) else {}
    return int(bucket.get("count") or 0)


def _db_catalog_schema_diff_counts(diff: object) -> dict[str, int] | None:
    if not isinstance(diff, dict):
        return None
    return {
        "tables_added": _nested_diff_count(diff, "tables_added"),
        "tables_removed": _nested_diff_count(diff, "tables_removed"),
        "columns_added": _nested_diff_count(diff, "columns_added"),
        "columns_removed": _nested_diff_count(diff, "columns_removed"),
        "columns_changed": _nested_diff_count(diff, "columns_changed"),
    }


def _emit_db_catalog_completion_audit(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    run: ConnectorRun,
    connector_id: str,
    stats: dict[str, Any],
    result: dict[str, Any],
) -> None:
    from app.services.audit_log_service import audit_log_event

    with contextlib.suppress(Exception):
        schema_doc = stats.get("schema_doc") if isinstance(stats, dict) else None
        diff = schema_doc.get("schema_diff") if isinstance(schema_doc, dict) else None
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=requested_by,
            action="db_catalog.sync.completed",
            resource_type="connector_run",
            resource_id=str(run.id),
            details={
                "dataset_id": str(run.dataset_id),
                "connector_id": connector_id,
                "config_id": (str(stats.get("config_id")) if stats.get("config_id") is not None else None),
                "result": dict(result or {}),
                "schema_doc_id": (
                    str(schema_doc.get("document_id"))
                    if isinstance(schema_doc, dict) and schema_doc.get("document_id")
                    else None
                ),
                "schema_diff_counts": _db_catalog_schema_diff_counts(diff),
            },
        )


def _finalize_db_catalog_run_success(db: Session, *, run: ConnectorRun, stats: dict[str, Any]) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.

    run.stats = connectors_module._finalize_connector_stats(stats)
    run.status = "completed"
    run.finished_at = connectors_module._now()
    db.commit()
    with contextlib.suppress(Exception):
        connectors_module._sync_connector_config_from_run(db, run=run)


def _emit_db_catalog_sync_failed(
    *,
    tenant_id: UUID,
    run_id: UUID,
    run: ConnectorRun | None,
    exc: Exception,
) -> None:
    with contextlib.suppress(Exception):
        import app.services.db_catalog_observability as obs

        obs.emit_db_catalog_sync_failed(
            tenant_id=str(tenant_id),
            dataset_id=str(getattr(run, "dataset_id", "") or ""),
            run_id=str(run_id),
            connector_id=str(getattr(run, "connector_id", "") or ""),
            elapsed_sec=0.0,
            error=str(exc)[:200],
        )


def _emit_db_catalog_failure_audit(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    run_id: UUID,
    run: ConnectorRun | None,
    exc: Exception,
) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.
    from app.services.audit_log_service import audit_log_event

    with contextlib.suppress(Exception):
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
                "error": connectors_module._safe_error_str(exc),
            },
        )


def _mark_db_catalog_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.

    with contextlib.suppress(Exception):
        run = (
            db.query(ConnectorRun)
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if run is not None:
            run.status = "failed"
            run.finished_at = connectors_module._now()
            run.error_message = connectors_module._safe_error_str(exc)
            db.commit()
            with contextlib.suppress(Exception):
                connectors_module._sync_connector_config_from_run(db, run=run)
        db.rollback()


def _execute_db_catalog_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to avoid circular import.
    from app.services.metrics_logger import metrics_context

    db = connectors_module.SessionLocal()
    run: ConnectorRun | None = None
    try:
        run = _get_db_catalog_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_db_catalog_run_running(db, run=run)
        connector_id, cfg, stats, connector_config_id, store = _build_db_catalog_run_context(db, run=run)

        with metrics_context(
            tenant_id=tenant_id,
            account_id=requested_by,
            dataset_id=str(run.dataset_id),
            connector_id=connector_id,
            connector_run_id=str(run_id),
        ):
            result, sync_elapsed = _run_db_catalog_sync(
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id=connector_id,
                cfg=cfg,
                store=store,
                connector_config_id=connector_config_id,
            )
            _emit_db_catalog_sync_completed(
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                run_id=run_id,
                connector_id=connector_id,
                sync_elapsed=sync_elapsed,
                result=result,
            )
            _attach_db_catalog_schema_doc(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                connector_id=connector_id,
                stats=stats,
            )
            _attach_db_catalog_row_sync(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                connector_id=connector_id,
                cfg=cfg,
                stats=stats,
            )

        stats["result"] = dict(result or {})
        _emit_db_catalog_completion_audit(
            db,
            tenant_id=tenant_id,
            requested_by=requested_by,
            run=run,
            connector_id=connector_id,
            stats=stats,
            result=result,
        )
        _finalize_db_catalog_run_success(db, run=run, stats=stats)
    except Exception as exc:  # noqa: BLE001
        _emit_db_catalog_sync_failed(tenant_id=tenant_id, run_id=run_id, run=run, exc=exc)
        _emit_db_catalog_failure_audit(
            db,
            tenant_id=tenant_id,
            requested_by=requested_by,
            run_id=run_id,
            run=run,
            exc=exc,
        )
        _mark_db_catalog_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        db.close()
