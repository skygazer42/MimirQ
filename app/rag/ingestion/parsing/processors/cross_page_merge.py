"""Merge metadata-aware document fragments or consecutive Markdown page texts."""

import re
from collections.abc import Iterable
from typing import Any

from langchain_core.documents import Document

from app.rag.ingestion.governance.markup.tables import is_markdown_table_separator, parse_markdown_table_row

_NUMBERED_LIST_RE = re.compile(r"^\s*(\d+)[.)]\s+")
_BULLET_LIST_RE = re.compile(r"^\s*([-*+])\s+")


def _last_page_number(meta: dict[str, Any]) -> int:
    merged_pages = meta.get("cross_page_merge_pages")
    if merged_pages:
        return merged_pages[-1]
    raw = meta.get("page")
    if raw is None:
        raw = meta.get("page_number")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return 0


def _non_empty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _table_columns_from_markdown(text: str) -> list[str]:
    lines = _table_lines_without_continuation_labels(text)
    if len(lines) < 2:
        return []
    header = parse_markdown_table_row(lines[0], min_columns=1)
    separator = parse_markdown_table_row(lines[1], min_columns=1)
    if header is None or separator is None:
        return []
    if len(header[1]) != len(separator[1]) or not is_markdown_table_separator(separator[1]):
        return []
    return header[1]


def _table_columns(meta: dict[str, Any], text: str) -> list[str]:
    raw = meta.get("table_columns")
    if isinstance(raw, list):
        cols = [col.strip() for col in raw]
        if cols:
            return cols
    return _table_columns_from_markdown(text)


def _table_header_present(meta: dict[str, Any], text: str) -> bool:
    raw = meta.get("table_header_present")
    if isinstance(raw, bool):
        return raw
    return bool(_table_columns_from_markdown(text))


def _is_table_segment(meta: dict[str, Any]) -> bool:
    doc_type = meta.get("doc_type_kwd")
    content_type = meta.get("content_type")
    if isinstance(doc_type, str):
        doc_type = doc_type.strip().lower()
    if isinstance(content_type, str):
        content_type = content_type.strip().lower()
    return doc_type == "table" or content_type == "table"


def _strip_redundant_table_header(text: str) -> str:
    lines = _table_lines_without_continuation_labels(text)
    if len(lines) >= 2 and _table_columns_from_markdown("\n".join(lines[:2])):
        return "\n".join(lines[2:]).strip()
    return "\n".join(lines).strip()


def _is_table_continuation_label(line: str) -> bool:
    text = " ".join(line.strip().lower().split())
    return (
        text in {"续表", "下表续页", "表格续页"}
        or text.startswith("续表")
        or (text.startswith(("table", "tbl", "表")) and "continued" in text)
    )


def _table_lines_without_continuation_labels(text: str) -> list[str]:
    lines = _non_empty_lines(text)
    while lines and _is_table_continuation_label(lines[0]):
        lines = lines[1:]
    return lines


def _has_leading_prose_before_table_rows(text: str) -> bool:
    lines = _table_lines_without_continuation_labels(text)
    if not lines:
        return False
    first_table_row = next((idx for idx, line in enumerate(lines) if _looks_like_table_row(line)), None)
    return first_table_row is not None and first_table_row > 0


def _can_merge_tables(prev: Document, cur: Document, *, max_page_gap: int) -> bool:
    prev_meta = prev.metadata
    cur_meta = cur.metadata
    if not (_is_table_segment(prev_meta) and _is_table_segment(cur_meta)):
        return False

    prev_page = _last_page_number(prev_meta)
    cur_page = _last_page_number(cur_meta)
    if prev_page <= 0 or cur_page <= 0:
        return False
    if not 1 <= cur_page - prev_page <= max_page_gap:
        return False
    if _has_leading_prose_before_table_rows(cur.page_content):
        return False

    prev_cols = _table_columns(prev_meta, prev.page_content)
    cur_cols = _table_columns(cur_meta, cur.page_content)
    if prev_cols and cur_cols and prev_cols != cur_cols:
        return False
    if not prev_cols and not cur_cols:
        prev_lines = prev.page_content.splitlines()
        cur_lines = cur.page_content.splitlines()
        prev_pipes = prev_lines[0].count("|") if prev_lines else 0
        cur_pipes = cur_lines[0].count("|") if cur_lines else 0
        if prev_pipes > 0 and cur_pipes > 0 and prev_pipes != cur_pipes:
            return False

    prev_truncated = bool(prev_meta.get("table_truncated") or prev_meta.get("truncated"))
    cur_header_missing = not _table_header_present(cur_meta, cur.page_content)
    cur_continued = bool(cur_meta.get("table_continued") or cur_meta.get("continued"))
    return prev_truncated or cur_header_missing or cur_continued


def _parse_numbered_list_line(line: str) -> int | None:
    match = _NUMBERED_LIST_RE.match(line)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_bullet_list_line(line: str) -> str | None:
    match = _BULLET_LIST_RE.match(line)
    if not match:
        return None
    return match.group(1)


def _can_merge_lists(prev: Document, cur: Document, *, max_page_gap: int) -> bool:
    prev_meta = prev.metadata
    cur_meta = cur.metadata
    prev_page = _last_page_number(prev_meta)
    cur_page = _last_page_number(cur_meta)
    if prev_page <= 0 or cur_page <= 0:
        return False
    if not 1 <= cur_page - prev_page <= max_page_gap:
        return False

    prev_lines = _non_empty_lines(prev.page_content)
    cur_lines = _non_empty_lines(cur.page_content)
    if not prev_lines or not cur_lines:
        return False

    prev_last = prev_lines[-1]
    cur_first = cur_lines[0]

    prev_num = _parse_numbered_list_line(prev_last)
    cur_num = _parse_numbered_list_line(cur_first)
    if prev_num is not None and cur_num is not None:
        return cur_num == prev_num + 1

    prev_bullet = _parse_bullet_list_line(prev_last)
    cur_bullet = _parse_bullet_list_line(cur_first)
    if prev_bullet and cur_bullet:
        return prev_bullet == cur_bullet

    return False


def _merge_metadata(prev_meta: dict[str, Any], cur_meta: dict[str, Any], *, kind: str) -> dict[str, Any]:
    merged = dict(prev_meta)
    pages = list(prev_meta.get("cross_page_merge_pages") or [])
    if not pages:
        prev_page = _last_page_number(prev_meta)
        if prev_page > 0:
            pages.append(prev_page)
    cur_pages = list(cur_meta.get("cross_page_merge_pages") or [])
    if not cur_pages:
        cur_page = _last_page_number(cur_meta)
        if cur_page > 0:
            cur_pages.append(cur_page)
    for page in cur_pages:
        if page not in pages:
            pages.append(page)

    merged["cross_page_merged"] = True
    merged["cross_page_merge_kind"] = kind
    merged["cross_page_merge_pages"] = pages
    merged["cross_page_merge_count"] = max(2, len(pages))
    if kind == "table":
        merged["table_truncated"] = False
        merged["truncated"] = False
    return merged


def _merge_pair(prev: Document, cur: Document, *, kind: str) -> Document:
    prev_meta = prev.metadata
    cur_meta = cur.metadata

    if kind == "table":
        cur_body = _strip_redundant_table_header(cur.page_content)
        parts = [(prev.page_content).rstrip()]
        if cur_body:
            parts.append(cur_body)
        merged_content = "\n".join([part for part in parts if part]).strip()
    else:
        parts = [(prev.page_content).rstrip(), (cur.page_content).lstrip()]
        merged_content = "\n".join([part for part in parts if part]).strip()

    return Document(
        page_content=merged_content,
        metadata=_merge_metadata(prev_meta, cur_meta, kind=kind),
        id=prev.id,
    )


def merge_cross_page_documents(
    documents: Iterable[Document],
    *,
    max_page_gap: int = 1,
    table_enabled: bool = True,
    list_enabled: bool = True,
) -> list[Document]:
    """Merge page-matched fragments; numbered lists must continue consecutively."""
    items = list(documents)
    if len(items) < 2:
        return items

    out: list[Document] = []
    pending = items[0]

    for current in items[1:]:
        if table_enabled and _can_merge_tables(pending, current, max_page_gap=max_page_gap):
            pending = _merge_pair(pending, current, kind="table")
            continue
        if list_enabled and _can_merge_lists(pending, current, max_page_gap=max_page_gap):
            pending = _merge_pair(pending, current, kind="list")
            continue
        out.append(pending)
        pending = current

    out.append(pending)
    return out


_ORDERED_ITEM_RE = re.compile(r"^\s{0,6}(\d{1,4})[.)]\s+")


def _looks_like_table_row(line: str) -> bool:
    s = (line).strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _looks_like_table_sep(line: str) -> bool:
    row = parse_markdown_table_row(line, min_columns=1)
    return row is not None and is_markdown_table_separator(row[1])


def _table_col_count(line: str) -> int:
    row = parse_markdown_table_row(line, min_columns=1)
    return len(row[1]) if row is not None else 0


def _extract_trailing_table_block(lines: list[str]) -> tuple[int, int] | None:
    """
    Return (start, end) indices of the trailing block (inclusive start, exclusive end),
    ignoring trailing blank lines.
    """
    if not lines:
        return None
    end = len(lines)
    # Strip trailing blanks.
    while end > 0 and not (lines[end - 1]).strip():
        end -= 1
    if end <= 0:
        return None

    start = end - 1
    if not _looks_like_table_row(lines[start]):
        return None
    while start > 0 and _looks_like_table_row(lines[start - 1]):
        start -= 1
    return start, end


def _extract_leading_table_block(lines: list[str]) -> tuple[int, int, int] | None:
    """
    Return the leading block start, first table row, and exclusive end.
    The block may include a continuation label before the first row.
    """
    if not lines:
        return None
    start = 0
    while start < len(lines) and not (lines[start]).strip():
        start += 1
    if start >= len(lines):
        return None

    cursor = start
    while cursor < len(lines) and _is_table_continuation_label(lines[cursor]):
        cursor += 1
        while cursor < len(lines) and not (lines[cursor]).strip():
            cursor += 1
    if cursor >= len(lines) or not _looks_like_table_row(lines[cursor]):
        return None

    end = cursor + 1
    while end < len(lines) and _looks_like_table_row(lines[end]):
        end += 1
    return start, cursor, end


def _extract_ordered_num(line: str) -> int | None:
    m = _ORDERED_ITEM_RE.match(line)
    if not m:
        return None
    n = int(m.group(1))
    if n <= 0:
        return None
    return n


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
            prev_header = (prev_block[0]).strip()
            next_header = (next_block[0]).strip()
            if prev_header != next_header:
                return None
            next_block = next_block[2:]
        else:
            # Next block looks like a standalone table with header; treat as not mergeable.
            return None

    if not next_block:
        return prev_block

    # Ensure single blank line between blocks isn't introduced here; table rows are consecutive.
    return [*prev_block, *next_block]


def _split_page_text(text: str) -> tuple[list[str], bool]:
    return text.splitlines(), text.endswith("\n")


def _join_page_text(lines: list[str], ends_with_newline: bool) -> str:
    text = "\n".join(lines)
    if ends_with_newline and not text.endswith("\n"):
        text += "\n"
    return text


def _merge_page_boundary(
    prev_lines: list[str],
    next_lines: list[str],
) -> tuple[list[str], list[str], int, int, bool]:
    previous_table = _extract_trailing_table_block(prev_lines)
    next_table = _extract_leading_table_block(next_lines)
    if previous_table and next_table:
        previous_start, previous_end = previous_table
        next_start, next_row_start, next_end = next_table
        merged = _merge_table_blocks(prev_lines[previous_start:previous_end], next_lines[next_row_start:next_end])
        if merged is not None:
            return (
                [*prev_lines[:previous_start], *merged, *prev_lines[previous_end:]],
                [*next_lines[:next_start], *next_lines[next_end:]],
                1,
                0,
                True,
            )

    previous_end = len(prev_lines)
    while previous_end > 0 and not prev_lines[previous_end - 1].strip():
        previous_end -= 1
    next_start = 0
    while next_start < len(next_lines) and not next_lines[next_start].strip():
        next_start += 1
    if previous_end == 0 or next_start == len(next_lines):
        return prev_lines, next_lines, 0, 0, False

    previous_number = _extract_ordered_num(prev_lines[previous_end - 1])
    next_number = _extract_ordered_num(next_lines[next_start])
    if previous_number is None or next_number is None or next_number <= previous_number:
        return prev_lines, next_lines, 0, 0, False

    previous_start = previous_end - 1
    while previous_start > 0 and _extract_ordered_num(prev_lines[previous_start - 1]) is not None:
        previous_start -= 1
    next_end = next_start + 1
    while next_end < len(next_lines) and _extract_ordered_num(next_lines[next_end]) is not None:
        next_end += 1

    merged = prev_lines[previous_start:previous_end] + next_lines[next_start:next_end]
    return (
        [*prev_lines[:previous_start], *merged, *prev_lines[previous_end:]],
        [*next_lines[:next_start], *next_lines[next_end:]],
        0,
        1,
        True,
    )


def merge_cross_page_markdown_pages(pages: list[str]) -> tuple[list[str], dict[str, int]]:
    """Stitch adjacent Markdown pages; ordered numbering must increase."""
    if len(pages) <= 1:
        return pages.copy(), {"tables_merged": 0, "lists_merged": 0, "pages_changed": 0}

    out = list(pages)
    tables_merged = 0
    lists_merged = 0
    pages_changed: set[int] = set()

    previous_index = 0
    for next_index in range(1, len(out)):
        prev_lines, prev_nl = _split_page_text(out[previous_index])
        next_lines, next_nl = _split_page_text(out[next_index])
        prev_lines, next_lines, table_delta, list_delta, changed = _merge_page_boundary(prev_lines, next_lines)
        if changed:
            tables_merged += table_delta
            lists_merged += list_delta
            out[previous_index] = _join_page_text(prev_lines, prev_nl)
            out[next_index] = _join_page_text(next_lines, next_nl)
            pages_changed.update((previous_index, next_index))
            if not out[next_index].strip():
                continue
        previous_index = next_index

    return out, {
        "tables_merged": tables_merged,
        "lists_merged": lists_merged,
        "pages_changed": len(pages_changed),
    }


def merge_cross_page_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Update parsed artifact dictionaries in place using Markdown-page rules."""
    pages = [item["page_content"] for item in items]
    merged, stats = merge_cross_page_markdown_pages(pages)
    for item, text in zip(items, merged, strict=True):
        item["page_content"] = text
    return items, stats


__all__ = [
    "merge_cross_page_documents",
    "merge_cross_page_items",
    "merge_cross_page_markdown_pages",
]
