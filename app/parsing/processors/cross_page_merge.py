from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

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
    lines = _non_empty_lines(text)
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
    lines = _non_empty_lines(text)
    if len(lines) >= 2 and _table_columns_from_markdown("\n".join(lines[:2])):
        return "\n".join(lines[2:]).strip()
    return (text or "").strip()


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

    prev_cols = _table_columns(prev_meta, prev.page_content or "")
    cur_cols = _table_columns(cur_meta, cur.page_content or "")
    if prev_cols and cur_cols and prev_cols != cur_cols:
        return False
    if prev_cols and not cur_cols:
        pass
    elif not prev_cols and cur_cols:
        pass
    elif not prev_cols and not cur_cols:
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


__all__ = ["merge_cross_page_documents"]
