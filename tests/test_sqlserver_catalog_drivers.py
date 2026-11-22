import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.api.schemas.sources import SQLServerCatalogConnectorConfig
from app.connectors import catalog, connectivity

ODBC_18 = "ODBC Driver 18 for SQL Server"
ODBC_17 = "ODBC Driver 17 for SQL Server"
LEGACY_SQL_SERVER = "SQL Server"
DBASE = "Microsoft Access dBASE Driver (*.dbf, *.ndx, *.mdx)"


@pytest.fixture
def sqlserver_config():
    return SQLServerCatalogConnectorConfig(host="database.example", database="catalog", username="reader", password="")


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ([LEGACY_SQL_SERVER, DBASE], LEGACY_SQL_SERVER),
        ([ODBC_17, ODBC_18, DBASE], ODBC_18),
        ([LEGACY_SQL_SERVER, ODBC_17, DBASE], ODBC_17),
    ],
)
def test_sqlserver_validation_and_catalog_share_encrypted_driver(monkeypatch, sqlserver_config, installed, expected):
    validation_calls = []
    catalog_calls = []
    connection = SimpleNamespace(close=lambda: None)

    def connect(connection_string, *, timeout):
        validation_calls.append((connection_string.split(";")[0], timeout, "Encrypt=yes;" in connection_string))
        return connection

    def create_engine(url, **kwargs):
        catalog_calls.append(dict(url.query))
        return SimpleNamespace(connect=lambda: nullcontext(connection), dispose=lambda: None)

    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(drivers=lambda: installed, connect=connect))
    monkeypatch.setattr(connectivity, "_inspect_connection", lambda *args, **kwargs: ({"ok": True}, []))
    monkeypatch.setattr(catalog, "create_engine", create_engine)

    result, _warnings = connectivity._check_sqlserver_connection(sqlserver_config)
    with catalog._connect_catalog(engine_name="sqlserver", config=sqlserver_config.model_dump()):
        pass

    assert result["ok"] is True
    assert validation_calls == [(f"DRIVER={{{expected}}}", 3, True)]
    assert connection.timeout == 3
    assert catalog_calls == [{"driver": expected, "Encrypt": "yes", "TrustServerCertificate": "yes"}]


def test_sqlserver_connector_rejects_unrelated_odbc_drivers(monkeypatch, sqlserver_config):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("an unrelated ODBC driver reached the connection boundary")

    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(drivers=lambda: [DBASE], connect=unexpected_connection))
    monkeypatch.setattr(catalog, "create_engine", unexpected_connection)
    with pytest.raises(RuntimeError, match="No SQL Server ODBC driver found"):
        connectivity._check_sqlserver_connection(sqlserver_config)
    with (
        pytest.raises(RuntimeError, match="No SQL Server ODBC driver found"),
        catalog._connect_catalog(engine_name="sqlserver", config=sqlserver_config.model_dump()),
    ):
        pass
