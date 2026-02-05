from app.connectors.db.introspection import mysql_list_tables_sql, sqlserver_list_tables_sql


def test_mysql_introspection_sql_is_select_only():
    sql = mysql_list_tables_sql(database="demo")
    assert "select" in sql.lower()
    assert ";" not in sql


def test_sqlserver_introspection_sql_is_select_only():
    sql = sqlserver_list_tables_sql(database="demo")
    assert "select" in sql.lower()
    assert ";" not in sql

