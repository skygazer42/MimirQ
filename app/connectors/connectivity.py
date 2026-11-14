"""Bounded database connectivity and read-only privilege checks."""

import time
from contextlib import closing
from typing import Any

from app.api.schemas.sources import (
    DbCatalogConnectorConfig,
    MySQLCatalogConnectorConfig,
    SQLServerCatalogConnectorConfig,
)
from app.core.async_bridge import run_blocking_in_thread
from app.services.connector_egress_policy import validate_db_connector_config

_WRITE_PRIVILEGES = (
    "all privileges",
    "insert",
    "update",
    "delete",
    "create",
    "drop",
    "alter",
    "grant option",
    "super",
    "owner",
    "control",
    "take ownership",
)


def _error_message(exc: Exception) -> str:
    message = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return (message or type(exc).__name__)[:200]


def _inspect_connection(
    connection: Any, *, started_at: float, permissions_sql: str, permission_limit: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with closing(connection.cursor()) as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    check: dict[str, Any] = {
        "ok": True,
        "latency_ms": round((time.time() - started_at) * 1000.0, 1),
        "read_only": None,
    }
    warnings: list[dict[str, Any]] = []
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(permissions_sql)
            permissions = cursor.fetchall()
        grants = "\n".join(row[0] for row in permissions[:permission_limit]).lower()
        has_write = any(privilege in grants for privilege in _WRITE_PRIVILEGES)
        check["read_only"] = not has_write
        if has_write:
            warnings.append(
                {
                    "code": "db_write_privileges_detected",
                    "message": "DB user appears to have write privileges; consider using a read-only account.",
                }
            )
    except Exception as exc:  # noqa: BLE001 - a successful probe may lack permission to inspect grants.
        warnings.append({"code": "db_read_only_check_error", "error": _error_message(exc)})
    return check, warnings


def _check_mysql_connection(config: MySQLCatalogConnectorConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import pymysql

    started_at = time.time()
    with closing(
        pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.username,
            password=config.password,
            database=config.database,
            connect_timeout=3,
            read_timeout=3,
            write_timeout=3,
            charset="utf8mb4",
        )
    ) as connection:
        return _inspect_connection(
            connection, started_at=started_at, permissions_sql="SHOW GRANTS", permission_limit=20
        )


def _check_sqlserver_connection(config: SQLServerCatalogConnectorConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import pyodbc

    installed = pyodbc.drivers()
    preferred = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
    driver = next((name for name in preferred if name in installed), None)
    if driver is None:
        if not installed:
            raise RuntimeError("No SQL Server ODBC driver found")
        driver = installed[-1]
    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={config.host},{config.port};"
        f"DATABASE={config.database};"
        f"UID={config.username};"
        f"PWD={config.password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    started_at = time.time()
    with closing(pyodbc.connect(connection_string, timeout=3)) as connection:
        # The connect timeout covers login; queries need their own driver timeout.
        connection.timeout = 3
        return _inspect_connection(
            connection,
            started_at=started_at,
            permissions_sql="SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE')",
            permission_limit=200,
        )


def _check_database_connection(config: DbCatalogConnectorConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # Connectivity failures are validation results; callers expose them as warnings.
    try:
        validate_db_connector_config(config)
        if isinstance(config, MySQLCatalogConnectorConfig):
            return _check_mysql_connection(config)
        return _check_sqlserver_connection(config)
    except Exception as exc:  # noqa: BLE001 - this is the connectivity-result boundary.
        error = _error_message(exc)
        return (
            {"ok": False, "latency_ms": None, "read_only": None, "error": error},
            [{"code": "db_connectivity_failed", "error": error}],
        )


async def check_database_connection(config: DbCatalogConnectorConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run synchronous database drivers outside the request event loop."""
    return await run_blocking_in_thread(_check_database_connection, config)
