"""
Markdown frontmatter extraction helpers.

The goal is metadata enrichment (title/tags/date/author) without adding heavy
YAML dependencies. Parsing is intentionally limited and safe.
"""

import re
from dataclasses import dataclass
from typing import Any

_FRONTMATTER_START_RE = re.compile(r"^\ufeff?---\s*$")
_FRONTMATTER_END_RE = re.compile(r"^(---|\.\.\.)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```")

_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z0-9_.-]{1,80})\s*:\s*(.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(\S.*)$")
_H1_TITLE_RE = re.compile(r"^\s*#\s+(\S.*)$")


@dataclass(frozen=True)
class FrontmatterExtractResult:
    data: dict[str, Any]
    raw: str
    start_char: int
    end_char: int
    stripped_text: str
    changed: bool


def _coerce_scalar(value: str) -> Any:
    v = value.strip()
    if not v:
        return ""

    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1].strip()

    low = v.lower()
    if low in {"true", "false"}:
        return low == "true"

    # Keep dates as strings; only coerce plain ints.
    if v.isdigit() and 1 <= len(v) <= 18:
        try:
            return int(v)
        except ValueError:
            return v

    return v


def _parse_frontmatter_key_value(line: str) -> tuple[str, str] | None:
    match = _KEY_VALUE_RE.fullmatch(line.rstrip("\r\n"))
    if match is None:
        return None
    return match.group(1).casefold(), match.group(2).strip()


def _parse_frontmatter_list_item(line: str) -> str | None:
    match = _LIST_ITEM_RE.fullmatch(line.rstrip("\r\n"))
    return match.group(1).strip() if match is not None else None


def _parse_markdown_h1_title(line: str) -> str | None:
    match = _H1_TITLE_RE.fullmatch(line.rstrip("\r\n"))
    return match.group(1).strip() if match is not None else None


def _parse_inline_list(value: str) -> list[str] | None:
    v = value.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    inner = v[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip().strip("'\"") for p in inner.split(",")]
    out = [p for p in parts if p]
    return out


def normalize_frontmatter_tags(raw_tags: object) -> list[str] | None:
    if isinstance(raw_tags, str) and raw_tags.strip():
        parts = [part.strip() for part in raw_tags.replace(";", ",").split(",") if part.strip()]
        return parts[:50] or None
    if not isinstance(raw_tags, list):
        return None

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        value = str(item).strip() if item is not None else ""
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        cleaned.append(value[:64])
    return cleaned[:50] or None


def _find_frontmatter_end(lines: list[str], *, max_chars: int) -> int | None:
    end_char = len(lines[0])
    for line in lines[1:]:
        end_char += len(line)
        if end_char > max_chars:
            return None
        if _FRONTMATTER_END_RE.fullmatch(line.strip()):
            return end_char
    return None


def _parse_frontmatter_data(frontmatter_raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    for line in frontmatter_raw.splitlines()[1:]:
        plain = line.strip()
        if _FRONTMATTER_END_RE.match(plain):
            break
        if not plain or plain.startswith("#"):
            continue

        item_val = _parse_frontmatter_list_item(line)
        if item_val and current_key and current_list is not None:
            val = item_val.strip().strip("'\"")
            if val:
                current_list.append(val)
            continue

        kv = _parse_frontmatter_key_value(line)
        if not kv:
            current_key = None
            current_list = None
            continue

        key, val_raw = kv
        val_raw = val_raw.strip()
        inline_list = _parse_inline_list(val_raw)
        if inline_list is not None:
            data[key] = inline_list
            current_key = None
            current_list = None
            continue
        if val_raw == "":
            current_key = key
            current_list = []
            data[key] = current_list
            continue

        data[key] = _coerce_scalar(val_raw)
        current_key = None
        current_list = None
    return data


def extract_markdown_frontmatter(
    text: str,
    *,
    strip: bool = False,
    max_chars: int = 30_000,
) -> FrontmatterExtractResult | None:
    """
    Extract YAML frontmatter from Markdown text.

    Args:
        strip: remove the frontmatter block from output text
        max_chars: safety cap for the block size to parse
    """
    raw = text
    if not raw:
        return None

    lines = raw.splitlines(keepends=True)
    # Frontmatter must be the very first non-empty line (BOM allowed).
    first = lines[0].rstrip("\r\n")
    if not _FRONTMATTER_START_RE.match(first.strip()):
        return None

    end_char = _find_frontmatter_end(lines, max_chars=max_chars)
    if end_char is None:
        return None

    fm_raw = raw[:end_char]
    body = raw[end_char:]
    stripped_text = body.lstrip("\r\n") if strip else raw
    data = _parse_frontmatter_data(fm_raw)

    return FrontmatterExtractResult(
        data=data,
        raw=fm_raw,
        start_char=0,
        end_char=end_char,
        stripped_text=stripped_text,
        changed=bool(strip and stripped_text != raw),
    )


def extract_markdown_title(text: str, *, max_lines: int = 60) -> str | None:
    """
    Extract a best-effort title from Markdown content:
    - prefers the first H1 heading (`# Title`)
    - skips fenced code blocks
    """
    raw = text
    if not raw:
        return None

    in_code = False
    lines = raw.splitlines()
    for i, ln in enumerate(lines):
        if i >= max_lines:
            break
        if _CODE_FENCE_RE.match(ln):
            in_code = not in_code
            continue
        if in_code:
            continue
        title = _parse_markdown_h1_title(ln)
        if not title:
            continue
        title = " ".join(title.split())
        return title[:200]

    return None


__all__ = [
    "FrontmatterExtractResult",
    "extract_markdown_frontmatter",
    "extract_markdown_title",
    "normalize_frontmatter_tags",
]
