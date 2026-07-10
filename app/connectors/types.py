"""Shared connector abstraction types."""


from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawDocument:
    """Normalized raw document payload produced by connectors."""

    source_ref: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class ConnectionTestResult:
    """Connector connectivity probe result."""

    ok: bool
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
