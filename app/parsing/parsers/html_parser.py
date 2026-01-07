"""
HTML parser (fallback / lightweight).

This parser is used as a robust fallback when MarkItDown is unavailable or fails.
It extracts the main readable content (best-effort) and converts it into plain text
that works well with downstream governance + chunking.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.parsing.utils.text import read_text_file


class HtmlParser:
    """HTML document parser with readability-based main-content extraction."""

    def parse(self, file_path: Path) -> List[Document]:
        decoded = read_text_file(file_path)
        raw_html = decoded.text or ""

        title: Optional[str] = None
        extracted_html: str = raw_html

        # 1) Best-effort: extract "main article" using readability-lxml.
        try:
            from readability import Document as ReadabilityDocument  # type: ignore

            rd = ReadabilityDocument(raw_html)
            title = (rd.short_title() or rd.title() or None) if raw_html.strip() else None
            extracted_html = rd.summary() or raw_html
        except Exception:
            extracted_html = raw_html

        # 2) Convert HTML to plain text.
        text = ""
        try:
            from html_text import extract_text  # type: ignore

            text = extract_text(extracted_html or "", guess_layout=True) or ""
        except Exception:
            # Last resort: keep raw HTML (still searchable, but less clean).
            text = extracted_html or raw_html or ""

        metadata = {
            "source": str(file_path.name),
            "file_type": "html",
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }
        if title:
            metadata["title"] = title

        return [Document(page_content=text, metadata=metadata)]

