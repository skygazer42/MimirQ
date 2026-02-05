"""
DB catalog sync runner (stub).

This module wires connector runs to catalog ingestion logic. The first iteration is
intentionally dependency-light:
- No real DB network calls yet (introspection is stubbed)
- Provides deterministic control flow and a stable metrics structure
"""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID


def _introspect_mysql(*, tenant_id: UUID, dataset_id: UUID, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Stub: in a later iteration this will connect to MySQL and return table/column metadata.

    Returns a list of table dicts, each optionally containing `columns: [...]`.
    """
    _ = (tenant_id, dataset_id, config)
    return []


def _introspect_sqlserver(*, tenant_id: UUID, dataset_id: UUID, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Stub: in a later iteration this will connect to SQL Server and return table/column metadata.

    Returns a list of table dicts, each optionally containing `columns: [...]`.
    """
    _ = (tenant_id, dataset_id, config)
    return []


def run_catalog_sync(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    connector_id: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Run a catalog sync for a dataset.

    This is currently a stub used to validate wiring and permission gates.
    """
    cid = str(connector_id or "").strip()
    if cid == "mysql_catalog":
        tables = _introspect_mysql(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
        return {"engine": "mysql", "tables": int(len(tables))}
    if cid == "sqlserver_catalog":
        tables = _introspect_sqlserver(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
        return {"engine": "sqlserver", "tables": int(len(tables))}
    raise ValueError("unsupported_connector_id")

