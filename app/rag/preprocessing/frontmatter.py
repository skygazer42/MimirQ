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

_YAML_KEY_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


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
    if v.isdigit() and 1 <= len(v) <= 18:
        try:
            return int(v)
        except Exception:
            return v

    return v


def _parse_frontmatter_key_value(line: str) -> tuple[str, str] | None:
    raw = (line or "").rstrip("\r\n")
    if not raw.strip():
        return None

    i = 0
    n = len(raw)
    while i < n and raw[i].isspace():
        i += 1

    key_start = i
    while i < n and raw[i] in _YAML_KEY_ALLOWED and (i - key_start) < 80:
        i += 1
    if i == key_start:
        return None
    key = raw[key_start:i]
    if not (1 <= len(key) <= 80):
        return None

    while i < n and raw[i].isspace():
        i += 1
    if i >= n or raw[i] != ":":
        return None
    i += 1

    val = raw[i:].strip()
    return key.strip().casefold(), val


def _parse_frontmatter_list_item(line: str) -> str | None:
    raw = (line or "").rstrip("\r\n")
    if not raw.strip():
        return None
    s = raw.lstrip()
    if not s.startswith("-"):
        return None
    i = 1
    if i >= len(s) or not s[i].isspace():
        return None
    while i < len(s) and s[i].isspace():
        i += 1
    val = s[i:].strip()
    return val or None


def _parse_markdown_h1_title(line: str) -> str | None:
    raw = (line or "").rstrip("\r\n")
    if not raw.strip():
        return None
    s = raw.lstrip()
    if not s.startswith("#"):
        return None
    if len(s) >= 2 and s[1] == "#":
        return None
    i = 1
    if i >= len(s) or not s[i].isspace():
        return None
    while i < len(s) and s[i].isspace():
        i += 1
    title = s[i:].strip()
    return title or None


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
        item_val = _parse_frontmatter_list_item(ln)
        if item_val and current_key and current_list is not None:
            val = item_val.strip().strip("'\"")
            if val:
                current_list.append(val)
            continue

        kv = _parse_frontmatter_key_value(ln)
        if not kv:
            current_key = None
            current_list = None
            continue

        key, val_raw = kv
        val_raw = (val_raw or "").strip()

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
        title = _parse_markdown_h1_title(ln)
        if not title:
            continue
        title = " ".join(title.split())
        return title[:200] or None

    return None


__all__ = [
    "FrontmatterExtractResult",
    "extract_markdown_frontmatter",
    "extract_markdown_title",
]
