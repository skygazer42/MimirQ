"""Read database catalogs and bounded row snapshots for connector runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

MYSQL_TABLES_SQL = (
    "SELECT "
    "table_schema AS db_name, "
    "table_name, "
    "CASE WHEN table_type = 'VIEW' THEN 'view' ELSE 'table' END AS table_type, "
    "table_comment AS comment, "
    "table_rows AS row_count_estimate "
    "FROM information_schema.tables "
    "WHERE table_schema = :database "
    "ORDER BY table_name"
)
MYSQL_COLUMNS_SQL = (
    "SELECT "
    "ordinal_position AS ordinal, "
    "column_name AS name, "
    "column_type AS data_type, "
    "CASE WHEN is_nullable = 'YES' THEN 1 ELSE 0 END AS nullable, "
    "column_comment AS comment "
    "FROM information_schema.columns "
    "WHERE table_schema = :database AND table_name = :table_name "
    "ORDER BY ordinal_position"
)
SQLSERVER_TABLES_SQL = (
    "SELECT "
    "DB_NAME() AS db_name, "
    "s.name AS schema_name, "
    "o.name AS table_name, "
    "CASE WHEN o.type = 'V' THEN 'view' ELSE 'table' END AS table_type, "
    "CASE WHEN o.type = 'U' THEN SUM(p.row_count) ELSE NULL END AS row_count_estimate "
    "FROM sys.objects o "
    "JOIN sys.schemas s ON s.schema_id = o.schema_id "
    "LEFT JOIN sys.dm_db_partition_stats p ON p.object_id = o.object_id AND p.index_id IN (0, 1) "
    "WHERE o.type IN ('U', 'V') "
    "GROUP BY s.name, o.name, o.type "
    "ORDER BY s.name, o.name"
)
SQLSERVER_COLUMNS_SQL = (
    "SELECT "
    "c.column_id AS ordinal, "
    "c.name AS name, "
    "t.name AS data_type, "
    "c.is_nullable AS nullable, "
    "CAST(NULL AS NVARCHAR(4000)) AS comment "
    "FROM sys.columns c "
    "JOIN sys.objects o ON o.object_id = c.object_id "
    "JOIN sys.schemas s ON s.schema_id = o.schema_id "
    "JOIN sys.types t ON t.user_type_id = c.user_type_id "
    "WHERE o.type IN ('U', 'V') AND s.name = :schema_name AND o.name = :table_name "
    "ORDER BY c.column_id"
)


@dataclass(frozen=True)
class CatalogColumnInput:
    ordinal: int
    name: str
    data_type: str | None = None
    nullable: bool | None = None
    comment: str | None = None


@dataclass(frozen=True)
class CatalogTableInput:
    engine: str
    db_name: str
    schema_name: str | None
    table_name: str
    table_type: str
    comment: str | None
    fingerprint: str
    columns: list[CatalogColumnInput] = field(default_factory=list)
    row_count_estimate: int | None = None


class CatalogStore(Protocol):
    def upsert_table(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        connector_config_id: UUID | None,
        table: CatalogTableInput,
        seen_at: datetime,
    ) -> UUID: ...

    def replace_columns(self, *, table_id: UUID, columns: Sequence[CatalogColumnInput]) -> int: ...

    def insert_profile_snapshot(
        self,
        *,
        table_id: UUID,
        entitlement_hash: str,
        profile: dict[str, Any],
        sample_meta: dict[str, Any],
    ) -> UUID: ...


def _engine_name(connector_id: str) -> str:
    connector_id = connector_id.strip()
    if connector_id == "mysql_catalog":
        return "mysql"
    if connector_id == "sqlserver_catalog":
        return "sqlserver"
    raise ValueError("unsupported_connector_id")


@contextmanager
def _connect_catalog(*, engine_name: str, config: Mapping[str, Any]) -> Iterator[Connection]:
    is_mysql = engine_name == "mysql"
    host = config["host"].strip()
    database = config["database"].strip()
    username = config["username"].strip()
    if not host or not database or not username:
        raise ValueError(f"{engine_name} config requires host/database/username")
    port = int(config.get("port") or (3306 if is_mysql else 1433))
    query = {"charset": "utf8mb4"}
    if not is_mysql:
        raw_driver = config.get("odbc_driver")
        driver = "ODBC Driver 18 for SQL Server" if raw_driver is None else raw_driver.strip()
        query = {"driver": driver or "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"}
    url = URL.create(
        "mysql+pymysql" if is_mysql else "mssql+pyodbc",
        username=username,
        password=config["password"],
        host=host,
        port=port,
        database=database,
        query=query,
    )
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()


def _fingerprint(*, engine: str, db_name: str, schema_name: str | None, table_name: str) -> str:
    key = "|".join((engine.strip().lower(), db_name.strip(), (schema_name or "").strip(), table_name.strip()))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _entitlement_hash(*, engine: str, config: Mapping[str, Any]) -> str:
    # Saved configs retain extra fields and omitted defaults as part of their permission identity.
    safe_config: dict[str, Any] = {}
    for raw_key, value in config.items():
        key = raw_key.strip()
        if key and key != "password" and not key.startswith("_"):
            safe_config[key] = value
    payload = {"engine": engine.strip().lower(), "config": safe_config}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _catalog_columns(rows: Sequence[Mapping[str, Any]]) -> list[CatalogColumnInput]:
    columns: list[CatalogColumnInput] = []
    for row in rows:
        name = row["name"].strip()
        if not name:
            continue
        columns.append(
            CatalogColumnInput(
                ordinal=int(row["ordinal"]),
                name=name,
                data_type=row["data_type"],
                nullable=bool(row["nullable"]),
                comment=row["comment"],
            )
        )
        if len(columns) >= 5000:
            break
    return columns


def _catalog_table(row: Mapping[str, Any], *, engine: str, columns: list[CatalogColumnInput]) -> CatalogTableInput:
    db_name = row["db_name"].strip()
    schema_name = row["schema_name"].strip() if engine == "sqlserver" else None
    table_name = row["table_name"].strip()
    row_count = row["row_count_estimate"]
    return CatalogTableInput(
        engine=engine,
        db_name=db_name,
        schema_name=schema_name,
        table_name=table_name,
        table_type=row["table_type"],
        comment=row.get("comment"),  # SQL Server's table query does not select comments.
        fingerprint=_fingerprint(engine=engine, db_name=db_name, schema_name=schema_name, table_name=table_name),
        columns=columns,
        row_count_estimate=int(row_count) if row_count is not None else None,
    )


def _read_mysql_catalog(config: Mapping[str, Any], *, max_tables: int) -> list[CatalogTableInput]:
    include_tables = {name.strip().lower() for name in (config.get("include_tables") or []) if name.strip()}
    database = config["database"].strip()
    tables: list[CatalogTableInput] = []
    with _connect_catalog(engine_name="mysql", config=config) as connection:
        rows = connection.execute(text(MYSQL_TABLES_SQL), {"database": database}).mappings().all()
        for row in rows:
            table_name = row["table_name"].strip()
            if not table_name:
                continue
            if include_tables and table_name.lower() not in include_tables:
                continue
            column_rows = (
                connection.execute(text(MYSQL_COLUMNS_SQL), {"database": database, "table_name": table_name})
                .mappings()
                .all()
            )
            tables.append(_catalog_table(row, engine="mysql", columns=_catalog_columns(column_rows)))
            if len(tables) >= max_tables:
                break
    return tables


def _sqlserver_table_filters(config: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    include_schemas = {schema.strip().lower() for schema in (config.get("include_schemas") or []) if schema.strip()}
    include_fqn: set[str] = set()
    include_names: set[str] = set()
    for raw_table in config.get("include_tables") or []:
        table = raw_table.strip()
        if not table:
            continue
        if "." not in table:
            include_names.add(table.lower())
            continue
        schema, name = table.split(".", 1)
        if schema.strip() and name.strip():
            include_fqn.add(f"{schema.strip().lower()}.{name.strip().lower()}")
    return include_schemas, include_fqn, include_names


def _sqlserver_table_included(
    *,
    schema_name: str,
    table_name: str,
    include_schemas: set[str],
    include_fqn: set[str],
    include_names: set[str],
) -> bool:
    if include_schemas and schema_name.lower() not in include_schemas:
        return False
    if not include_fqn and not include_names:
        return True
    fqn = f"{schema_name.lower()}.{table_name.lower()}" if schema_name else table_name.lower()
    return fqn in include_fqn or table_name.lower() in include_names


def _read_sqlserver_catalog(config: Mapping[str, Any], *, max_tables: int) -> list[CatalogTableInput]:
    include_schemas, include_fqn, include_names = _sqlserver_table_filters(config)
    tables: list[CatalogTableInput] = []
    with _connect_catalog(engine_name="sqlserver", config=config) as connection:
        rows = connection.execute(text(SQLSERVER_TABLES_SQL), {"database": config["database"].strip()}).mappings().all()
        for row in rows:
            schema_name = row["schema_name"].strip()
            table_name = row["table_name"].strip()
            if not table_name:
                continue
            if not _sqlserver_table_included(
                schema_name=schema_name,
                table_name=table_name,
                include_schemas=include_schemas,
                include_fqn=include_fqn,
                include_names=include_names,
            ):
                continue
            column_rows = (
                connection.execute(text(SQLSERVER_COLUMNS_SQL), {"schema_name": schema_name, "table_name": table_name})
                .mappings()
                .all()
            )
            tables.append(_catalog_table(row, engine="sqlserver", columns=_catalog_columns(column_rows)))
            if len(tables) >= max_tables:
                break
    return tables


def _read_catalog(*, engine: str, config: Mapping[str, Any]) -> list[CatalogTableInput]:
    # Saved configs are raw JSON, so their existing limits are resolved at this boundary.
    try:
        max_tables = int(config.get("max_tables") or 200)
    except (TypeError, ValueError, OverflowError):
        max_tables = 200
    max_tables = max(1, min(max_tables, 2000))
    if engine == "mysql":
        return _read_mysql_catalog(config, max_tables=max_tables)
    return _read_sqlserver_catalog(config, max_tables=max_tables)


def run_catalog_sync(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    connector_id: str,
    config: Mapping[str, Any],
    store: CatalogStore,
    connector_config_id: UUID | None = None,
) -> dict[str, Any]:
    """Persist a dataset's catalog through the caller-owned transaction."""
    engine = _engine_name(connector_id)
    tables = _read_catalog(engine=engine, config=config)
    seen_at = datetime.now(UTC)
    entitlement_hash = _entitlement_hash(engine=engine, config=config)
    columns_upserted = 0
    profiles_written = 0
    for table in tables:
        table_id = store.upsert_table(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            connector_config_id=connector_config_id,
            table=table,
            seen_at=seen_at,
        )
        columns_upserted += store.replace_columns(table_id=table_id, columns=table.columns)
        if config.get("profile_enabled", False):
            profile = {} if table.row_count_estimate is None else {"row_count_estimate": table.row_count_estimate}
            store.insert_profile_snapshot(
                table_id=table_id,
                entitlement_hash=entitlement_hash,
                profile=profile,
                sample_meta={"strategy": "catalog_sync", "seen_at": seen_at.isoformat()},
            )
            profiles_written += 1
    return {
        "engine": engine,
        "tables": len(tables),
        "tables_upserted": len(tables),
        "columns_upserted": columns_upserted,
        "profiles_written": profiles_written,
        "entitlement_hash": entitlement_hash,
    }


def _jsonify_row_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _row_hash(row: dict[str, Any]) -> str:
    payload = {key: _jsonify_row_value(row[key]) for key in sorted(row) if key != "__row_pk_hash"}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _snapshot_token(*, source_table: str, rows: Sequence[dict[str, Any]]) -> str:
    payload = {"source_table": source_table, "pk_hashes": [row["__row_pk_hash"] for row in rows]}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _quote_mysql_ident(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def _quote_sqlserver_ident(name: str) -> str:
    return f"[{name.replace(']', ']]')}]"


def _snapshot_payload(
    *, source_table: str, table: CatalogTableInput, rows_raw: Sequence[Mapping[str, Any]], max_rows: int, max_cols: int
) -> dict[str, Any]:
    columns = list(rows_raw[0])[:max_cols] if rows_raw else [column.name for column in table.columns[:max_cols]]
    rows: list[dict[str, Any]] = []
    for row in rows_raw[:max_rows]:
        record = {column: _jsonify_row_value(row[column]) for column in columns}
        record["__row_pk_hash"] = _row_hash(record)
        rows.append(record)
    return {
        "source_table": source_table,
        "sheet_name": source_table,
        "source_sync_token": _snapshot_token(source_table=source_table, rows=rows),
        "source_pk_hash_col": "__row_pk_hash",
        "columns": columns + (["__row_pk_hash"] if "__row_pk_hash" not in columns else []),
        "rows": rows,
    }


def extract_row_snapshots(
    *,
    connector_id: str,
    config: Mapping[str, Any],
    max_tables: int,
    max_rows_per_table: int,
    max_cols: int,
) -> list[dict[str, Any]]:
    """Read bounded per-table snapshots for the optional TAG sidecar."""
    if max_tables <= 0 or max_rows_per_table <= 0 or max_cols <= 0:
        return []
    engine = _engine_name(connector_id)
    tables = _read_catalog(engine=engine, config=config)
    snapshots: list[dict[str, Any]] = []
    with _connect_catalog(engine_name=engine, config=config) as connection:
        for table in tables:
            if len(snapshots) >= max_tables:
                break
            source_table = ".".join(part for part in (table.db_name, table.schema_name, table.table_name) if part)
            if engine == "mysql":
                sql = f"SELECT * FROM {_quote_mysql_ident(table.table_name)} LIMIT {max_rows_per_table}"
            else:
                table_ref = (
                    f"{_quote_sqlserver_ident(table.schema_name)}.{_quote_sqlserver_ident(table.table_name)}"
                    if table.schema_name
                    else _quote_sqlserver_ident(table.table_name)
                )
                sql = f"SELECT TOP ({max_rows_per_table}) * FROM {table_ref}"
            try:
                rows = connection.execute(text(sql)).mappings().all()
            except SQLAlchemyError as exc:
                # A stale or inaccessible table may be skipped by this optional sidecar.
                logger.warning("Unable to read database row snapshot for %s: %s", source_table, exc)
                continue
            snapshots.append(
                _snapshot_payload(
                    source_table=source_table,
                    table=table,
                    rows_raw=rows,
                    max_rows=max_rows_per_table,
                    max_cols=max_cols,
                )
            )
    return snapshots
