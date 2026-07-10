"""
Small, dependency-light filter helpers shared across modules.
"""


from typing import Any

from app.rag.pipeline_plugins.contracts import INDEXED_METADATA_KEY

_MAX_FILTER_DEPTH = 8
_MAX_FILTER_NODES = 200
_INDEXED_METADATA_KEY = INDEXED_METADATA_KEY
_MISSING = object()


def _get_meta_path_value(meta: dict[str, Any], key: str) -> Any:
    """Return metadata value for a key/path, or `_MISSING` when the path is absent."""
    if "." not in key:
        return meta[key] if key in meta else _MISSING

    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _get_meta_value(meta: dict[str, Any], key: str) -> Any:
    """
    Return metadata value for a key, supporting dotted paths.

    If the direct path is absent, schema-declared metadata field filters fall
    back to the schema-generated `_indexed_metadata` view. Explicit top-level
    metadata still wins, and callers can always target `_indexed_metadata.foo`
    directly.

    Examples:
        meta = {"a": {"b": 1}}
        _get_meta_value(meta, "a.b") -> 1
    """
    direct = _get_meta_path_value(meta, key)
    if direct is not _MISSING:
        return direct

    if key.startswith("$") or key.startswith("_"):
        return None

    indexed = meta.get(_INDEXED_METADATA_KEY)
    if isinstance(indexed, dict):
        fallback = _get_meta_path_value(indexed, key)
        if fallback is not _MISSING:
            return fallback

    return None


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


def match_metadata_filter(meta: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
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
    if not isinstance(meta, dict):
        return False
    # Only `None`/`{}` means "no filter". Other invalid shapes must fail closed.
    if filter_spec is None:
        return True
    if isinstance(filter_spec, dict) and not filter_spec:
        return True
    if not isinstance(filter_spec, dict):
        return False

    budget = [0]
    invalid = [False]

    def _match(meta0: dict[str, Any], spec0: dict[str, Any], *, depth: int) -> bool:
        if depth > _MAX_FILTER_DEPTH:
            invalid[0] = True
            return False
        if budget[0] > _MAX_FILTER_NODES:
            invalid[0] = True
            return False

        for key, condition in spec0.items():
            if not isinstance(key, str):
                return False

            budget[0] += 1
            if budget[0] > _MAX_FILTER_NODES:
                invalid[0] = True
                return False

            # Boolean composition operators at the top-level.
            if key == "$and":
                if not isinstance(condition, list) or not condition:
                    return False
                for item in condition:
                    if not isinstance(item, dict):
                        return False
                    if not _match(meta0, item, depth=depth + 1):
                        if invalid[0]:
                            return False
                        return False
                continue

            if key == "$or":
                if not isinstance(condition, list) or not condition:
                    return False
                any_ok = False
                for item in condition:
                    if not isinstance(item, dict):
                        return False
                    ok = _match(meta0, item, depth=depth + 1)
                    if invalid[0]:
                        return False
                    if ok:
                        any_ok = True
                        break
                if not any_ok:
                    return False
                continue

            if key == "$not":
                if not isinstance(condition, dict) or not condition:
                    return False
                ok = _match(meta0, condition, depth=depth + 1)
                if invalid[0]:
                    return False
                if ok:
                    return False
                continue

            if key.startswith("$"):
                # Unknown top-level operator: treat as non-match (safer than silently allowing).
                return False

            meta_value = _get_meta_value(meta0, key)

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
                        # Backward-compatible "allow missing" semantics:
                        # When callers include "" in the $in list, treat a missing metadata value
                        # (None) as equivalent to "" so older rows without this field are not
                        # incorrectly filtered out.
                        if meta_value is None and isinstance(expected, (list, tuple, set)) and "" in expected:
                            continue
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

    return _match(meta, filter_spec, depth=0)


def summarize_metadata_filter(
    filter_spec: Any,
    *,
    max_keys_sample: int = 10,
) -> dict[str, Any] | None:
    """
    Return a PII-safe summary of a metadata filter spec.

    This intentionally does NOT return any filter values. It only reports:
    - which keys are referenced
    - which operators are used and how often

    This is meant for debug/observability surfaces where raw filter specs must not leak.
    """
    if filter_spec is None:
        return None
    if isinstance(filter_spec, dict) and not filter_spec:
        return None
    if not isinstance(filter_spec, dict):
        return None

    keys: set[str] = set()
    ops: dict[str, int] = {}

    # Keep the traversal bounded so arbitrary user-provided filter specs can't blow up CPU.
    budget = [0]

    def _bump_op(op: str) -> None:
        if not op:
            return
        ops[op] = int(ops.get(op, 0) or 0) + 1

    def _visit(obj: Any, *, depth: int) -> None:
        if depth > _MAX_FILTER_DEPTH:
            return
        if budget[0] > _MAX_FILTER_NODES:
            return

        if isinstance(obj, dict):
            for k, v in obj.items():
                if budget[0] > _MAX_FILTER_NODES:
                    return
                budget[0] += 1

                if isinstance(k, str) and k.startswith("$"):
                    _bump_op(k)
                    # Boolean composition operators can nest more specs.
                    if k in {"$and", "$or"} and isinstance(v, list):
                        for item in v:
                            _visit(item, depth=depth + 1)
                    elif k == "$not" and isinstance(v, dict):
                        _visit(v, depth=depth + 1)
                    else:
                        # Other operators: do not traverse values (may contain user-provided data).
                        pass
                    continue

                if isinstance(k, str) and k:
                    keys.add(k)

                # Leaf condition: count operator keys under this field.
                if isinstance(v, dict):
                    for op in v.keys():
                        if isinstance(op, str) and op.startswith("$"):
                            _bump_op(op)

        elif isinstance(obj, list):
            for item in obj:
                _visit(item, depth=depth + 1)

    _visit(filter_spec, depth=0)

    keys_sorted = sorted(keys)
    max_keys_sample = max(0, int(max_keys_sample or 0))
    if max_keys_sample > 0:
        keys_sample = keys_sorted[:max_keys_sample]
    else:
        keys_sample = []

    # Keep ops deterministic and bounded.
    ops_sorted = dict(sorted(((str(k), int(v or 0)) for k, v in ops.items()), key=lambda x: x[0]))

    out: dict[str, Any] = {
        "keys_count": int(len(keys_sorted)),
        "keys_sample": keys_sample,
        "ops": ops_sorted,
    }
    return out


def apply_metadata_filter_with_stats(
    items: list[dict[str, Any]],
    filter_spec: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Apply `match_metadata_filter(...)` to a list of items and return (filtered, stats).

    Each item is expected to have a dict `metadata` field.
    Stats are PII-safe and do not include filter values.
    """
    summary = summarize_metadata_filter(filter_spec)
    if not items:
        return items, {"enabled": bool(summary), "matched": 0, "blocked": 0, "summary": summary}

    if filter_spec is None or (isinstance(filter_spec, dict) and not filter_spec):
        # No filter.
        return items, {"enabled": False, "matched": int(len(items)), "blocked": 0, "summary": None}

    if not isinstance(filter_spec, dict):
        # Invalid shape: fail closed and record a small, safe hint.
        return [], {"enabled": True, "invalid": True, "matched": 0, "blocked": int(len(items)), "summary": summary}

    matched = 0
    blocked = 0
    out: list[dict[str, Any]] = []
    for item in items:
        m = item.get("metadata") if isinstance(item, dict) else None
        if isinstance(m, dict) and match_metadata_filter(m, filter_spec):
            matched += 1
            out.append(item)
        else:
            blocked += 1

    return out, {
        "enabled": True,
        "matched": int(matched),
        "blocked": int(blocked),
        "summary": summary,
    }


__all__ = ["apply_metadata_filter_with_stats", "match_metadata_filter", "summarize_metadata_filter"]
