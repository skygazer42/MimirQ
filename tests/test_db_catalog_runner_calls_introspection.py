import uuid


def test_catalog_runner_calls_introspection(monkeypatch):
    from app.connectors.db import catalog_runner

    called = {"mysql": 0, "sqlserver": 0}

    def _fake_mysql(*_a, **_k):
        called["mysql"] += 1
        return []

    def _fake_sqlserver(*_a, **_k):
        called["sqlserver"] += 1
        return []

    monkeypatch.setattr(catalog_runner, "_introspect_mysql", _fake_mysql, raising=False)
    monkeypatch.setattr(catalog_runner, "_introspect_sqlserver", _fake_sqlserver, raising=False)

    catalog_runner.run_catalog_sync(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        connector_id="mysql_catalog",
        config={"host": "x"},
    )
    assert called["mysql"] == 1

