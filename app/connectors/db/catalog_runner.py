"""
DB catalog sync runner (stub).

This module wires connector runs to catalog ingestion logic. The first iteration is
intentionally dependency-light:
- No real DB network calls yet (introspection is stubbed)
- Provides deterministic control flow and a stable metrics structure
"""

import contextlib
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.rag.core.logging import get_logger


def _now() -> datetime:
    return datetime.now(UTC)


logger = get_logger(__name__)


def _fingerprint(*, engine: str, db_name: str, schema_name: str | None, table_name: str) -> str:
    # Stable table identity for upsert. Keep it deterministic and do not include secrets.
    key = "|".join(
        (
            str(engine or "").strip().lower(),
            str(db_name or "").strip(),
            str(schema_name or "").strip(),
            str(table_name or "").strip(),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _entitlement_hash(*, engine: str, config: dict[str, Any]) -> str:
    """
    Stable hash representing the permission context of a catalog run.

    Important: do not include secrets (e.g., passwords).
    """
    safe_cfg: dict[str, Any] = {}
    for k, v in (config or {}).items():
        key = str(k or "").strip()
        if not key or key in {"password"} or key.startswith("_"):
            continue
        safe_cfg[key] = v
    payload = {"engine": str(engine or "").strip().lower(), "config": safe_cfg}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


@contextlib.contextmanager
def _connect_sqlserver(config: dict[str, Any]):  # noqa: ANN201
    """
    Connect to SQL Server using SQLAlchemy.

    Notes:
    - Uses pyodbc driver via SQLAlchemy dialect (mssql+pyodbc).
    - Kept small and easily monkeypatchable for unit tests.
    """
    host = str(config.get("host") or "").strip()
    port = int(config.get("port") or 1433)
    database = str(config.get("database") or "").strip()
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    if not host or not database or not username:
        raise ValueError("sqlserver config requires host/database/username")

    driver = str(config.get("odbc_driver") or "").strip() or "ODBC Driver 18 for SQL Server"

    # Import lazily so pure unit tests can monkeypatch _connect_sqlserver without requiring pyodbc.
    from sqlalchemy import create_engine  # noqa: WPS433
    from sqlalchemy.engine import URL  # noqa: WPS433
    from sqlalchemy.pool import NullPool  # noqa: WPS433

    url = URL.create(
        "mssql+pyodbc",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
        query={
            "driver": driver,
            # Developer-friendly defaults; production can override via `odbc_driver` and DSN policy.
            "TrustServerCertificate": "yes",
        },
    )
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


@contextlib.contextmanager
def _connect_mysql(config: dict[str, Any]):  # noqa: ANN201
    """
    Connect to MySQL using SQLAlchemy.

    Notes:
    - Uses pymysql driver via SQLAlchemy dialect (mysql+pymysql).
    - Kept small and easily monkeypatchable for unit tests.
    """
    host = str(config.get("host") or "").strip()
    port = int(config.get("port") or 3306)
    database = str(config.get("database") or "").strip()
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    if not host or not database or not username:
        raise ValueError("mysql config requires host/database/username")

    # Import lazily so pure unit tests can monkeypatch _connect_mysql without requiring pymysql.
    from sqlalchemy import create_engine  # noqa: WPS433
    from sqlalchemy.engine import URL  # noqa: WPS433
    from sqlalchemy.pool import NullPool  # noqa: WPS433

    url = URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


def _bounded_positive_int(value: Any, *, default: int, upper: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(1, min(parsed, upper))


def _normalize_column_dict(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    try:
        ordinal = int(raw.get("ordinal") or 0)
    except (TypeError, ValueError, OverflowError):
        ordinal = 0
    return {
        "ordinal": ordinal,
        "name": name,
        "data_type": (str(raw.get("data_type") or "").strip() or None),
        "nullable": (bool(raw.get("nullable")) if raw.get("nullable") is not None else None),
        "comment": (str(raw.get("comment") or "").strip() or None),
    }


def _extract_column_dicts(*, col_rows: Sequence[Any], limit: int = 5000) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for raw in col_rows or []:
        column = _normalize_column_dict(raw)
        if column is None:
            continue
        columns.append(column)
        if len(columns) >= limit:
            break
    return columns


def _mysql_include_tables(config: dict[str, Any]) -> set[str]:
    return {
        str(table or "").strip().lower() for table in (config.get("include_tables") or []) if str(table or "").strip()
    }


def _sqlserver_table_filters(config: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    include_schemas = {
        str(schema or "").strip().lower()
        for schema in (config.get("include_schemas") or [])
        if str(schema or "").strip()
    }
    include_fqn: set[str] = set()
    include_names: set[str] = set()
    for raw_table in config.get("include_tables") or []:
        table = str(raw_table or "").strip()
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
    if include_fqn and fqn not in include_fqn:
        return False
    return not include_names or table_name.lower() in include_names or fqn in include_fqn


def _mysql_table_entry(*, row: dict[str, Any], database: str, columns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "db_name": (str(row.get("db_name") or database).strip() or database),
        "schema_name": None,
        "table_name": str(row.get("table_name") or "").strip(),
        "table_type": (str(row.get("table_type") or "table").strip().lower() or "table"),
        "comment": (str(row.get("comment") or "").strip() or None),
        "row_count_estimate": row.get("row_count_estimate"),
        "columns": columns,
    }


def _sqlserver_table_entry(
    *, row: dict[str, Any], database: str, schema_name: str, columns: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "db_name": (str(row.get("db_name") or database).strip() or database),
        "schema_name": (schema_name or None),
        "table_name": str(row.get("table_name") or "").strip(),
        "table_type": (str(row.get("table_type") or "table").strip().lower() or "table"),
        "comment": (str(row.get("comment") or "").strip() or None),
        "row_count_estimate": row.get("row_count_estimate"),
        "columns": columns,
    }


def _introspect_mysql(*, tenant_id: UUID, dataset_id: UUID, config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Stub: in a later iteration this will connect to MySQL and return table/column metadata.

    Returns a list of table dicts, each optionally containing `columns: [...]`.
    """
    _ = (tenant_id, dataset_id)
    database = str(config.get("database") or "").strip()
    if not database:
        return []

    include_tables = _mysql_include_tables(config)
    max_tables = _bounded_positive_int(config.get("max_tables"), default=200, upper=2000)

    from sqlalchemy import text  # noqa: WPS433

    from app.connectors.db.introspection import mysql_list_columns_sql, mysql_list_tables_sql  # noqa: WPS433

    out: list[dict[str, Any]] = []
    with _connect_mysql(config) as conn:
        tables_sql = mysql_list_tables_sql(database=database)
        rows = conn.execute(text(tables_sql), {"database": database}).mappings().all()

        cols_sql = mysql_list_columns_sql(database=database)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            table_name = str(row.get("table_name") or "").strip()
            if not table_name:
                continue
            if include_tables and table_name.lower() not in include_tables:
                continue

            col_rows = conn.execute(text(cols_sql), {"database": database, "table_name": table_name}).mappings().all()
            columns = _extract_column_dicts(col_rows=col_rows)
            out.append(_mysql_table_entry(row=row, database=database, columns=columns))
            if len(out) >= max_tables:
                break
    return out


def _introspect_sqlserver(*, tenant_id: UUID, dataset_id: UUID, config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Stub: in a later iteration this will connect to SQL Server and return table/column metadata.

    Returns a list of table dicts, each optionally containing `columns: [...]`.
    """
    _ = (tenant_id, dataset_id)
    database = str(config.get("database") or "").strip()
    if not database:
        return []

    include_schemas, include_fqn, include_names = _sqlserver_table_filters(config)
    max_tables = _bounded_positive_int(config.get("max_tables"), default=200, upper=2000)

    from sqlalchemy import text  # noqa: WPS433

    from app.connectors.db.introspection import sqlserver_list_columns_sql, sqlserver_list_tables_sql  # noqa: WPS433

    out: list[dict[str, Any]] = []
    with _connect_sqlserver(config) as conn:
        tables_sql = sqlserver_list_tables_sql(database=database)
        table_rows = conn.execute(text(tables_sql), {"database": database}).mappings().all()

        cols_sql = sqlserver_list_columns_sql(database=database)
        for row in table_rows or []:
            if not isinstance(row, dict):
                continue
            schema_name = str(row.get("schema_name") or "").strip()
            table_name = str(row.get("table_name") or "").strip()
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

            col_rows = (
                conn.execute(text(cols_sql), {"schema_name": schema_name, "table_name": table_name}).mappings().all()
            )
            columns = _extract_column_dicts(col_rows=col_rows)
            out.append(_sqlserver_table_entry(row=row, database=database, schema_name=schema_name, columns=columns))
            if len(out) >= max_tables:
                break
    return out


def _load_catalog_tables(
    *,
    connector_id: str,
    tenant_id: UUID,
    dataset_id: UUID,
    config: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    cid = str(connector_id or "").strip()
    if cid == "mysql_catalog":
        return "mysql", _introspect_mysql(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
    if cid == "sqlserver_catalog":
        return "sqlserver", _introspect_sqlserver(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
    raise ValueError("unsupported_connector_id")


def _normalize_catalog_columns(raw_columns: Any) -> list[CatalogColumnInput]:
    columns: list[CatalogColumnInput] = []
    for raw in raw_columns if isinstance(raw_columns, list) else []:
        column = _normalize_column_dict(raw)
        if column is None:
            continue
        columns.append(
            CatalogColumnInput(
                ordinal=int(column["ordinal"]),
                name=str(column["name"]),
                data_type=column["data_type"],
                nullable=column["nullable"],
                comment=column["comment"],
            )
        )
        if len(columns) >= 5000:
            break
    return columns


def _normalize_profile_from_table(
    raw_table: dict[str, Any], *, seen_at: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile: dict[str, Any] = {}
    row_count_estimate = raw_table.get("row_count_estimate")
    try:
        if row_count_estimate is not None:
            profile["row_count_estimate"] = int(row_count_estimate)
    except (TypeError, ValueError, OverflowError):
        pass
    return profile, {"strategy": "catalog_sync", "seen_at": seen_at.isoformat()}


def _build_catalog_sync_item(
    *,
    raw_table: Any,
    config: dict[str, Any],
    engine: str,
    seen_at: datetime,
) -> tuple[CatalogTableInput, dict[str, Any], dict[str, Any]] | None:
    if not isinstance(raw_table, dict):
        return None
    db_name = str(raw_table.get("db_name") or config.get("database") or "").strip()
    table_name = str(raw_table.get("table_name") or "").strip()
    if not db_name or not table_name:
        return None
    schema_name = str(raw_table.get("schema_name") or "").strip() or None
    table_type = str(raw_table.get("table_type") or "table").strip().lower()
    if table_type != "view":
        table_type = "table"
    profile, sample_meta = _normalize_profile_from_table(raw_table, seen_at=seen_at)
    return (
        CatalogTableInput(
            engine=engine,
            db_name=db_name,
            schema_name=schema_name,
            table_name=table_name,
            table_type=table_type,
            comment=(str(raw_table.get("comment") or "").strip() or None),
            fingerprint=_fingerprint(engine=engine, db_name=db_name, schema_name=schema_name, table_name=table_name),
            columns=_normalize_catalog_columns(raw_table.get("columns")),
        ),
        profile,
        sample_meta,
    )


def _persist_catalog_sync_items(
    *,
    store: CatalogStore,
    items: Sequence[tuple[CatalogTableInput, dict[str, Any], dict[str, Any]]],
    tenant_id: UUID,
    dataset_id: UUID,
    connector_config_id: UUID | None,
    seen_at: datetime,
    entitlement_hash: str,
    profile_enabled: bool,
) -> tuple[int, int, int]:
    tables_upserted = 0
    columns_upserted = 0
    profiles_written = 0
    for table, profile, sample_meta in items:
        table_id = store.upsert_table(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            connector_config_id=connector_config_id,
            table=table,
            seen_at=seen_at,
        )
        tables_upserted += 1
        columns_upserted += int(store.replace_columns(table_id=table_id, columns=table.columns))
        if not profile_enabled:
            continue
        store.insert_profile_snapshot(
            table_id=table_id,
            entitlement_hash=entitlement_hash,
            profile=dict(profile or {}),
            sample_meta=dict(sample_meta or {}),
        )
        profiles_written += 1
    return tables_upserted, columns_upserted, profiles_written


def run_catalog_sync(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    connector_id: str,
    config: dict[str, Any],
    store: CatalogStore | None = None,
    connector_config_id: UUID | None = None,
) -> dict[str, Any]:
    """
    Run a catalog sync for a dataset.

    This is currently a stub used to validate wiring and permission gates.
    """
    engine, raw_tables = _load_catalog_tables(
        connector_id=connector_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config=dict(config or {}),
    )
    seen_at = _now()
    items: list[tuple[CatalogTableInput, dict[str, Any], dict[str, Any]]] = []
    max_tables = _bounded_positive_int(config.get("max_tables"), default=200, upper=2000)
    for raw_table in raw_tables or []:
        item = _build_catalog_sync_item(raw_table=raw_table, config=config, engine=engine, seen_at=seen_at)
        if item is None:
            continue
        items.append(item)
        if len(items) >= max_tables:
            break

    tables_upserted = 0
    columns_upserted = 0
    profiles_written = 0
    ent_hash = _entitlement_hash(engine=engine, config=dict(config or {}))
    if store is not None:
        profile_enabled = bool(config.get("profile_enabled")) if "profile_enabled" in (config or {}) else False
        tables_upserted, columns_upserted, profiles_written = _persist_catalog_sync_items(
            store=store,
            items=items,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            connector_config_id=connector_config_id,
            seen_at=seen_at,
            entitlement_hash=ent_hash,
            profile_enabled=profile_enabled,
        )

    return {
        "engine": engine,
        "tables": int(len(items)),
        "tables_upserted": int(tables_upserted),
        "columns_upserted": int(columns_upserted),
        "profiles_written": int(profiles_written),
        "entitlement_hash": str(ent_hash or ""),
    }


def _jsonify_row_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    try:
        if hasattr(v, "item"):
            return v.item()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to unwrap DB catalog scalar value via item(): %s", exc)
    return str(v)


def _row_hash(row: dict[str, Any], *, exclude_keys: Sequence[str] | None = None) -> str:
    excluded = {str(k) for k in (exclude_keys or [])}
    payload: dict[str, Any] = {}
    for k in sorted(row.keys()):
        if str(k) in excluded:
            continue
        payload[str(k)] = _jsonify_row_value(row.get(k))
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _snapshot_token(*, source_table: str, rows: Sequence[dict[str, Any]]) -> str:
    payload = {
        "source_table": str(source_table or ""),
        "pk_hashes": [str(r.get("__row_pk_hash") or "") for r in rows if isinstance(r, dict)],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _quote_mysql_ident(name: str) -> str:
    return f"`{str(name or '').replace('`', '``')}`"


def _quote_sqlserver_ident(name: str) -> str:
    return f"[{str(name or '').replace(']', ']]')}]"


def _snapshot_columns(rows_raw: Sequence[Any], table_columns: Any, *, max_cols: int) -> list[str]:
    if rows_raw:
        return [str(key) for key in list(rows_raw[0].keys())[:max_cols]]
    columns: list[str] = []
    if not isinstance(table_columns, list):
        return columns
    for raw in table_columns:
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
        else:
            name = str(raw or "").strip()
        if not name:
            continue
        columns.append(name)
        if len(columns) >= max_cols:
            break
    return columns


def _snapshot_rows(rows_raw: Sequence[Any], *, columns: Sequence[str], max_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in rows_raw:
        if len(rows) >= max_rows:
            break
        record = {column: _jsonify_row_value(row.get(column)) for column in columns}
        record["__row_pk_hash"] = _row_hash(record, exclude_keys=["__row_pk_hash"])
        rows.append(record)
    return rows


def _snapshot_payload(*, source_table: str, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_table": source_table,
        "sheet_name": source_table,
        "source_sync_token": _snapshot_token(source_table=source_table, rows=rows),
        "source_pk_hash_col": "__row_pk_hash",
        "columns": columns + (["__row_pk_hash"] if "__row_pk_hash" not in columns else []),
        "rows": rows,
    }


def _mysql_snapshot_sql(table_name: str, max_rows: int) -> str:
    return f"SELECT * FROM {_quote_mysql_ident(table_name)} LIMIT {max_rows}"


def _sqlserver_table_ref(schema_name: str, table_name: str) -> str:
    if schema_name:
        return f"{_quote_sqlserver_ident(schema_name)}.{_quote_sqlserver_ident(table_name)}"
    return _quote_sqlserver_ident(table_name)


def _sqlserver_snapshot_sql(schema_name: str, table_name: str, max_rows: int) -> str:
    return f"SELECT TOP ({max_rows}) * FROM {_sqlserver_table_ref(schema_name, table_name)}"


def _mysql_source_table(raw_table: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    table_name = str(raw_table.get("table_name") or "").strip()
    db_name = str(raw_table.get("db_name") or config.get("database") or "").strip()
    source_table = f"{db_name}.{table_name}" if db_name else table_name
    return table_name, source_table


def _sqlserver_source_table(raw_table: dict[str, Any], config: dict[str, Any]) -> tuple[str, str, str]:
    schema_name = str(raw_table.get("schema_name") or "").strip()
    table_name = str(raw_table.get("table_name") or "").strip()
    db_name = str(raw_table.get("db_name") or config.get("database") or "").strip()
    source_table = f"{db_name}.{schema_name}.{table_name}" if schema_name else f"{db_name}.{table_name}"
    return schema_name, table_name, source_table


def _extract_table_snapshot(
    *,
    raw_table: Any,
    fetch_rows: callable,
    source_table_data: tuple[str, str] | tuple[str, str, str],
    max_rows: int,
    max_cols: int,
) -> dict[str, Any] | None:
    if not isinstance(raw_table, dict):
        return None
    if len(source_table_data) == 2:
        table_name, source_table = source_table_data
        fetch_args = (table_name,)
    else:
        schema_name, table_name, source_table = source_table_data
        fetch_args = (schema_name, table_name)
    if not table_name:
        return None
    rows_raw = fetch_rows(*fetch_args)
    columns = _snapshot_columns(rows_raw, raw_table.get("columns"), max_cols=max_cols)
    rows = _snapshot_rows(rows_raw, columns=columns, max_rows=max_rows)
    return _snapshot_payload(source_table=source_table, columns=columns, rows=rows)


def _extract_mysql_row_snapshots(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    config: dict[str, Any],
    max_tables: int,
    max_rows: int,
    max_cols: int,
) -> list[dict[str, Any]]:
    tables = _introspect_mysql(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
    out: list[dict[str, Any]] = []
    with _connect_mysql(dict(config or {})) as conn:
        from sqlalchemy import text  # noqa: WPS433

        def _fetch_mysql_rows(table_name: str) -> list[dict[str, Any]]:
            sql = _mysql_snapshot_sql(table_name, max_rows)  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            return conn.execute(text(sql)).mappings().all()

        for table in tables:
            if len(out) >= max_tables:
                break
            try:
                snapshot = _extract_table_snapshot(
                    raw_table=table,
                    fetch_rows=_fetch_mysql_rows,
                    source_table_data=_mysql_source_table(table, config) if isinstance(table, dict) else ("", ""),
                    max_rows=max_rows,
                    max_cols=max_cols,
                )
            except Exception:  # noqa: BLE001
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if snapshot is not None:
                out.append(snapshot)
    return out


def _extract_sqlserver_row_snapshots(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    config: dict[str, Any],
    max_tables: int,
    max_rows: int,
    max_cols: int,
) -> list[dict[str, Any]]:
    tables = _introspect_sqlserver(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
    out: list[dict[str, Any]] = []
    with _connect_sqlserver(dict(config or {})) as conn:
        from sqlalchemy import text  # noqa: WPS433

        def _fetch_sqlserver_rows(schema_name: str, table_name: str) -> list[dict[str, Any]]:
            sql = _sqlserver_snapshot_sql(schema_name, table_name, max_rows)  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            return conn.execute(text(sql)).mappings().all()

        for table in tables:
            if len(out) >= max_tables:
                break
            try:
                snapshot = _extract_table_snapshot(
                    raw_table=table,
                    fetch_rows=_fetch_sqlserver_rows,
                    source_table_data=_sqlserver_source_table(table, config)
                    if isinstance(table, dict)
                    else ("", "", ""),
                    max_rows=max_rows,
                    max_cols=max_cols,
                )
            except Exception:  # noqa: BLE001
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if snapshot is not None:
                out.append(snapshot)
    return out


def extract_row_snapshots(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    connector_id: str,
    config: dict[str, Any],
    max_tables: int,
    max_rows_per_table: int,
    max_cols: int,
) -> list[dict[str, Any]]:
    """
    Extract bounded per-table row snapshots for TAG sidecar recall.

    The output is connector-agnostic and intentionally small:
      [{"source_table","sheet_name","source_sync_token","source_pk_hash_col","columns","rows"}, ...]
    """
    cid = str(connector_id or "").strip()
    max_tables_i = max(0, int(max_tables or 0))
    max_rows_i = max(0, int(max_rows_per_table or 0))
    max_cols_i = max(0, int(max_cols or 0))
    if max_tables_i <= 0 or max_rows_i <= 0 or max_cols_i <= 0:
        return []

    if cid == "mysql_catalog":
        return _extract_mysql_row_snapshots(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            config=config,
            max_tables=max_tables_i,
            max_rows=max_rows_i,
            max_cols=max_cols_i,
        )
    if cid == "sqlserver_catalog":
        return _extract_sqlserver_row_snapshots(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            config=config,
            max_tables=max_tables_i,
            max_rows=max_rows_i,
            max_cols=max_cols_i,
        )
    return []
