"""Permission-scoped live reads from registered MySQL catalog assets."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.connectors.catalog import _connect_catalog
from app.models.connectors.configs import ConnectorConfig
from app.models.datasets.catalog import DbCatalogTable
from app.services.connectors.configs import build_saved_connector_run_config
from app.services.datasets.management import assert_dataset_readable, ensure_member, get_dataset
from app.services.tables.field_security import FlsUserContext, build_fls_column_mask_map, parse_fls_policy_from_metadata


@dataclass(frozen=True)
class MysqlAsset:
    id: str
    table_name: str
    columns: set[str]
    connector: ConnectorConfig
    revision: str

    def select(self, sql: str, parameters: tuple = (), *, limit: int) -> list[tuple[Any, ...]]:
        try:
            with _connect_catalog(engine_name="mysql", config=build_saved_connector_run_config(self.connector)) as conn:
                conn.exec_driver_sql("SET time_zone = '+00:00'")
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                return [tuple(row) for row in conn.exec_driver_sql(sql, parameters).fetchmany(limit)]
        except (OperationalError, ProgrammingError) as exc:
            code = exc.orig.args[0] if exc.orig.args else None
            if code in {1054, 1146}:
                raise HTTPException(status_code=409, detail="MySQL asset schema changed; review its binding") from exc
            raise HTTPException(status_code=503, detail="MySQL asset is unavailable") from exc


def mysql_identifier(name: str) -> str:
    delimiter = chr(96)
    return delimiter + name.replace(delimiter, delimiter * 2) + delimiter


def authorized_mysql_asset(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    asset_id: str,
    expected_revision: str | None = None,
) -> MysqlAsset:
    try:
        table_id = UUID(asset_id.removeprefix("catalog:"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid DB Catalog asset ID") from exc
    table = db.scalar(
        select(DbCatalogTable).where(
            DbCatalogTable.id == table_id,
            DbCatalogTable.tenant_id == tenant_id,
            DbCatalogTable.engine == "mysql",
        )
    )
    if table is None:
        raise HTTPException(status_code=404, detail="MySQL catalog asset not found")
    dataset = get_dataset(db, tenant_id, table.dataset_id)
    assert_dataset_readable(db, dataset, account_id)
    if expected_revision is not None and table.fingerprint != expected_revision:
        raise HTTPException(status_code=409, detail="MySQL asset schema changed; review its binding")
    connector = db.scalar(
        select(ConnectorConfig).where(
            ConnectorConfig.id == table.connector_config_id,
            ConnectorConfig.tenant_id == tenant_id,
            ConnectorConfig.dataset_id == dataset.id,
            ConnectorConfig.enabled.is_(True),
            ConnectorConfig.connector_id == "mysql_catalog",
        )
    )
    if connector is None or connector.config["database"].strip() != table.db_name:
        raise HTTPException(status_code=409, detail="MySQL asset requires its current saved connector")
    columns = {column.name for column in table.columns}
    policy = parse_fls_policy_from_metadata(dataset.dataset_metadata)
    if policy is not None:
        member = ensure_member(db, tenant_id, account_id)
        columns -= build_fls_column_mask_map(
            policy,
            source="db_catalog",
            columns=sorted(columns),
            ctx=FlsUserContext(account_id=account_id, role=member.role.lower()),
        ).keys()
    return MysqlAsset(asset_id, table.table_name, columns, connector, table.fingerprint)
