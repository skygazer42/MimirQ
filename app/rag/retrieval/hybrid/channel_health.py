
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalChannelHealth:
    """Track per-query channel attempts, failures, and degraded status."""

    _attempted: set[str] = field(default_factory=set)
    _successful: set[str] = field(default_factory=set)
    _failures: dict[str, str] = field(default_factory=dict)

    def started(self, channel: str) -> None:
        self._attempted.add(channel)

    def succeeded(self, channel: str) -> None:
        self._attempted.add(channel)
        self._successful.add(channel)

    def failed(self, channel: str, error: Exception) -> None:
        self._attempted.add(channel)
        self._failures[channel] = type(error).__name__

    def publish(self, metrics: dict[str, Any]) -> None:
        reasons = [
            {"channel": channel, "error_type": error_type}
            for channel, error_type in sorted(self._failures.items())
        ]
        metrics["retrieval_degraded"] = bool(reasons)
        metrics["degraded_reasons"] = reasons
        metrics["attempted_channels"] = sorted(self._attempted)
        metrics["successful_channels"] = sorted(self._successful)
        metrics["all_retrieval_channels_failed"] = bool(
            self._attempted and not self._successful
        )
