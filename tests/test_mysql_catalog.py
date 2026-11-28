from sqlalchemy import create_engine

from app.connectors import catalog


def test_mysql_catalog_reads_information_schema_table_name(monkeypatch):
    database = create_engine("sqlite://")
    with database.begin() as connection:
        # MySQL 8 preserves the casing of unaliased INFORMATION_SCHEMA column labels.
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS information_schema")
        connection.exec_driver_sql(
            "CREATE TABLE information_schema.tables "
            "(TABLE_SCHEMA TEXT, TABLE_NAME TEXT, TABLE_TYPE TEXT, TABLE_COMMENT TEXT, TABLE_ROWS INTEGER)"
        )
        connection.exec_driver_sql(
            "INSERT INTO information_schema.tables VALUES ('inventory', 'parts', 'BASE TABLE', '', 2)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE information_schema.columns (TABLE_SCHEMA TEXT, TABLE_NAME TEXT, ORDINAL_POSITION INTEGER, "
            "COLUMN_NAME TEXT, COLUMN_TYPE TEXT, IS_NULLABLE TEXT, COLUMN_COMMENT TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO information_schema.columns VALUES ('inventory', 'parts', 1, 'part_id', 'int', 'NO', '')"
        )
    monkeypatch.setattr(catalog, "_connect_catalog", lambda **_: database.connect())

    [table] = catalog._read_catalog(
        engine="mysql",
        config={"database": "inventory", "include_tables": ["parts"]},
    )
    assert table.table_name == "parts"
    assert table.row_count_estimate == 2
    assert [column.name for column in table.columns] == ["part_id"]
