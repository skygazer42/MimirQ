"""
Small, dependency-light filter helpers shared across modules.
"""


from typing import Any, Dict


def match_metadata_filter(meta: Dict[str, Any], filter_spec: Dict[str, Any]) -> bool:
    """
    Check if metadata matches the filter specification.

    Supported operators:
    - $eq: exact match (default if no operator)
    - $ne: not equal
    - $gt, $gte, $lt, $lte: comparison
    - $in: value in list
    - $nin: value not in list
    - $contains: string contains (case-insensitive)

    Examples:
        {"source": "doc.pdf"}  # exact match
        {"page": {"$gte": 10}}  # page >= 10
        {"source": {"$in": ["a.pdf", "b.pdf"]}}  # source in list
        {"title": {"$contains": "report"}}  # title contains "report"
    """
    if not filter_spec:
        return True
    if not isinstance(meta, dict):
        return False

    for key, condition in filter_spec.items():
        meta_value = meta.get(key)

        if isinstance(condition, dict):
            for op, expected in condition.items():
                if op == "$eq":
                    if meta_value != expected:
                        return False
                elif op == "$ne":
                    if meta_value == expected:
                        return False
                elif op == "$gt":
                    if meta_value is None or meta_value <= expected:
                        return False
                elif op == "$gte":
                    if meta_value is None or meta_value < expected:
                        return False
                elif op == "$lt":
                    if meta_value is None or meta_value >= expected:
                        return False
                elif op == "$lte":
                    if meta_value is None or meta_value > expected:
                        return False
                elif op == "$in":
                    if not isinstance(expected, (list, tuple, set)) or meta_value not in expected:
                        return False
                elif op == "$nin":
                    if isinstance(expected, (list, tuple, set)) and meta_value in expected:
                        return False
                elif op == "$contains":
                    if meta_value is None:
                        return False
                    if str(expected).lower() not in str(meta_value).lower():
                        return False
                else:
                    # Unknown operator: treat as non-match (safer than silently allowing).
                    return False
        else:
            if meta_value != condition:
                return False

    return True


__all__ = ["match_metadata_filter"]

