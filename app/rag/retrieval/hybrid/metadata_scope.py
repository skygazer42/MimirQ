"""Dataset identity parsing at the JSON metadata-filter boundary."""

from typing import Any
from uuid import UUID


def parse_dataset_scope_values(raw: Any) -> list[UUID]:
    values: list[Any]
    if isinstance(raw, dict):
        if "$eq" in raw:
            values = [raw.get("$eq")]
        elif "$in" in raw and isinstance(raw.get("$in"), list | tuple | set):
            values = list(raw.get("$in") or [])
        else:
            values = []
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        values = [raw]
    dataset_uuids: list[UUID] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            dataset_uuid = UUID(text)
        except (TypeError, ValueError, AttributeError):
            continue
        key = str(dataset_uuid)
        if key in seen:
            continue
        seen.add(key)
        dataset_uuids.append(dataset_uuid)
    return dataset_uuids


def collect_dataset_scope(metadata_filter: dict[str, Any] | None) -> list[UUID]:
    if not isinstance(metadata_filter, dict) or not metadata_filter:
        return []
    direct = parse_dataset_scope_values(metadata_filter.get("dataset_id"))
    if direct:
        return direct
    and_scope = _scope_from_and(metadata_filter.get("$and"))
    if and_scope:
        return and_scope
    return _scope_from_or(metadata_filter.get("$or"))


def _scope_from_and(parts: Any) -> list[UUID]:
    if not isinstance(parts, list):
        return []
    scoped: list[UUID] = []
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, dict):
            continue
        for dataset_uuid in collect_dataset_scope(part):
            key = str(dataset_uuid)
            if key in seen:
                continue
            seen.add(key)
            scoped.append(dataset_uuid)
    return scoped


def _scope_from_or(parts: Any) -> list[UUID]:
    if not isinstance(parts, list) or not parts:
        return []
    scoped_parts: list[list[UUID]] = []
    for part in parts:
        if not isinstance(part, dict):
            return []
        part_scope = collect_dataset_scope(part)
        if not part_scope:
            return []
        scoped_parts.append(part_scope)
    scoped: list[UUID] = []
    seen: set[str] = set()
    for part_scope in scoped_parts:
        for dataset_uuid in part_scope:
            key = str(dataset_uuid)
            if key in seen:
                continue
            seen.add(key)
            scoped.append(dataset_uuid)
    return scoped


def lexical_dataset_scope(metadata_filter: dict[str, Any] | None) -> tuple[list[UUID] | None, str | None]:
    dataset_uuids = collect_dataset_scope(metadata_filter)
    dataset_str = str(dataset_uuids[0]) if dataset_uuids else None
    return (dataset_uuids or None, dataset_str)
