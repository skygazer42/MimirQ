"""
Small, dependency-light filter helpers shared across modules.
"""

from __future__ import annotations

from typing import Any, Dict


def _get_meta_value(meta: Dict[str, Any], key: str) -> Any:
    """
    Return metadata value for a key, supporting dotted paths.

    Examples:
        meta = {"a": {"b": 1}}
        _get_meta_value(meta, "a.b") -> 1
    """
    if "." not in key:
        return meta.get(key)

    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _any_in(haystack: Any, needles: Any) -> bool:
    if not isinstance(needles, (list, tuple, set)):
        return False
    if isinstance(haystack, (list, tuple, set)):
        return any(v in needles for v in haystack)
    return haystack in needles


def _any_not_in(haystack: Any, needles: Any) -> bool:
    if not isinstance(needles, (list, tuple, set)):
        return False
    if isinstance(haystack, (list, tuple, set)):
        return all(v not in needles for v in haystack)
    return haystack not in needles


def _any_contains(haystack: Any, needle: Any) -> bool:
    if haystack is None:
        return False
    expected = str(needle).lower()
    if expected == "":
        # Empty substring would match everything; fail closed.
        return False
    if isinstance(haystack, (list, tuple, set)):
        return any(expected in str(v).lower() for v in haystack)
    return expected in str(haystack).lower()


def _any_startswith(haystack: Any, needle: Any) -> bool:
    if haystack is None:
        return False
    expected = str(needle).lower()
    if expected == "":
        # Empty prefix would match everything; fail closed.
        return False
    if isinstance(haystack, (list, tuple, set)):
        return any(str(v).lower().startswith(expected) for v in haystack)
    return str(haystack).lower().startswith(expected)


def _any_endswith(haystack: Any, needle: Any) -> bool:
    if haystack is None:
        return False
    expected = str(needle).lower()
    if expected == "":
        # Empty suffix would match everything; fail closed.
        return False
    if isinstance(haystack, (list, tuple, set)):
        return any(str(v).lower().endswith(expected) for v in haystack)
    return str(haystack).lower().endswith(expected)


def match_metadata_filter(meta: Dict[str, Any], filter_spec: Dict[str, Any]) -> bool:
    """
    Check if metadata matches the filter specification.

    Supported operators:
    - $eq: exact match (default if no operator)
    - $ne: not equal
    - $gt, $gte, $lt, $lte: comparison (numbers/strings)
    - $in: value in list (also supports list-valued metadata: any overlap)
    - $nin: value not in list (also supports list-valued metadata: no overlap)
    - $contains: string contains (case-insensitive; also supports list-valued metadata: any element contains)
    - $exists: key exists and is not None

    Key syntax:
    - Supports dotted paths for nested metadata, e.g. "document_user.tags".

    Examples:
        {"source": "doc.pdf"}  # exact match
        {"page": {"$gte": 10}}  # page >= 10
        {"source": {"$in": ["a.pdf", "b.pdf"]}}  # source in list
        {"title": {"$contains": "report"}}  # title contains "report"
        {"document_user.tags": {"$in": ["hr", "it"]}}  # tags overlap
    """
    if not filter_spec:
        return True
    if not isinstance(meta, dict):
        return False

    for key, condition in filter_spec.items():
        if not isinstance(key, str):
            return False

        # Boolean composition operators at the top-level.
        if key == "$and":
            if not isinstance(condition, list) or not condition:
                return False
            for item in condition:
                if not isinstance(item, dict):
                    return False
                if not match_metadata_filter(meta, item):
                    return False
            continue

        if key == "$or":
            if not isinstance(condition, list) or not condition:
                return False
            any_ok = False
            for item in condition:
                if not isinstance(item, dict):
                    return False
                if match_metadata_filter(meta, item):
                    any_ok = True
                    break
            if not any_ok:
                return False
            continue

        if key == "$not":
            if not isinstance(condition, dict) or not condition:
                return False
            if match_metadata_filter(meta, condition):
                return False
            continue

        if key.startswith("$"):
            # Unknown top-level operator: treat as non-match (safer than silently allowing).
            return False

        meta_value = _get_meta_value(meta, key)

        if isinstance(condition, dict):
            for op, expected in condition.items():
                if op == "$exists":
                    want = bool(expected)
                    if want and meta_value is None:
                        return False
                    if (not want) and meta_value is not None:
                        return False
                elif op == "$eq":
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
                    if not _any_in(meta_value, expected):
                        return False
                elif op == "$nin":
                    if not _any_not_in(meta_value, expected):
                        return False
                elif op == "$contains":
                    if not _any_contains(meta_value, expected):
                        return False
                elif op == "$startswith":
                    if not _any_startswith(meta_value, expected):
                        return False
                elif op == "$endswith":
                    if not _any_endswith(meta_value, expected):
                        return False
                else:
                    # Unknown operator: treat as non-match (safer than silently allowing).
                    return False
        else:
            if meta_value != condition:
                return False

    return True


__all__ = ["match_metadata_filter"]
