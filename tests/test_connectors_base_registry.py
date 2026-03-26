from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.connectors import (
    ConnectionTestResult,
    ConnectorBase,
    ConnectorNotFoundError,
    ConnectorRegistry,
    RawDocument,
)
from app.connectors.registry import registry as global_registry


@dataclass
class _DemoConnector(ConnectorBase):
    _connected: bool = False

    async def connect(self, config: dict) -> None:
        _ = config
        self._connected = True

    async def fetch_documents(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        yield RawDocument(source_ref="doc-1", content="hello world", metadata={"k": "v"})

    async def test_connection(self, config: dict) -> ConnectionTestResult:
        _ = config
        return ConnectionTestResult(ok=True, message="connected")

    def supported_file_types(self) -> list[str]:
        return ["txt", "md"]

    @property
    def connector_type(self) -> str:
        return "demo"


def test_connector_base_contract_can_be_implemented() -> None:
    connector = _DemoConnector()
    assert connector.connector_type == "demo"
    assert connector.supported_file_types() == ["txt", "md"]


def test_raw_document_defaults() -> None:
    doc = RawDocument(source_ref="id-1", content="sample")
    assert doc.metadata == {}
    assert doc.mime_type is None
    assert doc.title is None


def test_registry_register_and_get() -> None:
    registry = ConnectorRegistry()

    @registry.register("demo")
    class _Registered(_DemoConnector):
        pass

    cls = registry.get("demo")
    assert cls is _Registered


def test_registry_get_missing_raises() -> None:
    registry = ConnectorRegistry()
    with pytest.raises(ConnectorNotFoundError):
        registry.get("missing")


def test_db_catalog_connectors_are_registered_in_global_registry() -> None:
    from app.connectors import db as _db_connectors  # noqa: F401

    mysql_cls = global_registry.get("mysql_catalog")
    sqlserver_cls = global_registry.get("sqlserver_catalog")
    assert issubclass(mysql_cls, ConnectorBase)
    assert issubclass(sqlserver_cls, ConnectorBase)
