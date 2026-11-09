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
import re
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.docling_service import DoclingServiceParser

from .base_parser import BaseAdvancedParser

logger = get_logger(__name__)

# Configuration
DOCLING_ENABLED = settings.DOCLING_ENABLED
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
    attrs = out.get("element_attributes") if isinstance(out.get("element_attributes"), dict) else {}
    attrs.setdefault("source_content_type", out.get("content_type"))
    attrs.setdefault("source_doc_type", out.get("doc_type_kwd"))

    raw_positions = out.get("positions")
    if isinstance(raw_positions, list) and raw_positions:
        attrs.setdefault("positions", list(raw_positions))
        first = raw_positions[0]
        if isinstance(first, (list, tuple)) and len(first) >= 5:
            try:
                page_index = int(first[0])
                out.setdefault("element_page", page_index + 1)
                out.setdefault(
                    "element_bbox",
                    {
                        "x0": int(first[1]),
                        "x1": int(first[2]),
                        "y0": int(first[3]),
                        "y1": int(first[4]),
                    },
                )
                attrs.setdefault("page", page_index + 1)
                attrs.setdefault(
                    "bbox",
                    {
                        "x0": int(first[1]),
                        "x1": int(first[2]),
                        "y0": int(first[3]),
                        "y1": int(first[4]),
                    },
                )
            except Exception as exc:
                logger.debug("Ignoring Docling element position hint failure: %s", exc)
    if out.get("element_page") is None:
        raw_page = out.get("page")
        if isinstance(raw_page, (int, float)) and not isinstance(raw_page, bool):
            out["element_page"] = int(raw_page)
            attrs.setdefault("page", out["element_page"])
    if isinstance(out.get("element_bbox"), dict):
        attrs.setdefault("bbox", dict(out["element_bbox"]))
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
        t = (tag).lower()
        if t == "tr":
            self._in_row = True
            self._cell_buf = []
        elif t in {"td", "th"}:
            self._in_cell = True
            self._cell_buf.append("")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        t = (tag).lower()
        if t in {"td", "th"}:
            self._in_cell = False
        elif t == "tr":
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
        idx = len(self._cell_buf) - 1
        self._cell_buf[idx] = (self._cell_buf[idx] + " " + text).strip()


def _html_table_to_markdown(table_html: str) -> str:
    parser = _TableParser()
    parser.feed(table_html)
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
    mode = (mode or "markdown").strip().lower()
    if not text:
        return ""
    lowered = text.lower()
    if "<table" not in lowered:
        return text

    if mode == "html":
        return text
    if mode == "plain":
        stripped = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", _html.unescape(stripped)).strip()

    # markdown: convert all tables found, join with blank lines.
    tables = list(re.finditer(r"(?is)<table\\b.*?</table>", text))
    if not tables:
        return _html_table_to_markdown(text)
    converted = [_html_table_to_markdown(m.group(0)) for m in tables if m.group(0)]
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
        self.ocr_enabled = DOCLING_OCR_ENABLED if ocr_enabled is None else bool(ocr_enabled)
        self.table_mode = (table_mode or _DEFAULT_TABLE_MODE).strip().lower() or _DEFAULT_TABLE_MODE
        self.extract_images = _DEFAULT_EXTRACT_IMAGES if extract_images is None else bool(extract_images)
        self.max_pages = max_pages
        super().__init__()

    def _get_parser_name(self) -> str:
        return "docling"

    def _create_parser(self) -> Any:
        return DoclingServiceParser(ocr_enabled=self.ocr_enabled)

    def _check_parser_installation(self, parser: Any) -> tuple[bool, str]:
        ok = parser.check_installation()
        reason = str(getattr(parser, "unavailable_reason", "") or "Docling service unavailable")
        return (ok, "" if ok else reason)

    def _call_parse_method(
        self, parser: Any, file_path: Path, binary: bytes | None, callback: Callable[[float, str], None], **kwargs
    ) -> tuple[list, list]:
        return parser.parse_pdf(filepath=str(file_path), binary=binary, callback=callback, **kwargs)

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
            converted = _convert_table_content(content, mode=self.table_mode)
            if converted != content:
                return [
                    Document(
                        page_content=converted,
                        metadata=_apply_element_hints(meta, text=converted),
                        id=doc.id,
                    )
                ]
        return [Document(page_content=content, metadata=meta, id=doc.id)]

    def parse(self, file_path: Path, **kwargs) -> list[Document]:
        documents = super().parse(file_path, **kwargs)

        processed: list[Document] = []
        for doc in documents:
            processed.extend(self._process_document(doc))
        return processed
