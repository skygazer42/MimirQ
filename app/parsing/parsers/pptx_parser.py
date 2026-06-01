"""
PPTX parser (lightweight).

Extracts slide text (and simple tables) using python-pptx.

This is used as a robust fallback when general converters (MarkItDown/Pandoc)
fail on certain presentations.
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


def _clean_line(text: str) -> str:
    text = (text or "").replace("\r", " ").strip()
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


class PptxParser:
    """Parse a PowerPoint .pptx into slide-level Documents."""

    def parse(self, file_path: Path) -> list[Document]:
        ext = file_path.suffix.lower()
        if ext != ".pptx":
            raise ValueError(f"PptxParser supports only .pptx, got: {ext or '(no ext)'}")

        try:
            from pptx import Presentation  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("python-pptx is not installed; cannot parse .pptx files") from exc

        prs = Presentation(str(file_path))
        total_slides = len(getattr(prs, "slides", []) or [])

        documents: list[Document] = []

        for idx, slide in enumerate(prs.slides):
            parts: list[str] = []

            for shape in getattr(slide, "shapes", []) or []:
                # Tables -> Markdown
                try:
                    if bool(getattr(shape, "has_table", False)):
                        table = shape.table
                        rows: list[list[str]] = []
                        for r in range(len(table.rows)):
                            row: list[str] = []
                            for c in range(len(table.columns)):
                                try:
                                    cell_text = table.cell(r, c).text
                                except Exception:
                                    cell_text = ""
                                row.append(_escape_md_cell(cell_text))
                            if any(row):
                                rows.append(row)
                        if rows:
                            parts.append(_md_table(rows))
                        continue
                except Exception as exc:
                    # Best-effort: ignore table extraction errors.
                    logger.debug("Failed to extract PPTX table; falling back to text frame handling: %s", exc)

                # Text frames -> plain text (keep bullet/indent via paragraph.level).
                try:
                    if not bool(getattr(shape, "has_text_frame", False)):
                        continue
                    tf = shape.text_frame
                    for para in getattr(tf, "paragraphs", []) or []:
                        raw = str(getattr(para, "text", "") or "")
                        text = _clean_line(raw)
                        if not text:
                            continue
                        level = 0
                        try:
                            level = int(getattr(para, "level", 0) or 0)
                        except Exception:
                            level = 0
                        level = max(0, min(level, 10))
                        prefix = ("  " * level) + "- " if text else ""
                        parts.append(f"{prefix}{text}" if prefix else text)
                except Exception:
                    continue

            content = "\n".join([p for p in (parts or []) if p]).strip()
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
