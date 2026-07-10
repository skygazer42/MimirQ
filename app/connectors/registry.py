"""Connector registry."""


from collections.abc import Callable

from app.connectors.base import ConnectorBase


class ConnectorNotFoundError(LookupError):
    """Raised when a connector type is not registered."""

    def __init__(self, connector_type: str) -> None:
        self.connector_type = str(connector_type or "").strip()
        super().__init__(f"connector not found: {self.connector_type or '<empty>'}")


class ConnectorRegistry:
    """Registry for connector classes."""

    def __init__(self) -> None:
        self._connectors: dict[str, type[ConnectorBase]] = {}

    def register(self, connector_type: str) -> Callable[[type[ConnectorBase]], type[ConnectorBase]]:
        key = str(connector_type or "").strip()
        if not key:
            raise ValueError("connector_type must be non-empty")

        def _decorator(connector_cls: type[ConnectorBase]) -> type[ConnectorBase]:
            self._connectors[key] = connector_cls
            return connector_cls

        return _decorator

    def get(self, connector_type: str) -> type[ConnectorBase]:
        key = str(connector_type or "").strip()
        try:
            return self._connectors[key]
        except KeyError as exc:
            raise ConnectorNotFoundError(key) from exc

    def list_types(self) -> list[str]:
        return sorted(self._connectors.keys())


registry = ConnectorRegistry()
