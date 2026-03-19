"""
Cross-page merge postprocessor.

Opt 2 (docs/plans/2026-03-19-document-parsing-optimization.md):
- Merge tables/lists that are split across adjacent pages.

This module is intentionally lightweight and deterministic:
- No PDF rendering
- Operates on parser-emitted per-page markdown texts
- Best-effort heuristics only (must never crash ingest/preview)
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, MutableMapping, Protocol, TypeVar, cast

_ORDERED_ITEM_RE = re.compile(r"^\s{0,6}(\d{1,4})[.)]\s+")


def _looks_like_table_row(line: str) -> bool:
    s = (line or "").strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _looks_like_table_sep(line: str) -> bool:
    s = (line or "").strip()
    if not _looks_like_table_row(s):
        return False
    inner = s.strip("|").strip()
    if not inner:
        return False
    # Separator rows are mostly dashes/colons/spaces/pipes.
    for ch in inner:
        if ch.isalnum():
            return False
        if ch not in "-:| ":
            return False
    return "---" in inner


def _table_col_count(line: str) -> int:
    s = (line or "").strip()
    if not _looks_like_table_row(s):
        return 0
    # "a|b|c" has 3 columns -> 4 pipes in markdown table row including boundaries.
    # We count non-empty column segments.
    parts = [p.strip() for p in s.strip("|").split("|")]
    parts = [p for p in parts if p != ""]
    return int(len(parts))


def _extract_trailing_block(lines: list[str], pred: Callable[[str], bool]) -> tuple[int, int] | None:
    """
    Return (start, end) indices of the trailing block (inclusive start, exclusive end),
    ignoring trailing blank lines.
    """
    if not lines:
        return None
    end = len(lines)
    # Strip trailing blanks.
    while end > 0 and not (lines[end - 1] or "").strip():
        end -= 1
    if end <= 0:
        return None

    start = end - 1
    if not pred(lines[start]):
        return None
    while start > 0 and pred(lines[start - 1]):
        start -= 1
    return int(start), int(end)


def _extract_leading_block(lines: list[str], pred: Callable[[str], bool]) -> tuple[int, int] | None:
    """
    Return (start, end) indices of the leading block (inclusive start, exclusive end),
    skipping leading blank lines.
    """
    if not lines:
        return None
    start = 0
    while start < len(lines) and not (lines[start] or "").strip():
        start += 1
    if start >= len(lines):
        return None
    if not pred(lines[start]):
        return None
    end = start + 1
    while end < len(lines) and pred(lines[end]):
        end += 1
    return int(start), int(end)


def _extract_ordered_num(line: str) -> int | None:
    m = _ORDERED_ITEM_RE.match(line or "")
    if not m:
        return None
    try:
        n = int(m.group(1))
    except Exception:
        return None
    if n <= 0:
        return None
    return int(n)


def _merge_table_blocks(prev_block: list[str], next_block: list[str]) -> list[str] | None:
    if not prev_block or not next_block:
        return None
    prev_cols = _table_col_count(prev_block[0])
    next_cols = _table_col_count(next_block[0])
    if prev_cols <= 0 or next_cols <= 0 or prev_cols != next_cols:
        return None

    # If the next block has a repeated header, drop it.
    if len(next_block) >= 2 and _looks_like_table_sep(next_block[1]):
        if len(prev_block) >= 2 and _looks_like_table_sep(prev_block[1]):
            # Compare header rows (trim whitespace to be tolerant).
            prev_header = (prev_block[0] or "").strip()
            next_header = (next_block[0] or "").strip()
            if prev_header == next_header:
                next_block = next_block[2:]
        else:
            # Next block looks like a standalone table with header; treat as not mergeable.
            return None
    else:
        # Next block has no separator row -> likely continuation (no header).
        pass

    if not next_block:
        return prev_block

    # Ensure single blank line between blocks isn't introduced here; table rows are consecutive.
    return [*prev_block, *next_block]


def _merge_ordered_list_blocks(prev_block: list[str], next_block: list[str]) -> list[str] | None:
    if not prev_block or not next_block:
        return None
    prev_nums = [_extract_ordered_num(line) for line in prev_block]
    next_nums = [_extract_ordered_num(line) for line in next_block]
    if any(n is None for n in prev_nums) or any(n is None for n in next_nums):
        return None

    prev_last = cast(int, prev_nums[-1])
    next_first = cast(int, next_nums[0])
    # Basic monotonicity: continuation should not reset.
    if next_first <= prev_last:
        return None
    return [*prev_block, *next_block]


def merge_cross_page_markdown_pages(pages: list[str]) -> tuple[list[str], dict[str, int]]:
    """
    Merge cross-page table/list continuations on a list of per-page markdown texts.
    """
    if not pages or len(pages) <= 1:
        return list(pages or []), {"tables_merged": 0, "lists_merged": 0, "pages_changed": 0}

    out = list(pages)
    tables_merged = 0
    lists_merged = 0
    pages_changed: set[int] = set()

    def _split(text: str) -> tuple[list[str], bool]:
        raw = str(text or "")
        return raw.splitlines(), raw.endswith("\n")

    def _join(lines: list[str], ends_with_newline: bool) -> str:
        txt = "\n".join(lines)
        if ends_with_newline and not txt.endswith("\n"):
            txt += "\n"
        return txt

    for i in range(len(out) - 1):
        prev_lines, prev_nl = _split(out[i])
        next_lines, next_nl = _split(out[i + 1])

        changed = False

        # 1) Table continuation: trailing table in prev + leading table in next.
        prev_tbl = _extract_trailing_block(prev_lines, _looks_like_table_row)
        next_tbl = _extract_leading_block(next_lines, _looks_like_table_row)
        if prev_tbl and next_tbl:
            ps, pe = prev_tbl
            ns, ne = next_tbl
            merged = _merge_table_blocks(prev_lines[ps:pe], next_lines[ns:ne])
            if merged is not None:
                prev_lines = [*prev_lines[:ps], *merged, *prev_lines[pe:]]
                next_lines = [*next_lines[:ns], *next_lines[ne:]]
                tables_merged += 1
                changed = True

        # 2) Ordered list continuation (only if table didn't already change boundary).
        if not changed:
            prev_lst = _extract_trailing_block(prev_lines, lambda line: _extract_ordered_num(line) is not None)
            next_lst = _extract_leading_block(next_lines, lambda line: _extract_ordered_num(line) is not None)
            if prev_lst and next_lst:
                ps, pe = prev_lst
                ns, ne = next_lst
                merged = _merge_ordered_list_blocks(prev_lines[ps:pe], next_lines[ns:ne])
                if merged is not None:
                    prev_lines = [*prev_lines[:ps], *merged, *prev_lines[pe:]]
                    next_lines = [*next_lines[:ns], *next_lines[ne:]]
                    lists_merged += 1
                    changed = True

        if changed:
            out[i] = _join(prev_lines, prev_nl)
            out[i + 1] = _join(next_lines, next_nl)
            pages_changed.add(i)
            pages_changed.add(i + 1)

    return out, {"tables_merged": int(tables_merged), "lists_merged": int(lists_merged), "pages_changed": int(len(pages_changed))}


class _PageLike(Protocol):
    page_content: str
    metadata: dict[str, Any]


TPage = TypeVar("TPage")


def _get_text(item: object) -> str:
    if isinstance(item, Mapping):
        return str(cast(Mapping[str, Any], item).get("page_content") or "")
    return str(getattr(item, "page_content", "") or "")


def _set_text(item: object, value: str) -> None:
    if isinstance(item, MutableMapping):
        cast(MutableMapping[str, Any], item)["page_content"] = str(value or "")
        return
    item.page_content = str(value or "")


def merge_cross_page_items(items: list[TPage]) -> tuple[list[TPage], dict[str, int]]:
    """
    Apply cross-page merge to a list of Document-like objects or dict-like items.

    Supported inputs:
    - langchain_core.documents.Document (has .page_content)
    - dict objects with {"page_content": "...", "metadata": {...}}
    """
    pages = [_get_text(it) for it in (items or [])]
    merged, stats = merge_cross_page_markdown_pages(pages)
    if len(merged) == len(items or []):
        for it, text in zip(items, merged, strict=False):
            _set_text(it, text)
    return items, stats


__all__ = [
    "merge_cross_page_items",
    "merge_cross_page_markdown_pages",
]
