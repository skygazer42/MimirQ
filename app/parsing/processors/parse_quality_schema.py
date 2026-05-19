from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ParseQualityGateDecision:
    grade: str
    needs_review: bool
    flags: dict[str, bool]
    actions: dict[str, bool]
    evidence: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": "mimirq.parse_quality_gate.v1",
            "grade": str(self.grade or "pass"),
            "needs_review": bool(self.needs_review),
            "flags": {str(k): bool(v) for k, v in dict(self.flags or {}).items()},
            "actions": {str(k): bool(v) for k, v in dict(self.actions or {}).items()},
            "evidence": _json_safe_mapping(self.evidence),
            "thresholds": _json_safe_mapping(self.thresholds),
            "warnings": [str(item) for item in (self.warnings or [])],
        }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _json_safe_mapping(value: Mapping[str, Any] | Mapping[Any, Any] | None) -> dict[str, Any]:
    return {str(k): _json_safe(v) for k, v in dict(value or {}).items()}


__all__ = ["ParseQualityGateDecision"]
