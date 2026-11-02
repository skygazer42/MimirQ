"""Canonical merge and normalization rules for user-owned document metadata."""

from typing import Any


def _merge_user_metadata_patch(*, current: dict[str, Any], patch: dict[str, Any], replace: bool) -> dict[str, Any]:
    if replace:
        return dict(patch)

    next_user = dict(current)
    for key, value in patch.items():
        if value is None:
            next_user.pop(key, None)
        else:
            next_user[key] = value
    return next_user


def _normalize_user_metadata_tags(next_user: dict[str, Any], *, replace: bool) -> None:
    tags = next_user.get("tags")
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",")]
    if isinstance(tags, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            if not isinstance(raw, str):
                continue
            value = raw.strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(value[:64])
        next_user["tags"] = cleaned[:50]
    elif tags is None and "tags" in next_user and not replace:
        next_user.pop("tags", None)


def _normalize_user_metadata_notes(next_user: dict[str, Any]) -> None:
    notes = next_user.get("notes")
    if isinstance(notes, str):
        value = notes.strip()
        if not value:
            next_user.pop("notes", None)
        else:
            next_user["notes"] = value[:20_000]


def apply_user_metadata_patch(*, current: dict[str, Any], patch: dict[str, Any], replace: bool) -> dict[str, Any]:
    next_user = _merge_user_metadata_patch(current=current, patch=patch, replace=replace)
    _normalize_user_metadata_tags(next_user, replace=replace)
    _normalize_user_metadata_notes(next_user)
    return next_user
