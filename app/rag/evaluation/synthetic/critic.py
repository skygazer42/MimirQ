from typing import Any

_CRITIQUE_FIELDS = ("grounded", "relevance", "standalone")


def normalize_synthetic_sample_critique(sample: dict[str, Any]) -> dict[str, Any]:
    """Copy the sample and fill missing critique fields without judging its content."""
    payload = dict(sample or {})
    critique = dict(payload.get("critique") or {})
    for key in _CRITIQUE_FIELDS:
        critique.setdefault(key, None)
    payload["critique"] = critique
    return payload


def evaluate_synthetic_sample_acceptance(sample: dict[str, Any]) -> tuple[bool, list[str]]:
    critique = dict((sample or {}).get("critique") or {})
    failures: list[str] = []
    for key in _CRITIQUE_FIELDS:
        value = critique.get(key)
        if value is False:
            failures.append(key)
        elif value is not True:
            failures.append(f"{key}_unreviewed")
    return (not failures), failures


__all__ = ["normalize_synthetic_sample_critique", "evaluate_synthetic_sample_acceptance"]
