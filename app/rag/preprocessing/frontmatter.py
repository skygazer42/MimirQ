"""
Markdown frontmatter extraction helpers.

The goal is metadata enrichment (title/tags/date/author) without adding heavy
YAML dependencies. Parsing is intentionally limited and safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_FRONTMATTER_START_RE = re.compile(r"^\ufeff?---\s*$")
_FRONTMATTER_END_RE = re.compile(r"^(---|\.\.\.)\s*$")
_KEY_VALUE_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_.-]{1,80})\s*:\s*(?P<val>.*)\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s*(?P<val>.+?)\s*$")
_H1_RE = re.compile(r"^\s*#\s+(?P<title>.+?)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```")


@dataclass(frozen=True)
class FrontmatterExtractResult:
    data: dict[str, Any]
    raw: str
    start_char: int
    end_char: int
    stripped_text: str
    changed: bool


def _coerce_scalar(value: str) -> Any:
    v = (value or "").strip()
    if not v:
        return ""

    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1].strip()

    low = v.lower()
    if low in {"true", "false"}:
        return low == "true"

    # Keep dates as strings; only coerce plain ints.
    if re.fullmatch(r"\d{1,18}", v or ""):
        try:
            return int(v)
        except Exception:
            return v

    return v


def _parse_inline_list(value: str) -> list[str] | None:
    v = (value or "").strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    inner = v[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip().strip("'\"") for p in inner.split(",")]
    out = [p for p in parts if p]
    return out


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
    raw = text or ""
    if not raw:
        return None

    lines = raw.splitlines(keepends=True)
    if not lines:
        return None

    # Frontmatter must be the very first non-empty line (BOM allowed).
    first = lines[0].rstrip("\r\n")
    if not _FRONTMATTER_START_RE.match(first.strip()):
        return None

    offset = 0
    end_char = None
    for i in range(1, len(lines)):
        offset += len(lines[i - 1])
        plain = lines[i].rstrip("\r\n").strip()
        if _FRONTMATTER_END_RE.match(plain):
            end_char = offset + len(lines[i])
            break

        if offset > max(0, int(max_chars or 0)):
            return None

    if end_char is None:
        return None

    fm_raw = raw[:end_char]
    body = raw[end_char:]
    stripped_text = body.lstrip("\r\n") if strip else raw

    # Parse limited YAML for common keys.
    data: dict[str, Any] = {}
    yaml_lines = fm_raw.splitlines()
    current_key: str | None = None
    current_list: list[str] | None = None

    for ln in yaml_lines[1:]:  # skip opening ---
        plain = ln.strip()
        if _FRONTMATTER_END_RE.match(plain):
            break
        if not plain or plain.startswith("#"):
            continue

        # Multi-line list items.
        m_item = _LIST_ITEM_RE.match(ln)
        if m_item and current_key and current_list is not None:
            val = (m_item.group("val") or "").strip().strip("'\"")
            if val:
                current_list.append(val)
            continue

        m = _KEY_VALUE_RE.match(ln)
        if not m:
            current_key = None
            current_list = None
            continue

        key = (m.group("key") or "").strip().casefold()
        val_raw = (m.group("val") or "").strip()

        inline_list = _parse_inline_list(val_raw)
        if inline_list is not None:
            data[key] = inline_list
            current_key = None
            current_list = None
            continue

        if val_raw == "":
            # Start a multi-line list.
            current_key = key
            current_list = []
            data[key] = current_list
            continue

        data[key] = _coerce_scalar(val_raw)
        current_key = None
        current_list = None

    return FrontmatterExtractResult(
        data=data,
        raw=fm_raw,
        start_char=0,
        end_char=int(end_char),
        stripped_text=stripped_text,
        changed=bool(strip and stripped_text != raw),
    )


def extract_markdown_title(text: str, *, max_lines: int = 60) -> str | None:
    """
    Extract a best-effort title from Markdown content:
    - prefers the first H1 heading (`# Title`)
    - skips fenced code blocks
    """
    raw = text or ""
    if not raw:
        return None

    in_code = False
    lines = raw.splitlines()
    for i, ln in enumerate(lines):
        if i >= max(1, int(max_lines or 0)):
            break
        if _CODE_FENCE_RE.match(ln):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _H1_RE.match(ln)
        if not m:
            continue
        title = (m.group("title") or "").strip()
        title = re.sub(r"\s+", " ", title)
        return title[:200] or None

    return None


__all__ = [
    "FrontmatterExtractResult",
    "extract_markdown_frontmatter",
    "extract_markdown_title",
]

