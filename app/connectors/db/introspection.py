"""
SQL generation helpers for DB catalog connectors.

Important:
- These helpers return *SELECT-only* statements (no semicolons) to make downstream
  validation easier and reduce injection risk.
- Callers should use parameter binding (e.g. SQLAlchemy text(...), params={...})
  rather than string interpolation.
"""

from __future__ import annotations


def mysql_list_tables_sql(*, database: str) -> str:
    # Use information_schema; `table_schema` is the database name in MySQL.
    # Named parameter is used so callers can bind safely.
    _ = database  # noqa: F841 (kept for signature symmetry / future use)
    return (
        "SELECT "
        "table_schema AS db_name, "
        "table_name, "
        "CASE WHEN table_type = 'VIEW' THEN 'view' ELSE 'table' END AS table_type, "
        "table_comment AS comment "
        "FROM information_schema.tables "
        "WHERE table_schema = :database "
        "ORDER BY table_name"
    )


def sqlserver_list_tables_sql(*, database: str) -> str:
    # SQL Server introspection for the current DB connection.
    # `database` is kept as a bind param for future use (or DB_NAME() sanity checks),
    # but the server typically scopes the connection to a database already.
    _ = database  # noqa: F841 (kept for signature symmetry / future use)
    return (
        "SELECT "
        "DB_NAME() AS db_name, "
        "s.name AS schema_name, "
        "o.name AS table_name, "
        "CASE WHEN o.type = 'V' THEN 'view' ELSE 'table' END AS table_type "
        "FROM sys.objects o "
        "JOIN sys.schemas s ON s.schema_id = o.schema_id "
        "WHERE o.type IN ('U', 'V') "
        "ORDER BY s.name, o.name"
    )

