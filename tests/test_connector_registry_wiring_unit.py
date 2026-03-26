from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_check_db_connectivity_uses_connector_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors as connectors_module

    captured: dict[str, object] = {}

    class _FakeConnector:
        async def test_connection(self, config):  # noqa: ANN001, ANN201
            captured["config"] = config

            class _Result:
                ok = True
                message = "connected"
                details = {"latency_ms": 7.7, "read_only": True, "warnings": []}

            return _Result()

    monkeypatch.setattr(
        connectors_module.connector_class_registry,
        "get",
        lambda connector_id: _FakeConnector,  # noqa: ARG005
        raising=True,
    )

    cfg = {"host": "localhost", "database": "demo"}
    check, warnings = await connectors_module._check_db_connectivity_best_effort(
        connector_id="mysql_catalog",
        cfg=cfg,
    )
    assert captured["config"] == cfg
    assert check == {"ok": True, "latency_ms": 7.7, "read_only": True}
    assert warnings == []


@pytest.mark.asyncio
async def test_check_db_connectivity_returns_empty_when_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors as connectors_module
    from app.connectors.registry import ConnectorNotFoundError

    def _raise_not_found(connector_id: str):  # noqa: ANN001
        raise ConnectorNotFoundError(connector_id)

    monkeypatch.setattr(connectors_module.connector_class_registry, "get", _raise_not_found, raising=True)

    check, warnings = await connectors_module._check_db_connectivity_best_effort(
        connector_id="unknown_connector",
        cfg={"k": "v"},
    )
    assert check == {}
    assert warnings == []

