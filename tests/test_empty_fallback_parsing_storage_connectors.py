import pytest

from app.connectors import catalog


@pytest.mark.parametrize("engine_name", ["mysql", "sqlserver"])
def test_catalog_connection_requires_password_field_before_opening_database(monkeypatch, engine_name):
    def unexpected_engine(*args, **kwargs):
        raise AssertionError("incomplete credentials reached the database driver")

    monkeypatch.setattr(catalog, "create_engine", unexpected_engine)

    with pytest.raises(KeyError, match="password"):
        with catalog._connect_catalog(
            engine_name=engine_name, config={"host": "database.example", "database": "catalog", "username": "reader"}
        ):
            pytest.fail("an incomplete catalog connection was opened")
