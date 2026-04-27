from __future__ import annotations

from typing import Any


def critique_synthetic_sample(sample: dict[str, Any]) -> dict[str, Any]:
    payload = dict(sample or {})
    critique = dict(payload.get("critique") or {})
    critique.setdefault("grounded", True)
    critique.setdefault("relevance", True)
    critique.setdefault("standalone", True)
    payload["critique"] = critique
    return payload


def should_keep_synthetic_sample(sample: dict[str, Any]) -> tuple[bool, list[str]]:
    critique = dict((sample or {}).get("critique") or {})
    failures: list[str] = []
    for key in ("grounded", "relevance", "standalone"):
        value = critique.get(key)
        if value is False:
            failures.append(key)
    return (not failures), failures


__all__ = ["critique_synthetic_sample", "should_keep_synthetic_sample"]
