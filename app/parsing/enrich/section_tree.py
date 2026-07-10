
import re
from collections.abc import Mapping, Sequence
from typing import Any

_CN_TOP_RE = re.compile(r"^\s*[一二三四五六七八九十百]+[、.．]")
_CN_SECOND_RE = re.compile(r"^\s*[（(][一二三四五六七八九十百]+[)）]")
_NUMERIC_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:[.)）]|\s+)")
_CHAPTER_RE = re.compile(r"^\s*chapter\s+\d+\b", re.IGNORECASE)
_SECTION_RE = re.compile(r"^\s*section\s+(\d+(?:\.\d+)*)\b", re.IGNORECASE)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _heading_level(element: Mapping[str, Any]) -> int | None:
    attrs = element.get("attributes")
    if isinstance(attrs, Mapping):
        explicit = _coerce_int(attrs.get("heading_level") or attrs.get("level"))
        if explicit is not None:
            return max(1, min(6, int(explicit)))

    text = str(element.get("text") or "").strip()
    if not text:
        return None
    if _CN_TOP_RE.match(text):
        return 1
    if _CN_SECOND_RE.match(text):
        return 2
    if _CHAPTER_RE.match(text):
        return 1
    section = _SECTION_RE.match(text)
    if section:
        token = str(section.group(1) or "")
        return max(2, min(6, token.count(".") + 1))
    numeric = _NUMERIC_RE.match(text)
    if numeric:
        token = str(numeric.group(1) or "")
        return max(1, min(6, token.count(".") + 1))
    if str(element.get("kind") or "").strip().lower() == "heading":
        return 2
    return None


def build_section_tree(elements: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    stack: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(elements or []):
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("kind") or "").strip().lower() != "heading":
            continue
        level = _heading_level(raw)
        if level is None:
            continue
        node = {
            "id": str(raw.get("id") or f"section:{index}"),
            "text": str(raw.get("text") or "").strip(),
            "level": int(level),
            "page": raw.get("page"),
            "bbox": raw.get("bbox") if isinstance(raw.get("bbox"), Mapping) else None,
            "source_element_id": raw.get("source_element_id"),
            "parent_id": None,
        }
        while stack and int(stack[-1].get("level") or 0) >= int(level):
            stack.pop()
        if stack:
            node["parent_id"] = stack[-1].get("id")
        out.append({key: value for key, value in node.items() if key == "parent_id" or value not in (None, "", [], {})})
        stack.append(out[-1])
    return out


def add_section_paths(elements: Sequence[Mapping[str, Any]] | None, section_tree: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if not elements:
        return []
    by_id = {str(node.get("id") or ""): dict(node) for node in (section_tree or []) if isinstance(node, Mapping)}
    path_by_id: dict[str, list[str]] = {}
    for node_id, node in by_id.items():
        path: list[str] = []
        cursor = node
        seen: set[str] = set()
        while cursor and str(cursor.get("id") or "") not in seen:
            seen.add(str(cursor.get("id") or ""))
            text = str(cursor.get("text") or "").strip()
            if text:
                path.append(text)
            parent_id = str(cursor.get("parent_id") or "")
            cursor = by_id.get(parent_id) if parent_id else {}
        path_by_id[node_id] = list(reversed(path))

    current_path: list[str] = []
    out: list[dict[str, Any]] = []
    for raw in elements or []:
        item = dict(raw)
        node_id = str(item.get("id") or "")
        if node_id in path_by_id:
            current_path = path_by_id[node_id]
        if current_path:
            attrs = dict(item.get("attributes") or {})
            attrs["header_path"] = list(current_path)
            item["attributes"] = attrs
        out.append(item)
    return out


__all__ = ["add_section_paths", "build_section_tree"]
