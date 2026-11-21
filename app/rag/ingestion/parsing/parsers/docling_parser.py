"""
Docling document parser (external-service wrapper)

Calls a separately deployed Docling Serve instance and provides LangChain
Document format output. Docling itself and its model weights are deliberately
not installed in the MimirQ API/worker image.

Supports:
- Structure-aware PDF parsing
- Table structure extraction
- Image extraction
- Multiple formats (PDF, DOCX, PPTX, HTML, etc.)
"""

import html as _html
import logging
import re
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.ingestion.parsing.utils.scalars import coerce_int as _coerce_int
from app.services.parsing.docling import DoclingServiceParser, validate_docling_max_pages

from .base_parser import BaseAdvancedParser

logger = logging.getLogger(__name__)

# Configuration
DOCLING_OCR_ENABLED = settings.DOCLING_OCR_ENABLED
_DEFAULT_TABLE_MODE = "markdown"
_DEFAULT_EXTRACT_IMAGES = False


def _apply_element_hints(meta: dict[str, Any], *, text: str) -> dict[str, Any]:
    out = dict(meta)
    content_type = out.get("content_type")
    doc_type = out.get("doc_type_kwd")
    if isinstance(content_type, str):
        content_type = content_type.strip().lower()
    if isinstance(doc_type, str):
        doc_type = doc_type.strip().lower()
    if doc_type == "table" or content_type == "table":
        out.setdefault("element_kind", "table")
    elif doc_type == "image" or content_type == "image":
        out.setdefault("element_kind", "image")
    elif doc_type == "equation" or content_type == "equation":
        out.setdefault("element_kind", "equation")
    else:
        out.setdefault("element_kind", "paragraph")
    out.setdefault("element_text", text)
    attrs = out.get("element_attributes")
    attrs = dict(attrs) if isinstance(attrs, dict) else {}
    attrs.setdefault("source_content_type", out.get("content_type"))
    attrs.setdefault("source_doc_type", out.get("doc_type_kwd"))

    raw_positions = out.get("positions")
    if isinstance(raw_positions, list) and raw_positions:
        if attrs.get("positions") is None:
            attrs["positions"] = list(raw_positions)
        first = raw_positions[0]
        if isinstance(first, (list, tuple)) and len(first) >= 5:
            page_index = _coerce_int(first[0])
            if page_index is not None and page_index >= 0:
                if out.get("element_page") is None:
                    out["element_page"] = page_index + 1
                left, right, top, bottom = (_coerce_int(value) for value in first[1:5])
                if None not in {left, right, top, bottom}:
                    if out.get("element_bbox") is None:
                        out["element_bbox"] = {"x0": left, "x1": right, "y0": top, "y1": bottom}
                else:
                    logger.debug("Ignoring invalid Docling element bbox hint")
            else:
                logger.debug("Ignoring invalid Docling element position hint")
    if out.get("element_page") is None:
        raw_page = _coerce_int(out.get("page"))
        if raw_page is not None:
            out["element_page"] = raw_page
    if out.get("element_page") is not None and attrs.get("page") is None:
        attrs["page"] = out["element_page"]
    if isinstance(out.get("element_bbox"), dict) and attrs.get("bbox") is None:
        attrs["bbox"] = dict(out["element_bbox"])
    out["element_attributes"] = attrs
    return out


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._in_row = False
        self._cell_buf: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "tr":
            self._in_row = True
            self._cell_buf = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._cell_buf.append("")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in {"td", "th"}:
            self._in_cell = False
        elif tag == "tr":
            if self._in_row and self._cell_buf:
                self.rows.append([c.strip() for c in self._cell_buf])
            self._in_row = False
            self._cell_buf = []

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._in_cell or not self._cell_buf:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self._cell_buf[-1] = (self._cell_buf[-1] + " " + text).strip()


def _html_table_to_markdown(table_html: str) -> str:
    parser = _TableParser()
    parser.feed(table_html)
    parser.close()
    rows = parser.rows
    if not rows:
        # Fallback: strip tags.
        return re.sub(r"<[^>]+>", " ", table_html).strip()

    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]

    def esc(cell: str) -> str:
        cell = _html.unescape(cell)
        cell = cell.replace("|", r"\|")
        return re.sub(r"\s+", " ", cell).strip()

    header = [esc(c) for c in norm_rows[0]]
    body = [[esc(c) for c in r] for r in norm_rows[1:]]
    sep = ["---"] * max_cols

    out: list[str] = []
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(sep) + " |")
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out).strip()


def _convert_table_content(text: str, *, mode: str) -> str:
    if mode == "html" or "<table" not in text.lower():
        return text
    if mode == "plain":
        stripped = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", _html.unescape(stripped)).strip()

    # markdown: convert all tables found, join with blank lines.
    tables = list(re.finditer(r"(?is)<table\b.*?</table>", text))
    if not tables:
        return _html_table_to_markdown(text)
    converted = [_html_table_to_markdown(m.group(0)) for m in tables]
    return "\n\n".join([c for c in converted if c.strip()]).strip() or text


class DoclingParser(BaseAdvancedParser):
    """
    Docling document parser (business layer wrapper)

    Calls Docling Serve over HTTP and converts the stable response into
    LangChain Document format.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".html", ".md", ".asciidoc"}

    def __init__(
        self,
        ocr_enabled: bool | None = None,
        table_mode: str | None = None,
        extract_images: bool | None = None,
        max_pages: int | None = None,
    ):
        """
        Initialize Docling parser.

        Args:
            ocr_enabled: Enable OCR for scanned documents
            table_mode: Table output format (markdown, html, plain)
            extract_images: Extract images
            max_pages: Maximum pages to process (None = all)
        """
        validate_docling_max_pages(max_pages)
        self.ocr_enabled = DOCLING_OCR_ENABLED if ocr_enabled is None else bool(ocr_enabled)
        self.table_mode = (table_mode or _DEFAULT_TABLE_MODE).strip().lower() or _DEFAULT_TABLE_MODE
        self.extract_images = _DEFAULT_EXTRACT_IMAGES if extract_images is None else bool(extract_images)
        self.max_pages = max_pages
        super().__init__()

    def _get_parser_name(self) -> str:
        return "docling"

    def _create_parser(self) -> DoclingServiceParser:
        return DoclingServiceParser(ocr_enabled=self.ocr_enabled)

    def _check_parser_installation(self, parser: DoclingServiceParser) -> tuple[bool, str]:
        ok = parser.check_installation()
        return ok, "" if ok else parser.unavailable_reason

    def _call_parse_method(
        self, parser: Any, file_path: Path, binary: bytes | None, callback: Callable[[float, str], None], **kwargs
    ) -> tuple[list, list]:
        parse_kwargs = dict(kwargs)
        parse_kwargs.setdefault("max_pages", self.max_pages)
        return parser.parse_pdf(filepath=str(file_path), binary=binary, callback=callback, **parse_kwargs)

    def _process_document(self, doc: Document) -> list[Document]:
        meta = dict(doc.metadata)
        doc_type = meta.get("doc_type_kwd")
        if isinstance(doc_type, str):
            doc_type = doc_type.lower()
        if not self.extract_images and doc_type == "image":
            return []

        content = doc.page_content
        content_type = meta.get("content_type")
        if isinstance(content_type, str):
            content_type = content_type.lower()
        meta = _apply_element_hints(meta, text=content)
        if content_type == "table":
            content = _convert_table_content(content, mode=self.table_mode)
        return [Document(page_content=content, metadata=meta, id=doc.id)]

    def parse(self, file_path: Path, **kwargs) -> list[Document]:
        validate_docling_max_pages(kwargs.get("max_pages", self.max_pages))
        documents = super().parse(file_path, **kwargs)

        processed: list[Document] = []
        for doc in documents:
            processed.extend(self._process_document(doc))
        return processed
