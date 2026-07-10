"""
DB catalog observability helpers.

We keep these as small pure-ish wrappers so unit tests can validate event shape
without needing to run connector background tasks.
"""


from collections.abc import Mapping
from typing import Any

from app.services.metrics_logger import log_metrics


def emit_db_catalog_sync_completed(
    *,
    tenant_id: str,
    dataset_id: str,
    run_id: str,
    connector_id: str,
    elapsed_sec: float,
    result: Mapping[str, Any] | None,
) -> None:
    log_metrics(
        {
            "event": "db_catalog.sync.completed",
            "success": True,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "run_id": str(run_id),
            "connector_id": str(connector_id),
            "elapsed_sec": float(elapsed_sec or 0.0),
            "result": dict(result or {}),
        }
    )


def emit_db_catalog_sync_failed(
    *,
    tenant_id: str,
    dataset_id: str,
    run_id: str,
    connector_id: str,
    elapsed_sec: float,
    error: str,
) -> None:
    log_metrics(
        {
            "event": "db_catalog.sync.failed",
            "success": False,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "run_id": str(run_id),
            "connector_id": str(connector_id),
            "elapsed_sec": float(elapsed_sec or 0.0),
            "error": str(error or "")[:500],
        }
    )


def emit_db_catalog_schema_doc_completed(
    *,
    tenant_id: str,
    dataset_id: str,
    run_id: str,
    connector_id: str,
    elapsed_sec: float,
    document_id: str,
    chunks: int,
    tables: int,
    catalog_last_seen_at: str | None = None,
    catalog_age_sec: float | None = None,
) -> None:
    log_metrics(
        {
            "event": "db_catalog.schema_doc.completed",
            "success": True,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "run_id": str(run_id),
            "connector_id": str(connector_id),
            "elapsed_sec": float(elapsed_sec or 0.0),
            "document_id": str(document_id),
            "chunks": int(chunks or 0),
            "tables": int(tables or 0),
            "catalog_last_seen_at": (str(catalog_last_seen_at) if catalog_last_seen_at else None),
            "catalog_age_sec": (float(catalog_age_sec) if catalog_age_sec is not None else None),
        }
    )
