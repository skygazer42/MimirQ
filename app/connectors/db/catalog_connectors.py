"""DB catalog connector implementations registered in ConnectorRegistry."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any

from app.api.schemas.connector import MySQLCatalogConnectorConfig, SQLServerCatalogConnectorConfig
from app.connectors.base import ConnectorBase
from app.connectors.registry import registry
from app.connectors.types import ConnectionTestResult, RawDocument
from app.services.connector_egress_policy import validate_db_connector_config

DbCatalogConfig = dict[str, Any] | MySQLCatalogConnectorConfig | SQLServerCatalogConnectorConfig


def _has_write_privileges_from_text(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return False
    tokens = (
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
    return any(token in lowered for token in tokens)


def _safe_error_str(exc: Exception) -> str:
    msg = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if not msg:
        msg = exc.__class__.__name__
    return msg[:200] if len(msg) > 200 else msg


def _extract_cfg(config: DbCatalogConfig) -> dict[str, Any]:
    if isinstance(config, dict):
        return dict(config)
    return config.model_dump(mode="json", exclude_none=True)


class _BaseCatalogConnector(ConnectorBase):
    _config: dict[str, Any]

    @property
    def connector_type(self) -> str:
        raise NotImplementedError

    async def connect(self, config: dict[str, Any]) -> None:
        self._config = dict(config)
        validate_db_connector_config(self._config)

    async def fetch_documents(self, **kwargs: Any) -> AsyncIterator[RawDocument]:
        if kwargs.get("__yield_placeholder__"):
            yield RawDocument(source_ref="unused", content="")

    def supported_file_types(self) -> list[str]:
        return ["json"]


@registry.register("mysql_catalog")
class MySQLCatalogConnector(_BaseCatalogConnector):
    @property
    def connector_type(self) -> str:
        return "mysql_catalog"

    async def test_connection(self, config: DbCatalogConfig) -> ConnectionTestResult:
        # PyMySQL connect/cursor APIs are synchronous, so keep them off the event loop.
        return await asyncio.to_thread(self._test_connection_sync, _extract_cfg(config))

    def _test_connection_sync(self, cfg: dict[str, Any]) -> ConnectionTestResult:
        warnings: list[dict[str, Any]] = []
        details: dict[str, Any] = {"latency_ms": None, "read_only": None}
        try:
            validate_db_connector_config(cfg)
            import pymysql

            t0 = time.time()
            conn = pymysql.connect(
                host=cfg["host"].strip(),
                port=int(cfg.get("port", 3306) or 3306),
                user=cfg["username"].strip(),
                password=cfg["password"],
                database=cfg["database"].strip(),
                connect_timeout=3,
                read_timeout=3,
                write_timeout=3,
                charset="utf8mb4",
            )
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                details["latency_ms"] = round((time.time() - t0) * 1000.0, 1)

                try:
                    with conn.cursor() as cur:
                        cur.execute("SHOW GRANTS")
                        rows = cur.fetchall() or []
                    grants = [row[0] for row in rows if row]
                    has_write = _has_write_privileges_from_text("\n".join(grants[:20]))
                    details["read_only"] = not has_write
                    if has_write:
                        warnings.append(
                            {
                                "code": "db_write_privileges_detected",
                                "message": (
                                    "DB user appears to have write privileges; consider using a read-only account."
                                ),
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    details["read_only"] = None
                    warnings.append({"code": "db_read_only_check_error", "error": _safe_error_str(exc)})
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
        except Exception as exc:  # noqa: BLE001
            details["error"] = _safe_error_str(exc)
            warnings.append({"code": "db_connectivity_failed", "error": _safe_error_str(exc)})
            details["warnings"] = warnings
            return ConnectionTestResult(ok=False, message=details["error"], details=details)

        details["warnings"] = warnings
        return ConnectionTestResult(ok=True, message="connected", details=details)


@registry.register("sqlserver_catalog")
class SQLServerCatalogConnector(_BaseCatalogConnector):
    @property
    def connector_type(self) -> str:
        return "sqlserver_catalog"

    async def test_connection(self, config: DbCatalogConfig) -> ConnectionTestResult:
        # pyodbc connect/cursor APIs are synchronous, so keep them off the event loop.
        return await asyncio.to_thread(self._test_connection_sync, _extract_cfg(config))

    def _test_connection_sync(self, cfg: dict[str, Any]) -> ConnectionTestResult:
        warnings: list[dict[str, Any]] = []
        details: dict[str, Any] = {"latency_ms": None, "read_only": None}
        try:
            validate_db_connector_config(cfg)
            import pyodbc

            preferred = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
            installed = list(pyodbc.drivers() or [])
            driver = next((item for item in preferred if item in installed), None)
            if not driver and installed:
                driver = installed[-1]
            if not driver:
                raise RuntimeError("No SQL Server ODBC driver found")

            host = cfg["host"].strip()
            port = int(cfg.get("port", 1433) or 1433)
            database = cfg["database"].strip()
            username = cfg["username"].strip()
            password = cfg["password"]

            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={host},{port};"
                f"DATABASE={database};"
                f"UID={username};"
                f"PWD={password};"
                "Encrypt=yes;"
                "TrustServerCertificate=yes;"
            )

            t0 = time.time()
            conn = pyodbc.connect(conn_str, timeout=3)
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                details["latency_ms"] = round((time.time() - t0) * 1000.0, 1)

                try:
                    cur = conn.cursor()
                    cur.execute("SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE')")
                    perms = [row[0] for row in (cur.fetchall() or []) if row and row[0]]
                    has_write = _has_write_privileges_from_text("\n".join(perms[:200]))
                    details["read_only"] = not has_write
                    if has_write:
                        warnings.append(
                            {
                                "code": "db_write_privileges_detected",
                                "message": (
                                    "DB user appears to have write privileges; consider using a read-only account."
                                ),
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    details["read_only"] = None
                    warnings.append({"code": "db_read_only_check_error", "error": _safe_error_str(exc)})
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
        except Exception as exc:  # noqa: BLE001
            details["error"] = _safe_error_str(exc)
            warnings.append({"code": "db_connectivity_failed", "error": _safe_error_str(exc)})
            details["warnings"] = warnings
            return ConnectionTestResult(ok=False, message=details["error"], details=details)

        details["warnings"] = warnings
        return ConnectionTestResult(ok=True, message="connected", details=details)
