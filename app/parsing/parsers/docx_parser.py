"""
DOCX parser (fallback / lightweight).

Used as a best-effort fallback when MarkItDown is unavailable or fails.
Relies on python-docx (pure Python) to extract paragraphs and tables.
"""

from pathlib import Path
from typing import List

from langchain_core.documents import Document


def _clean_cell(text: str) -> str:
    return " ".join((text or "").replace("\r", " ").replace("\n", " ").split()).strip()


class DocxParser:
    """Parse DOCX into a chunk-friendly plain text representation."""

    def parse(self, file_path: Path) -> List[Document]:
        from docx import Document as DocxDocument  # type: ignore

        doc = DocxDocument(str(file_path))

        parts: list[str] = []
        for p in getattr(doc, "paragraphs", []) or []:
            text = (p.text or "").strip()
            if text:
                parts.append(text)

        for table in getattr(doc, "tables", []) or []:
            for row in getattr(table, "rows", []) or []:
                cells = []
                for cell in getattr(row, "cells", []) or []:
                    cell_text = _clean_cell(getattr(cell, "text", "") or "")
                    cells.append(cell_text)
                if any(cells):
                    parts.append(" | ".join(cells))

        content = "\n".join(p for p in parts if p)
        metadata = {
            "source": str(file_path.name),
            "file_type": "docx",
        }
        return [Document(page_content=content, metadata=metadata)]

