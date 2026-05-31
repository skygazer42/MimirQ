"""
DOCX parser (fallback / lightweight).

Used as a best-effort fallback when MarkItDown is unavailable or fails.
Relies on python-docx (pure Python) to extract paragraphs and tables.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.documents import Document

from app.parsing.utils.markdown_table import build_markdown_table, clean_table_cell, infer_table_header

_HEADING_LEVEL_RE = re.compile(r"(\d+)")


def _looks_like_heading_style(style_name: str) -> bool:
    s = (style_name or "").strip()
    if not s:
        return False
    # Common styles: "Heading 1", "Heading 2", "标题 1", ...
    s_lower = s.lower()
    return s_lower.startswith("heading") or "标题" in s


def _heading_level(style_name: str) -> int:
    raw = (style_name or "").strip()
    m = _HEADING_LEVEL_RE.search(raw)
    if not m:
        return 2
    try:
        lvl = int(m.group(1))
    except Exception:
        return 2
    return max(1, min(6, lvl))


def _is_list_paragraph(p) -> bool:  # noqa: ANN001
    """
    Best-effort list detection for python-docx.

    We avoid resolving numbering definitions; for chunking, stable indentation + list markers
    are more important than exact numbering.
    """
    try:
        ppr = p._p.pPr  # noqa: SLF001
        num_pr = ppr.numPr if ppr is not None else None
        return num_pr is not None
    except Exception:
        return False


def _list_level(p) -> int:  # noqa: ANN001
    try:
        ppr = p._p.pPr  # noqa: SLF001
        num_pr = ppr.numPr if ppr is not None else None
        if num_pr is None:
            return 0
        ilvl = getattr(num_pr, "ilvl", None)
        if ilvl is None:
            return 0
        val = getattr(ilvl, "val", None)
        if val is None:
            return 0
        return max(0, int(val))
    except Exception:
        return 0


def _list_marker(style_name: str) -> str:
    s = (style_name or "").strip().lower()
    # Keep ordered lists recognizable; exact numbering is not required.
    if "number" in s or "编号" in s or "序号" in s:
        return "1."
    return "-"


def _iter_docx_blocks(doc):  # noqa: ANN001
    """
    Yield paragraph/table blocks in document order.

    python-docx exposes paragraphs and tables separately; to preserve reading order
    we iterate the underlying XML body children.
    """
    from docx.oxml.table import CT_Tbl  # type: ignore
    from docx.oxml.text.paragraph import CT_P  # type: ignore
    from docx.table import Table  # type: ignore
    from docx.text.paragraph import Paragraph  # type: ignore

    body = getattr(getattr(doc, "element", None), "body", None)
    if body is None:
        return
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


class DocxParser:
    """Parse DOCX into a chunk-friendly plain text representation."""

    def parse(self, file_path: Path) -> list[Document]:
        from docx import Document as DocxDocument  # type: ignore

        doc = DocxDocument(str(file_path))

        parts: list[str] = []
        for block in _iter_docx_blocks(doc):
            # Paragraph
            if hasattr(block, "text") and hasattr(block, "style"):
                text = (getattr(block, "text", "") or "").strip()
                if not text:
                    continue

                style = getattr(block, "style", None)
                style_name = str(getattr(style, "name", "") or "")

                if _looks_like_heading_style(style_name):
                    level = _heading_level(style_name)
                    parts.append(f"{'#' * level} {text}")
                    continue

                if _is_list_paragraph(block):
                    lvl = _list_level(block)
                    indent = "  " * max(0, min(6, int(lvl)))
                    marker = _list_marker(style_name)
                    parts.append(f"{indent}{marker} {text}")
                    continue

                parts.append(text)
                continue

            # Table
            if hasattr(block, "rows"):
                rows: list[list[str]] = []
                for row in getattr(block, "rows", []) or []:
                    cells: list[str] = []
                    for cell in getattr(row, "cells", []) or []:
                        cells.append(clean_table_cell(getattr(cell, "text", "") or ""))
                    if any(cells):
                        rows.append(cells)

                if not rows:
                    continue

                header, body = infer_table_header(rows)
                parts.append(build_markdown_table(header=header, rows=body))

        content = "\n\n".join(p for p in parts if p)
        metadata = {
            "source": str(file_path.name),
            "file_type": "docx",
        }
        return [Document(page_content=content, metadata=metadata)]
