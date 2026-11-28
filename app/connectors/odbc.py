"""Select an installed SQL Server ODBC driver for connector defaults."""

_SQL_SERVER_DRIVER_PREFERENCE = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server")


def find_sqlserver_odbc_driver() -> str:
    import pyodbc

    installed = set(pyodbc.drivers())
    for driver in _SQL_SERVER_DRIVER_PREFERENCE:
        if driver in installed:
            return driver
    raise RuntimeError("No SQL Server ODBC driver found")
