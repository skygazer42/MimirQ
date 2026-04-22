from __future__ import annotations

from typing import Any


def critique_synthetic_sample(sample: dict[str, Any]) -> dict[str, Any]:
    payload = dict(sample or {})
    critique = dict(payload.get("critique") or {})
    critique.setdefault("grounded", True)
    critique.setdefault("relevance", True)
    payload["critique"] = critique
    return payload
