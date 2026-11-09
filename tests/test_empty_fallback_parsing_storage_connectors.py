import pytest

from app.connectors.db.catalog_runner import _connect_mysql, _connect_sqlserver


@pytest.mark.parametrize("connect", [_connect_mysql, _connect_sqlserver])
def test_catalog_connection_requires_password_field_before_opening_database(monkeypatch, connect):
    import sqlalchemy

    def unexpected_engine(*args, **kwargs):
        raise AssertionError("incomplete credentials reached the database driver")

    monkeypatch.setattr(sqlalchemy, "create_engine", unexpected_engine)

    with pytest.raises(KeyError, match="password"):
        with connect({"host": "database.example", "database": "catalog", "username": "reader"}):
            pytest.fail("an incomplete catalog connection was opened")
