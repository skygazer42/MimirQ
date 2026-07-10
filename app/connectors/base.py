"""Connector base interface."""


from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.connectors.types import ConnectionTestResult, RawDocument


class ConnectorBase(ABC):
    """Base class for connector implementations."""

    @abstractmethod
    async def connect(self, config: dict[str, Any]) -> None:
        """Prepare connector runtime state."""

    @abstractmethod
    async def fetch_documents(self, **kwargs: Any) -> AsyncIterator[RawDocument]:
        """Yield raw documents from the source."""

    @abstractmethod
    async def test_connection(self, config: dict[str, Any]) -> ConnectionTestResult:
        """Run a best-effort connection probe."""

    @abstractmethod
    def supported_file_types(self) -> list[str]:
        """Return file types this connector can emit."""

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """Connector type identifier."""
