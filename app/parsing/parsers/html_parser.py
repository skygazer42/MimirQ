"""
HTML parser (fallback / lightweight).

This parser is used as a robust fallback when MarkItDown is unavailable or fails.
It extracts the main readable content (best-effort) and converts it into plain text
that works well with downstream governance + chunking.
"""


from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.parsing.utils.text import read_text_file


class HtmlParser:
    """HTML document parser with readability-based main-content extraction."""

    def parse(self, file_path: Path, *, html_xpath: str | None = None) -> List[Document]:
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

        # 2) Optional XPath extraction (when caller provides governance_html_xpath).
        xpath_matches = 0
        xpath_error: str | None = None
        if html_xpath and raw_html.strip():
            try:
                from app.rag.preprocessing.html_xpath import extract_text_from_html

                extracted = extract_text_from_html(raw_html, xpath=str(html_xpath))
                xpath_matches = int(extracted.matched_nodes or 0)
                xpath_error = extracted.xpath_error
                if xpath_matches > 0 and (extracted.text or "").strip():
                    text = extracted.text
                else:
                    text = ""
            except Exception:
                text = ""
        else:
            text = ""

        # 3) Convert HTML to plain text.
        if not text:
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
        if html_xpath:
            metadata["html_xpath"] = str(html_xpath)
            metadata["html_xpath_matches"] = int(xpath_matches)
            if xpath_error:
                metadata["html_xpath_error"] = str(xpath_error)

        return [Document(page_content=text, metadata=metadata)]
