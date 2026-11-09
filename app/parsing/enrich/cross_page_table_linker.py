from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.documents import Document

from app.parsing.enrich.table_cell_schema import TableCell, TableExtraction
from app.parsing.enrich.table_renderers import render_table_csv, render_table_html, render_table_markdown
from app.parsing.utils.scalars import coerce_int as _coerce_int


def _is_table_doc(doc: Document) -> bool:
    meta = dict(doc.metadata or {})
    hint = meta.get("content_type") or meta.get("element_kind") or meta.get("doc_type_kwd")
    return isinstance(hint, str) and hint.lower() == "table"


def _bbox(meta: Mapping[str, Any]) -> Mapping[str, Any]:
    value = meta.get("element_bbox") or meta.get("source_bbox") or meta.get("bbox")
    return value if isinstance(value, Mapping) else {}


def _page(meta: Mapping[str, Any]) -> int | None:
    return _coerce_int(meta.get("element_page") or meta.get("source_page") or meta.get("page"))


def _columns(meta: Mapping[str, Any]) -> list[str]:
    raw = meta.get("table_columns")
    if not isinstance(raw, list):
        extraction = meta.get("table_extraction")
        if isinstance(extraction, Mapping):
            raw = extraction.get("columns")
    return [item.strip().casefold() for item in (raw if isinstance(raw, list) else [])]


def _rows(meta: Mapping[str, Any]) -> list[list[str]]:
    extraction = meta.get("table_extraction")
    if isinstance(extraction, Mapping) and isinstance(extraction.get("rows"), list):
        rows = []
        for raw in extraction.get("rows") or []:
            if isinstance(raw, list):
                rows.append([cell.strip() for cell in raw])
        return rows
    return []


def _near_page_bottom(meta: Mapping[str, Any]) -> bool:
    bbox = _bbox(meta)
    y1 = _coerce_int(bbox.get("y1"))
    return y1 is not None and y1 >= 720


def _near_page_top(meta: Mapping[str, Any]) -> bool:
    bbox = _bbox(meta)
    y0 = _coerce_int(bbox.get("y0"))
    return y0 is not None and y0 <= 180


def _should_merge(left: Document, right: Document) -> bool:
    left_meta = dict(left.metadata or {})
    right_meta = dict(right.metadata or {})
    left_page = _page(left_meta)
    right_page = _page(right_meta)
    if left_page is None or right_page is None or right_page != left_page + 1:
        return False
    if _columns(left_meta) != _columns(right_meta) or not _columns(left_meta):
        return False
    right_text = str(right.page_content)
    has_continuation_hint = any(token in right_text for token in ("续表", "continued", "Continuation"))
    return (_near_page_bottom(left_meta) and _near_page_top(right_meta)) or has_continuation_hint


def _make_extraction(meta: Mapping[str, Any], rows: list[list[str]]) -> TableExtraction:
    source_id = meta.get("source_element_id")
    if source_id is None:
        source_id = meta.get("element_id")
    columns = [
        item.strip()
        for item in (meta.get("table_columns") if isinstance(meta.get("table_columns"), list) else [])
    ]
    if not columns:
        extraction = meta.get("table_extraction")
        if isinstance(extraction, Mapping) and isinstance(extraction.get("columns"), list):
            columns = [item.strip() for item in extraction.get("columns") or []]
    cells = [TableCell(row_index=0, col_index=i, text=col, is_header=True) for i, col in enumerate(columns)]
    for row_index, row in enumerate(rows, start=1):
        for col_index, text in enumerate(row[: len(columns)]):
            cells.append(TableCell(row_index=row_index, col_index=col_index, text=text, is_header=False))
    return TableExtraction(
        columns=columns,
        rows=rows,
        cells=cells,
        page=_page(meta),
        bbox=_bbox(meta),
        source_element_id=str(source_id) if source_id is not None else None,
        header_rows=1,
        metadata={"source": "cross_page_table_linker"},
    )


def _merge_group(group: list[Document]) -> Document:
    first = group[0]
    meta = dict(first.metadata or {})
    all_rows: list[list[str]] = []
    pages: list[int] = []
    source_ids: list[str] = []
    for doc in group:
        doc_meta = dict(doc.metadata or {})
        page = _page(doc_meta)
        if page is not None and page not in pages:
            pages.append(page)
        source_id = doc_meta.get("source_element_id")
        if source_id is None:
            source_id = doc_meta.get("element_id")
        sid = str(source_id) if source_id is not None else None
        if sid and sid not in source_ids:
            source_ids.append(sid)
        all_rows.extend(_rows(doc_meta))
    extraction = _make_extraction(meta, all_rows)
    meta["table_extraction"] = extraction.to_metadata()
    meta["table_shape"] = {"rows": extraction.row_count, "columns": extraction.col_count}
    meta["cross_page_merge_pages"] = pages
    meta["cross_page_table_link"] = {
        "schema": "mimirq.cross_page_table_link.v1",
        "merged_count": len(group),
        "pages": pages,
        "source_element_ids": source_ids,
    }
    markdown = render_table_markdown(extraction)
    meta["table_outputs"] = {
        "markdown": markdown,
        "html": render_table_html(extraction),
        "csv": render_table_csv(extraction),
    }
    return Document(page_content=markdown, metadata=meta)


def link_cross_page_table_documents(documents: Sequence[Document] | None) -> list[Document]:
    docs = list(documents or [])
    if len(docs) < 2:
        return docs
    out: list[Document] = []
    index = 0
    while index < len(docs):
        current = docs[index]
        if not _is_table_doc(current):
            out.append(current)
            index += 1
            continue
        group = [current]
        cursor = index + 1
        while cursor < len(docs) and _is_table_doc(docs[cursor]) and _should_merge(group[-1], docs[cursor]):
            group.append(docs[cursor])
            cursor += 1
        out.append(_merge_group(group) if len(group) > 1 else current)
        index = cursor
    return out


__all__ = ["link_cross_page_table_documents"]
