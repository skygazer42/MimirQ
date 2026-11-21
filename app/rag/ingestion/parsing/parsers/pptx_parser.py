"""
PPTX parser (lightweight).

Extracts slide text (and simple tables) using python-pptx.

This is used as a robust fallback when general converters (MarkItDown/Pandoc)
fail on certain presentations.
"""

import logging
from pathlib import Path

from langchain_core.documents import Document
from pptx import Presentation

logger = logging.getLogger(__name__)


def _clean_line(text: str) -> str:
    text = (text).replace("\r", " ").strip()
    return " ".join(text.split())


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = norm[0]
    body = norm[1:]
    out: list[str] = []
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * width) + " |")
    for row in body:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out).strip()


def _escape_md_cell(text: str) -> str:
    return _clean_line(text).replace("|", r"\|")


def _extract_table_text(shape: object) -> str | None:
    if not shape.has_table:
        return None
    table = shape.table
    rows: list[list[str]] = []
    for row_index in range(len(table.rows)):
        row = [_escape_md_cell(table.cell(row_index, col_index).text) for col_index in range(len(table.columns))]
        rows.append(row)
    return _md_table(rows)


def _paragraph_text(para: object) -> str:
    raw = para.text
    text = _clean_line(raw)
    if not text:
        return ""
    level = max(0, min(para.level, 10))
    prefix = ("  " * level) + "- "
    return f"{prefix}{text}"


def _extract_shape_text(shape: object) -> list[str]:
    if not shape.has_text_frame:
        return []
    parts: list[str] = []
    for para in shape.text_frame.paragraphs:
        text = _paragraph_text(para)
        if text:
            parts.append(text)
    return parts


def _extract_slide_parts(slide: object) -> list[str]:
    parts: list[str] = []
    for shape in slide.shapes:
        table_text = _extract_table_text(shape)
        if table_text is not None:
            if table_text:
                parts.append(table_text)
            continue
        parts.extend(_extract_shape_text(shape))
    return parts


class PptxParser:
    """Parse a PowerPoint .pptx into slide-level Documents."""

    def parse(self, file_path: Path) -> list[Document]:
        ext = file_path.suffix.lower()
        if ext != ".pptx":
            raise ValueError(f"PptxParser supports only .pptx, got: {ext or '(no ext)'}")

        prs = Presentation(str(file_path))
        total_slides = len(prs.slides)

        documents: list[Document] = []

        for idx, slide in enumerate(prs.slides):
            parts = _extract_slide_parts(slide)
            content = "\n".join(parts).strip()
            if not content:
                continue

            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": str(file_path.name),
                        "page": idx + 1,
                        "total_pages": total_slides,
                        "file_type": "pptx",
                    },
                )
            )

        if documents:
            return documents

        return [
            Document(
                page_content="",
                metadata={
                    "source": str(file_path.name),
                    "total_pages": total_slides,
                    "file_type": "pptx",
                },
            )
        ]
