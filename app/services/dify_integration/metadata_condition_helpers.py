
from typing import Any


class MetadataConditionValidationError(ValueError):
    """Raised when a Dify metadata condition payload cannot be converted."""


def metadata_filter_field_names(metadata_filter: Any) -> set[str]:
    if not isinstance(metadata_filter, dict):
        return set()
    out: set[str] = set()
    for key, value in metadata_filter.items():
        name = str(key or "").strip()
        if not name:
            continue
        if name in {"$and", "$or"}:
            values = value if isinstance(value, list | tuple | set) else [value]
            for item in values:
                out.update(metadata_filter_field_names(item))
            continue
        if name == "$not":
            out.update(metadata_filter_field_names(value))
            continue
        if name.startswith("$"):
            continue
        out.add(name)
    return out


def validate_metadata_filter_fields(metadata_filter: dict[str, Any], *, allowed_fields: set[str] | None) -> None:
    if allowed_fields is None:
        return
    disallowed = sorted(
        field_name for field_name in metadata_filter_field_names(metadata_filter) if field_name not in allowed_fields
    )
    if disallowed:
        raise MetadataConditionValidationError(
            f"Dify metadata filter field is not allowed by plugin retrieval_policy: {disallowed[0]}"
        )


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def dify_metadata_condition_item_to_filter(condition: dict[str, Any]) -> dict[str, Any]:
    name = str(condition.get("name") or "").strip()
    op = str(condition.get("comparison_operator") or "").strip().lower()
    value = condition.get("value")
    if not name or not op:
        raise MetadataConditionValidationError("Invalid Dify metadata_condition condition")

    if op == "contains":
        return {name: {"$contains": value}}
    if op == "not contains":
        return {"$not": {name: {"$contains": value}}}
    if op == "start with":
        return {name: {"$startswith": value}}
    if op == "end with":
        return {name: {"$endswith": value}}
    if op in {"is", "="}:
        return {name: {"$eq": value}}
    if op in {"is not", "≠", "!="}:
        return {name: {"$ne": value}}
    if op == "in":
        return {name: {"$in": as_list(value)}}
    if op == "not in":
        return {name: {"$nin": as_list(value)}}
    if op == "empty":
        return {"$or": [{name: {"$exists": False}}, {name: {"$eq": ""}}, {name: {"$eq": []}}]}
    if op == "not empty":
        return {
            "$and": [
                {name: {"$exists": True}},
                {"$not": {name: {"$eq": ""}}},
                {"$not": {name: {"$eq": []}}},
            ]
        }
    if op in {">", "after"}:
        return {name: {"$gt": value}}
    if op in {"<", "before"}:
        return {name: {"$lt": value}}
    if op in {"≥", ">="}:
        return {name: {"$gte": value}}
    if op in {"≤", "<="}:
        return {name: {"$lte": value}}

    raise MetadataConditionValidationError(f"Unsupported Dify metadata comparison operator: {op}")


def metadata_condition_to_filter(
    condition: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(condition, dict) or not condition:
        return None
    for key in ("metadata_filter", "filter"):
        value = condition.get(key)
        if isinstance(value, dict) and value:
            validate_metadata_filter_fields(value, allowed_fields=allowed_fields)
            return value

    raw_conditions = condition.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        return None

    logical_operator = str(condition.get("logical_operator") or "and").strip().lower()
    if logical_operator not in {"and", "or"}:
        raise MetadataConditionValidationError("Invalid Dify metadata_condition logical_operator")

    parts: list[dict[str, Any]] = []
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, dict):
            raise MetadataConditionValidationError("Invalid Dify metadata_condition condition")
        parts.append(dify_metadata_condition_item_to_filter(raw_condition))

    if not parts:
        return None
    metadata_filter = parts[0] if len(parts) == 1 else {"$or" if logical_operator == "or" else "$and": parts}
    validate_metadata_filter_fields(metadata_filter, allowed_fields=allowed_fields)
    return metadata_filter
