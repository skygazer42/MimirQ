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


class _MetadataFilterMatcher:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        self.budget = 0
        self.invalid = False

    def _within_budget(self, depth: int) -> bool:
        if depth > _MAX_FILTER_DEPTH or self.budget > _MAX_FILTER_NODES:
            self.invalid = True
            return False
        return True

    def _consume_node(self) -> bool:
        self.budget += 1
        if self.budget > _MAX_FILTER_NODES:
            self.invalid = True
            return False
        return True

    def _match_and(self, condition: Any, *, depth: int) -> bool:
        if not isinstance(condition, list) or not condition:
            return False
        for item in condition:
            if not isinstance(item, dict) or not self.match(item, depth=depth + 1):
                return False
        return True

    def _match_or(self, condition: Any, *, depth: int) -> bool:
        if not isinstance(condition, list) or not condition:
            return False
        for item in condition:
            if not isinstance(item, dict):
                return False
            if self.match(item, depth=depth + 1):
                return True
            if self.invalid:
                return False
        return False

    def _match_not(self, condition: Any, *, depth: int) -> bool:
        if not isinstance(condition, dict) or not condition:
            return False
        matched = self.match(condition, depth=depth + 1)
        return False if self.invalid else not matched

    def _match_boolean(self, key: str, condition: Any, *, depth: int) -> bool:
        handlers = {
            "$and": self._match_and,
            "$or": self._match_or,
            "$not": self._match_not,
        }
        handler = handlers.get(key)
        return bool(handler and handler(condition, depth=depth))

    @staticmethod
    def _match_in(meta_value: Any, expected: Any) -> bool:
        if meta_value is None and isinstance(expected, (list, tuple, set)) and "" in expected:
            return True
        return _any_in(meta_value, expected)

    @staticmethod
    def _match_exists(meta_value: Any, expected: Any) -> bool:
        return (meta_value is not None) if bool(expected) else (meta_value is None)

    def _match_operator(self, meta_value: Any, operator: str, expected: Any) -> bool:
        handlers = {
            "$exists": self._match_exists,
            "$eq": lambda value, target: value == target,
            "$ne": lambda value, target: value != target,
            "$gt": lambda value, target: value is not None and value > target,
            "$gte": lambda value, target: value is not None and value >= target,
            "$lt": lambda value, target: value is not None and value < target,
            "$lte": lambda value, target: value is not None and value <= target,
            "$in": self._match_in,
            "$nin": _any_not_in,
            "$contains": _any_contains,
            "$startswith": _any_startswith,
            "$endswith": _any_endswith,
        }
        handler = handlers.get(operator)
        return bool(handler and handler(meta_value, expected))

    def _match_field(self, key: str, condition: Any) -> bool:
        meta_value = _get_meta_value(self.metadata, key)
        if not isinstance(condition, dict):
            return meta_value == condition
        for operator, expected in condition.items():
            if not self._match_operator(meta_value, operator, expected):
                return False
        return True

    def match(self, specification: dict[str, Any], *, depth: int) -> bool:
        if not self._within_budget(depth):
            return False
        for key, condition in specification.items():
            if not isinstance(key, str) or not self._consume_node():
                return False
            if key in {"$and", "$or", "$not"}:
                if not self._match_boolean(key, condition, depth=depth):
                    return False
                continue
            if key.startswith("$") or not self._match_field(key, condition):
                return False
        return True


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

    return _MetadataFilterMatcher(meta).match(filter_spec, depth=0)


class _MetadataFilterSummary:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.operators: dict[str, int] = {}
        self.budget = 0

    def _bump_operator(self, operator: str) -> None:
        if operator:
            self.operators[operator] = int(self.operators.get(operator, 0) or 0) + 1

    def _visit_operator(self, operator: str, value: Any, *, depth: int) -> None:
        self._bump_operator(operator)
        if operator in {"$and", "$or"} and isinstance(value, list):
            for item in value:
                self.visit(item, depth=depth + 1)
        elif operator == "$not" and isinstance(value, dict):
            self.visit(value, depth=depth + 1)

    def _count_leaf_operators(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        for operator in value:
            if isinstance(operator, str) and operator.startswith("$"):
                self._bump_operator(operator)

    def _visit_dict(self, value: dict[Any, Any], *, depth: int) -> None:
        for key, nested in value.items():
            if self.budget > _MAX_FILTER_NODES:
                return
            self.budget += 1
            if isinstance(key, str) and key.startswith("$"):
                self._visit_operator(key, nested, depth=depth)
                continue
            if isinstance(key, str) and key:
                self.keys.add(key)
            self._count_leaf_operators(nested)

    def visit(self, value: Any, *, depth: int) -> None:
        if depth > _MAX_FILTER_DEPTH or self.budget > _MAX_FILTER_NODES:
            return
        if isinstance(value, dict):
            self._visit_dict(value, depth=depth)
        elif isinstance(value, list):
            for item in value:
                self.visit(item, depth=depth + 1)


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

    summary = _MetadataFilterSummary()
    summary.visit(filter_spec, depth=0)
    keys_sorted = sorted(summary.keys)
    max_keys_sample = max(0, int(max_keys_sample or 0))
    if max_keys_sample > 0:
        keys_sample = keys_sorted[:max_keys_sample]
    else:
        keys_sample = []

    # Keep ops deterministic and bounded.
    ops_sorted = dict(
        sorted(
            ((str(key), int(value or 0)) for key, value in summary.operators.items()),
            key=lambda item: item[0],
        )
    )

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
