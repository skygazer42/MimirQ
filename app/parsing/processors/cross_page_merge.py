
import re
from collections.abc import Iterable
from typing import Any, Callable, Mapping, MutableMapping, Protocol, TypeVar, cast

from langchain_core.documents import Document

_NUMBERED_LIST_RE = re.compile(r"^\s*(\d+)[.)]\s+")
_BULLET_LIST_RE = re.compile(r"^\s*([-*+])\s+")
def _page_number(meta: dict[str, Any]) -> int:
    raw = meta.get("page")
    if raw is None:
        raw = meta.get("page_number")
    try:
        return int(raw or 0)
    except Exception:
        return 0


def _non_empty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in (text or "").splitlines() if line.strip()]


def _table_columns_from_markdown(text: str) -> list[str]:
    lines = _table_lines_without_continuation_labels(text)
    if len(lines) < 2:
        return []
    header = lines[0]
    separator = lines[1]
    if "|" not in header or "|" not in separator:
        return []
    if "-" not in separator:
        return []
    cols = [cell.strip() for cell in header.strip().strip("|").split("|")]
    return [col for col in cols if col]


def _table_columns(meta: dict[str, Any], text: str) -> list[str]:
    raw = meta.get("table_columns")
    if isinstance(raw, list):
        cols = [str(col).strip() for col in raw if str(col).strip()]
        if cols:
            return cols
    return _table_columns_from_markdown(text)


def _table_header_present(meta: dict[str, Any], text: str) -> bool:
    raw = meta.get("table_header_present")
    if isinstance(raw, bool):
        return raw
    return bool(_table_columns_from_markdown(text))


def _is_table_segment(meta: dict[str, Any]) -> bool:
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    content_type = str(meta.get("content_type") or "").strip().lower()
    return doc_type == "table" or content_type == "table"


def _strip_redundant_table_header(text: str) -> str:
    lines = _table_lines_without_continuation_labels(text)
    if len(lines) >= 2 and _table_columns_from_markdown("\n".join(lines[:2])):
        return "\n".join(lines[2:]).strip()
    return "\n".join(lines).strip()


def _is_table_continuation_label(line: str) -> bool:
    text = " ".join(str(line or "").strip().lower().split())
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
    return first_table_row is not None and int(first_table_row) > 0


def _can_merge_tables(prev: Document, cur: Document, *, max_page_gap: int) -> bool:
    prev_meta = dict(prev.metadata or {})
    cur_meta = dict(cur.metadata or {})
    if not (_is_table_segment(prev_meta) and _is_table_segment(cur_meta)):
        return False

    prev_page = _page_number(prev_meta)
    cur_page = _page_number(cur_meta)
    if prev_page <= 0 or cur_page <= 0:
        return False
    if cur_page - prev_page < 1 or cur_page - prev_page > int(max_page_gap):
        return False
    if _has_leading_prose_before_table_rows(cur.page_content or ""):
        return False

    prev_cols = _table_columns(prev_meta, prev.page_content or "")
    cur_cols = _table_columns(cur_meta, cur.page_content or "")
    if prev_cols and cur_cols and prev_cols != cur_cols:
        return False
    if not prev_cols and not cur_cols:
        prev_pipes = (prev.page_content or "").splitlines()[0].count("|") if (prev.page_content or "").splitlines() else 0
        cur_pipes = (cur.page_content or "").splitlines()[0].count("|") if (cur.page_content or "").splitlines() else 0
        if prev_pipes > 0 and cur_pipes > 0 and prev_pipes != cur_pipes:
            return False

    prev_truncated = bool(prev_meta.get("table_truncated") or prev_meta.get("truncated"))
    cur_header_missing = not _table_header_present(cur_meta, cur.page_content or "")
    cur_continued = bool(cur_meta.get("table_continued") or cur_meta.get("continued"))
    return prev_truncated or cur_header_missing or cur_continued


def _parse_numbered_list_line(line: str) -> tuple[str, int] | None:
    match = _NUMBERED_LIST_RE.match(line or "")
    if not match:
        return None
    token = match.group(0)
    try:
        return token, int(match.group(1))
    except Exception:
        return None


def _parse_bullet_list_line(line: str) -> str | None:
    match = _BULLET_LIST_RE.match(line or "")
    if not match:
        return None
    return str(match.group(1))


def _can_merge_lists(prev: Document, cur: Document, *, max_page_gap: int) -> bool:
    prev_meta = dict(prev.metadata or {})
    cur_meta = dict(cur.metadata or {})
    prev_page = _page_number(prev_meta)
    cur_page = _page_number(cur_meta)
    if prev_page <= 0 or cur_page <= 0:
        return False
    if cur_page - prev_page < 1 or cur_page - prev_page > int(max_page_gap):
        return False

    prev_lines = _non_empty_lines(prev.page_content or "")
    cur_lines = _non_empty_lines(cur.page_content or "")
    if not prev_lines or not cur_lines:
        return False

    prev_last = prev_lines[-1]
    cur_first = cur_lines[0]

    prev_num = _parse_numbered_list_line(prev_last)
    cur_num = _parse_numbered_list_line(cur_first)
    if prev_num and cur_num:
        return cur_num[1] == prev_num[1] + 1

    prev_bullet = _parse_bullet_list_line(prev_last)
    cur_bullet = _parse_bullet_list_line(cur_first)
    if prev_bullet and cur_bullet:
        return prev_bullet == cur_bullet

    return False


def _merge_metadata(prev_meta: dict[str, Any], cur_meta: dict[str, Any], *, kind: str) -> dict[str, Any]:
    merged = dict(prev_meta)
    pages = list(prev_meta.get("cross_page_merge_pages") or [])
    if not pages:
        prev_page = _page_number(prev_meta)
        if prev_page > 0:
            pages.append(prev_page)
    cur_pages = list(cur_meta.get("cross_page_merge_pages") or [])
    if not cur_pages:
        cur_page = _page_number(cur_meta)
        if cur_page > 0:
            cur_pages.append(cur_page)
    for page in cur_pages:
        if page not in pages:
            pages.append(page)

    merged["cross_page_merged"] = True
    merged["cross_page_merge_kind"] = kind
    merged["cross_page_merge_pages"] = pages
    merged["cross_page_merge_count"] = int(max(2, len(pages)))
    if kind == "table":
        merged["table_truncated"] = False
        merged["truncated"] = False
    return merged


def _merge_pair(prev: Document, cur: Document, *, kind: str) -> Document:
    prev_meta = dict(prev.metadata or {})
    cur_meta = dict(cur.metadata or {})

    if kind == "table":
        cur_body = _strip_redundant_table_header(cur.page_content or "")
        parts = [(prev.page_content or "").rstrip()]
        if cur_body:
            parts.append(cur_body)
        merged_content = "\n".join([part for part in parts if part]).strip()
    else:
        parts = [(prev.page_content or "").rstrip(), (cur.page_content or "").lstrip()]
        merged_content = "\n".join([part for part in parts if part]).strip()

    return Document(
        page_content=merged_content,
        metadata=_merge_metadata(prev_meta, cur_meta, kind=kind),
        id=getattr(prev, "id", None),
    )


def merge_cross_page_documents(
    documents: Iterable[Document] | None,
    *,
    max_page_gap: int = 1,
    table_enabled: bool = True,
    list_enabled: bool = True,
) -> list[Document]:
    items = list(documents or [])
    if len(items) < 2:
        return items

    out: list[Document] = []
    pending = items[0]

    for current in items[1:]:
        if bool(table_enabled) and _can_merge_tables(pending, current, max_page_gap=max_page_gap):
            pending = _merge_pair(pending, current, kind="table")
            continue
        if bool(list_enabled) and _can_merge_lists(pending, current, max_page_gap=max_page_gap):
            pending = _merge_pair(pending, current, kind="list")
            continue
        out.append(pending)
        pending = current

    out.append(pending)
    return out


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
    if pred is _looks_like_table_row:
        body_start = start
        while body_start < len(lines) and _is_table_continuation_label(lines[body_start]):
            body_start += 1
        if body_start >= len(lines) or not pred(lines[body_start]):
            return None
        end = body_start + 1
        while end < len(lines) and pred(lines[end]):
            end += 1
        return int(start), int(end)
    if not pred(lines[start]):
        return None
    end = start + 1
    while end < len(lines) and pred(lines[end]):
        end += 1
    return int(start), int(end)


def _extract_leading_table_block(lines: list[str]) -> tuple[int, int] | None:
    """
    Return the leading table block while tolerating a continuation label such as
    "Table 1 (continued)" or "续表" ahead of the repeated header.
    """
    if not lines:
        return None
    start = 0
    while start < len(lines) and not (lines[start] or "").strip():
        start += 1
    if start >= len(lines):
        return None

    cursor = start
    while cursor < len(lines) and _is_table_continuation_label(lines[cursor]):
        cursor += 1
        while cursor < len(lines) and not (lines[cursor] or "").strip():
            cursor += 1
    if cursor >= len(lines) or not _looks_like_table_row(lines[cursor]):
        return None

    end = cursor + 1
    while end < len(lines) and _looks_like_table_row(lines[end]):
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
    while next_block and _is_table_continuation_label(next_block[0]):
        next_block = next_block[1:]
    if not next_block:
        return prev_block
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


def _split_page_text(text: str) -> tuple[list[str], bool]:
    raw = str(text or "")
    return raw.splitlines(), raw.endswith("\n")


def _join_page_text(lines: list[str], ends_with_newline: bool) -> str:
    text = "\n".join(lines)
    if ends_with_newline and not text.endswith("\n"):
        text += "\n"
    return text


def _merge_page_boundary(
    prev_lines: list[str],
    next_lines: list[str],
) -> tuple[list[str], list[str], int, int, bool]:
    prev_tbl = _extract_trailing_block(prev_lines, _looks_like_table_row)
    next_tbl = _extract_leading_table_block(next_lines)
    if prev_tbl and next_tbl:
        ps, pe = prev_tbl
        ns, ne = next_tbl
        merged = _merge_table_blocks(prev_lines[ps:pe], next_lines[ns:ne])
        if merged is not None:
            return [*prev_lines[:ps], *merged, *prev_lines[pe:]], [*next_lines[:ns], *next_lines[ne:]], 1, 0, True

    prev_lst = _extract_trailing_block(prev_lines, lambda line: _extract_ordered_num(line) is not None)
    next_lst = _extract_leading_block(next_lines, lambda line: _extract_ordered_num(line) is not None)
    if prev_lst and next_lst:
        ps, pe = prev_lst
        ns, ne = next_lst
        merged = _merge_ordered_list_blocks(prev_lines[ps:pe], next_lines[ns:ne])
        if merged is not None:
            return [*prev_lines[:ps], *merged, *prev_lines[pe:]], [*next_lines[:ns], *next_lines[ne:]], 0, 1, True
    return prev_lines, next_lines, 0, 0, False


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

    for i in range(len(out) - 1):
        prev_lines, prev_nl = _split_page_text(out[i])
        next_lines, next_nl = _split_page_text(out[i + 1])
        prev_lines, next_lines, table_delta, list_delta, changed = _merge_page_boundary(prev_lines, next_lines)
        if changed:
            tables_merged += table_delta
            lists_merged += list_delta
            out[i] = _join_page_text(prev_lines, prev_nl)
            out[i + 1] = _join_page_text(next_lines, next_nl)
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
    "merge_cross_page_documents",
    "merge_cross_page_items",
    "merge_cross_page_markdown_pages",
]
