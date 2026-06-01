"""
DB catalog sync runner (stub).

This module wires connector runs to catalog ingestion logic. The first iteration is
intentionally dependency-light:
- No real DB network calls yet (introspection is stubbed)
- Provides deterministic control flow and a stable metrics structure
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


def _now() -> datetime:
    return datetime.now(UTC)


logger = logging.getLogger(__name__)


def _fingerprint(*, engine: str, db_name: str, schema_name: str | None, table_name: str) -> str:
    # Stable table identity for upsert. Keep it deterministic and do not include secrets.
    key = f"{str(engine or '').strip().lower()}|{str(db_name or '').strip()}|{str(schema_name or '').strip()}|{str(table_name or '').strip()}"
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


def _introspect_mysql(*, tenant_id: UUID, dataset_id: UUID, config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Stub: in a later iteration this will connect to MySQL and return table/column metadata.

    Returns a list of table dicts, each optionally containing `columns: [...]`.
    """
    _ = (tenant_id, dataset_id)
    database = str(config.get("database") or "").strip()
    if not database:
        return []

    include_tables = {str(t or "").strip().lower() for t in (config.get("include_tables") or []) if str(t or "").strip()}
    max_tables = int(config.get("max_tables") or 200)
    max_tables = max(1, min(max_tables, 2000))

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
            cols: list[dict[str, Any]] = []
            for c in col_rows or []:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                if not name:
                    continue
                try:
                    ordinal = int(c.get("ordinal") or 0)
                except (TypeError, ValueError, OverflowError):
                    ordinal = 0
                cols.append(
                    {
                        "ordinal": int(ordinal),
                        "name": name,
                        "data_type": (str(c.get("data_type") or "").strip() or None),
                        "nullable": (bool(c.get("nullable")) if c.get("nullable") is not None else None),
                        "comment": (str(c.get("comment") or "").strip() or None),
                    }
                )
                if len(cols) >= 5000:
                    break

            out.append(
                {
                    "db_name": (str(row.get("db_name") or database).strip() or database),
                    "schema_name": None,
                    "table_name": table_name,
                    "table_type": (str(row.get("table_type") or "table").strip().lower() or "table"),
                    "comment": (str(row.get("comment") or "").strip() or None),
                    "row_count_estimate": row.get("row_count_estimate"),
                    "columns": cols,
                }
            )
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

    include_schemas = {str(s or "").strip().lower() for s in (config.get("include_schemas") or []) if str(s or "").strip()}
    raw_tables = [str(t or "").strip() for t in (config.get("include_tables") or []) if str(t or "").strip()]
    include_fqn = set()
    include_names = set()
    for t in raw_tables:
        if "." in t:
            schema, name = t.split(".", 1)
            if schema.strip() and name.strip():
                include_fqn.add(f"{schema.strip().lower()}.{name.strip().lower()}")
        else:
            include_names.add(t.lower())

    max_tables = int(config.get("max_tables") or 200)
    max_tables = max(1, min(max_tables, 2000))

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
            if include_schemas and schema_name.lower() not in include_schemas:
                continue
            if include_fqn or include_names:
                fqn = f"{schema_name.lower()}.{table_name.lower()}" if schema_name else table_name.lower()
                if include_fqn and fqn not in include_fqn:
                    # If only fully-qualified names were provided, enforce them strictly.
                    continue
                if include_names and table_name.lower() not in include_names and fqn not in include_fqn:
                    continue

            col_rows = conn.execute(text(cols_sql), {"schema_name": schema_name, "table_name": table_name}).mappings().all()
            cols: list[dict[str, Any]] = []
            for c in col_rows or []:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                if not name:
                    continue
                try:
                    ordinal = int(c.get("ordinal") or 0)
                except (TypeError, ValueError, OverflowError):
                    ordinal = 0
                cols.append(
                    {
                        "ordinal": int(ordinal),
                        "name": name,
                        "data_type": (str(c.get("data_type") or "").strip() or None),
                        "nullable": (bool(c.get("nullable")) if c.get("nullable") is not None else None),
                        "comment": (str(c.get("comment") or "").strip() or None),
                    }
                )
                if len(cols) >= 5000:
                    break

            out.append(
                {
                    "db_name": (str(row.get("db_name") or database).strip() or database),
                    "schema_name": (schema_name or None),
                    "table_name": table_name,
                    "table_type": (str(row.get("table_type") or "table").strip().lower() or "table"),
                    "comment": (str(row.get("comment") or "").strip() or None),
                    "row_count_estimate": row.get("row_count_estimate"),
                    "columns": cols,
                }
            )
            if len(out) >= max_tables:
                break
    return out


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
    cid = str(connector_id or "").strip()
    if cid == "mysql_catalog":
        engine = "mysql"
        raw_tables = _introspect_mysql(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
    elif cid == "sqlserver_catalog":
        engine = "sqlserver"
        raw_tables = _introspect_sqlserver(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
    else:
        raise ValueError("unsupported_connector_id")

    seen_at = _now()
    items: list[tuple[CatalogTableInput, dict[str, Any], dict[str, Any]]] = []
    for t in raw_tables or []:
        if not isinstance(t, dict):
            continue
        db_name = str(t.get("db_name") or config.get("database") or "").strip()
        schema_name = str(t.get("schema_name") or "").strip() or None
        table_name = str(t.get("table_name") or "").strip()
        if not db_name or not table_name:
            continue

        table_type = str(t.get("table_type") or "table").strip().lower()
        if table_type != "view":
            table_type = "table"

        comment = (str(t.get("comment") or "").strip() or None)
        cols: list[CatalogColumnInput] = []
        for c in (t.get("columns") or []) if isinstance(t.get("columns"), list) else []:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            try:
                ordinal = int(c.get("ordinal") or 0)
            except (TypeError, ValueError, OverflowError):
                ordinal = 0
            cols.append(
                CatalogColumnInput(
                    ordinal=ordinal,
                    name=name,
                    data_type=(str(c.get("data_type") or "").strip() or None),
                    nullable=(bool(c.get("nullable")) if c.get("nullable") is not None else None),
                    comment=(str(c.get("comment") or "").strip() or None),
                )
            )
            if len(cols) >= 5000:
                break

        profile: dict[str, Any] = {}
        row_count_estimate = t.get("row_count_estimate")
        try:
            if row_count_estimate is not None:
                profile["row_count_estimate"] = int(row_count_estimate)
        except (TypeError, ValueError, OverflowError):
            # Best-effort; skip invalid values.
            pass
        sample_meta: dict[str, Any] = {"strategy": "catalog_sync", "seen_at": seen_at.isoformat()}

        items.append(
            (
                CatalogTableInput(
                engine=engine,
                db_name=db_name,
                schema_name=schema_name,
                table_name=table_name,
                table_type=table_type,
                comment=comment,
                fingerprint=_fingerprint(engine=engine, db_name=db_name, schema_name=schema_name, table_name=table_name),
                columns=cols,
                ),
                profile,
                sample_meta,
            )
        )
        if len(items) >= int(config.get("max_tables") or 200):
            break

    tables_upserted = 0
    columns_upserted = 0
    profiles_written = 0
    ent_hash = _entitlement_hash(engine=engine, config=dict(config or {}))
    if store is not None:
        profile_enabled = bool(config.get("profile_enabled")) if "profile_enabled" in (config or {}) else False
        for t, profile, sample_meta in items:
            table_id = store.upsert_table(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                connector_config_id=connector_config_id,
                table=t,
                seen_at=seen_at,
            )
            tables_upserted += 1
            columns_upserted += int(store.replace_columns(table_id=table_id, columns=t.columns))
            if profile_enabled:
                store.insert_profile_snapshot(
                    table_id=table_id,
                    entitlement_hash=ent_hash,
                    profile=dict(profile or {}),
                    sample_meta=dict(sample_meta or {}),
                )
                profiles_written += 1

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

    out: list[dict[str, Any]] = []
    if cid == "mysql_catalog":
        tables = _introspect_mysql(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
        with _connect_mysql(dict(config or {})) as conn:
            from sqlalchemy import text  # noqa: WPS433

            for t in tables:
                if len(out) >= max_tables_i:
                    break
                if not isinstance(t, dict):
                    continue
                table_name = str(t.get("table_name") or "").strip()
                if not table_name:
                    continue
                db_name = str(t.get("db_name") or config.get("database") or "").strip()
                source_table = f"{db_name}.{table_name}" if db_name else table_name
                sql = f"SELECT * FROM {_quote_mysql_ident(table_name)} LIMIT {max_rows_i}"
                try:
                    rows_raw = conn.execute(text(sql)).mappings().all()
                except Exception:  # noqa: BLE001
                    logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                    continue
                rows: list[dict[str, Any]] = []
                cols: list[str] = []
                if rows_raw:
                    cols = [str(k) for k in list(rows_raw[0].keys())[:max_cols_i]]
                if not cols:
                    cols_raw = t.get("columns")
                    if isinstance(cols_raw, list):
                        for c in cols_raw:
                            if isinstance(c, dict):
                                n = str(c.get("name") or "").strip()
                                if n:
                                    cols.append(n)
                            else:
                                n = str(c or "").strip()
                                if n:
                                    cols.append(n)
                            if len(cols) >= max_cols_i:
                                break
                for row in rows_raw:
                    if len(rows) >= max_rows_i:
                        break
                    rec: dict[str, Any] = {}
                    for col in cols:
                        rec[col] = _jsonify_row_value(row.get(col))
                    rec["__row_pk_hash"] = _row_hash(rec, exclude_keys=["__row_pk_hash"])
                    rows.append(rec)

                out.append(
                    {
                        "source_table": source_table,
                        "sheet_name": source_table,
                        "source_sync_token": _snapshot_token(source_table=source_table, rows=rows),
                        "source_pk_hash_col": "__row_pk_hash",
                        "columns": cols + (["__row_pk_hash"] if "__row_pk_hash" not in cols else []),
                        "rows": rows,
                    }
                )

    elif cid == "sqlserver_catalog":
        tables = _introspect_sqlserver(tenant_id=tenant_id, dataset_id=dataset_id, config=dict(config or {}))
        with _connect_sqlserver(dict(config or {})) as conn:
            from sqlalchemy import text  # noqa: WPS433

            for t in tables:
                if len(out) >= max_tables_i:
                    break
                if not isinstance(t, dict):
                    continue
                schema_name = str(t.get("schema_name") or "").strip()
                table_name = str(t.get("table_name") or "").strip()
                if not table_name:
                    continue
                db_name = str(t.get("db_name") or config.get("database") or "").strip()
                source_table = f"{db_name}.{schema_name}.{table_name}" if schema_name else f"{db_name}.{table_name}"
                table_ref = (
                    f"{_quote_sqlserver_ident(schema_name)}.{_quote_sqlserver_ident(table_name)}"
                    if schema_name
                    else _quote_sqlserver_ident(table_name)
                )
                sql = f"SELECT TOP ({max_rows_i}) * FROM {table_ref}"
                try:
                    rows_raw = conn.execute(text(sql)).mappings().all()
                except Exception:  # noqa: BLE001
                    logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                    continue
                rows: list[dict[str, Any]] = []
                cols: list[str] = []
                if rows_raw:
                    cols = [str(k) for k in list(rows_raw[0].keys())[:max_cols_i]]
                if not cols:
                    cols_raw = t.get("columns")
                    if isinstance(cols_raw, list):
                        for c in cols_raw:
                            if isinstance(c, dict):
                                n = str(c.get("name") or "").strip()
                                if n:
                                    cols.append(n)
                            else:
                                n = str(c or "").strip()
                                if n:
                                    cols.append(n)
                            if len(cols) >= max_cols_i:
                                break
                for row in rows_raw:
                    if len(rows) >= max_rows_i:
                        break
                    rec: dict[str, Any] = {}
                    for col in cols:
                        rec[col] = _jsonify_row_value(row.get(col))
                    rec["__row_pk_hash"] = _row_hash(rec, exclude_keys=["__row_pk_hash"])
                    rows.append(rec)

                out.append(
                    {
                        "source_table": source_table,
                        "sheet_name": source_table,
                        "source_sync_token": _snapshot_token(source_table=source_table, rows=rows),
                        "source_pk_hash_col": "__row_pk_hash",
                        "columns": cols + (["__row_pk_hash"] if "__row_pk_hash" not in cols else []),
                        "rows": rows,
                    }
                )

    return out
