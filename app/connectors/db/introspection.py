"""
SQL generation helpers for DB catalog connectors.

Important:
- These helpers return *SELECT-only* statements (no semicolons) to make downstream
  validation easier and reduce injection risk.
- Callers should use parameter binding (e.g. SQLAlchemy text(...), params={...})
  rather than string interpolation.
"""



def mysql_list_tables_sql(*, database: str) -> str:
    # Use information_schema; `table_schema` is the database name in MySQL.
    # Named parameter is used so callers can bind safely.
    _ = database  # noqa: F841 (kept for signature symmetry / future use)
    return (
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


def mysql_list_columns_sql(*, database: str) -> str:
    _ = database  # noqa: F841 (kept for signature symmetry / future use)
    return (
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
        "CASE WHEN o.type = 'V' THEN 'view' ELSE 'table' END AS table_type, "
        "CASE WHEN o.type = 'U' THEN SUM(p.row_count) ELSE NULL END AS row_count_estimate "
        "FROM sys.objects o "
        "JOIN sys.schemas s ON s.schema_id = o.schema_id "
        "LEFT JOIN sys.dm_db_partition_stats p ON p.object_id = o.object_id AND p.index_id IN (0, 1) "
        "WHERE o.type IN ('U', 'V') "
        "GROUP BY s.name, o.name, o.type "
        "ORDER BY s.name, o.name"
    )


def sqlserver_list_columns_sql(*, database: str) -> str:
    _ = database  # noqa: F841 (kept for signature symmetry / future use)
    return (
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
