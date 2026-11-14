"""Lightweight JSON/text response parsing shared by model query clients."""

import json
import re
from typing import Any, Literal

from app.rag.core.code_fence import extract_first_code_fence


def _extract_string_items_from_lines(text: str, *, max_items: int = 12) -> list[str]:
    max_items = max(1, int(max_items or 0))
    items: list[str] = []
    seen: set[str] = set()
    for raw_line in (text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip common list prefixes: "- ", "* ", "1. ", "1) ", "• ".
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+\s*[.)]\s+", "", line)
        line = line.strip().strip('"').strip("'").strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        items.append(line)
        if len(items) >= max_items:
            break
    return items


def _json_candidates(raw: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    inner = extract_first_code_fence(raw, allowed_info_strings=("", "json"))
    if inner:
        candidates.append(("code_fence", inner))
    candidates.append(("raw", raw))

    obj_start = raw.find("{")
    obj_end = raw.rfind("}")
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        candidates.append(("first_last_brace", raw[obj_start : obj_end + 1].strip()))

    arr_start = raw.find("[")
    arr_end = raw.rfind("]")
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        candidates.append(("first_last_bracket", raw[arr_start : arr_end + 1].strip()))
    return candidates


def _wrapped_json_array(data: dict[str, Any], *, method: str) -> tuple[Any | None, dict[str, Any] | None]:
    for key in ("items", "queries", "data", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value, {"ok": True, "method": f"{method}:wrapped:{key}", "error": None}
    list_values = [value for value in data.values() if isinstance(value, list)]
    if len(list_values) == 1:
        return list_values[0], {"ok": True, "method": f"{method}:wrapped:single_list", "error": None}
    return None, None


def _accept_json_candidate(
    data: Any, *, expected: Literal["any", "array", "object"], method: str
) -> tuple[Any | None, dict[str, Any] | None, str | None]:
    if expected == "any":
        return data, {"ok": True, "method": method, "error": None}, None
    if expected == "object":
        if isinstance(data, dict):
            return data, {"ok": True, "method": method, "error": None}, None
        return None, None, f"expected_object_got_{type(data).__name__}"
    if isinstance(data, list):
        return data, {"ok": True, "method": method, "error": None}, None
    if isinstance(data, dict):
        wrapped, meta = _wrapped_json_array(data, method=method)
        if meta is not None:
            return wrapped, meta, None
    return None, None, f"expected_array_got_{type(data).__name__}"


def parse_json_from_text(
    text: str,
    *,
    expected: Literal["any", "array", "object"] = "any",
) -> tuple[Any | None, dict[str, Any]]:
    """
    Best-effort JSON parser for LLM outputs.

    Returns: (data, meta) where meta contains ok/method/error.
    """
    raw = (text).strip()
    if not raw:
        return None, {"ok": False, "method": None, "error": "empty"}

    last_error: str | None = None
    for method, candidate in _json_candidates(raw):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            accepted, meta, error = _accept_json_candidate(data, expected=expected, method=method)
            if meta is not None:
                return accepted, meta
            last_error = error
        except ValueError as exc:
            last_error = str(exc)[:200]
            continue

    if expected == "array":
        items = _extract_string_items_from_lines(raw, max_items=12)
        if items:
            return items, {"ok": True, "method": "lines", "error": None}

    return None, {"ok": False, "method": None, "error": last_error or "invalid_json"}
