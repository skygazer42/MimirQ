from __future__ import annotations

from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_runtime_migrations_bind_tenant_values_and_use_static_table_inputs() -> None:
    src = _source("app/core/migrations.py")

    assert "CAST(:default_tenant AS uuid)" in src
    assert "'{default_tenant}'" not in src
    assert "_tenant_id_migrations(\"documents\"" in src


def test_sqlite_table_store_uses_identifier_quote_helper() -> None:
    table_store = _source("app/services/table_store.py")
    service = _source("app/services/table_store_service.py")
    api = _source("app/api/v1/dataset_tables.py")

    assert "def quote_sqlite_ident" in table_store
    assert "replace('\"', '\"\"')" in table_store
    assert 'DROP TABLE IF EXISTS "{name}"' not in service
    assert 'DROP TABLE IF EXISTS "{sql_table}"' not in service
    assert 'PRAGMA table_info("{sql_table}")' not in api
    assert 'FROM "{sql_table}"' not in api
    assert "quote_sqlite_ident(" in service
    assert "quote_sqlite_ident(" in api


def test_external_catalog_and_checkpointer_dynamic_sql_are_constrained() -> None:
    catalog = _source("app/connectors/db/catalog_runner.py")
    checkpointer = _source("app/rag/checkpointer/sqlite.py")

    assert "def _quote_mysql_ident" in catalog
    assert "def _quote_sqlserver_ident" in catalog
    assert "SELECT * FROM {_quote_mysql_ident(table_name)}" in catalog
    assert "SELECT TOP ({max_rows_i}) * FROM {table_ref}" in catalog
    assert "re.match(r\"^[A-Za-z_]\\w*$\", table_prefix" in checkpointer
    assert "self.table_prefix = table_prefix" in checkpointer
