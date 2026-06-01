"""
Docling document parser (business layer wrapper)

Wraps the underlying implementation in deepdoc/parser/docling_parser.py,
providing LangChain Document format output.

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
from app.deepdoc.parser.docling_parser import DoclingParser as DeepDocDoclingParser
from app.rag.core.logging import get_logger

from .base_parser import BaseAdvancedParser

logger = get_logger(__name__)

# Configuration
DOCLING_ENABLED = getattr(settings, "DOCLING_ENABLED", False)
DOCLING_OCR_ENABLED = getattr(settings, "DOCLING_OCR_ENABLED", True)
DOCLING_TABLE_MODE = getattr(settings, "DOCLING_TABLE_MODE", "markdown")
DOCLING_EXTRACT_IMAGES = getattr(settings, "DOCLING_EXTRACT_IMAGES", False)


def _apply_element_hints(meta: dict[str, Any], *, text: str) -> dict[str, Any]:
    out = dict(meta)
    content_type = str(out.get("content_type") or "").strip().lower()
    doc_type = str(out.get("doc_type_kwd") or "").strip().lower()
    if doc_type == "table" or content_type == "table":
        out.setdefault("element_kind", "table")
    elif doc_type == "image" or content_type == "image":
        out.setdefault("element_kind", "image")
    elif doc_type == "equation" or content_type == "equation":
        out.setdefault("element_kind", "equation")
    else:
        out.setdefault("element_kind", "paragraph")
    out.setdefault("element_text", str(text or ""))
    attrs = out.get("element_attributes") if isinstance(out.get("element_attributes"), dict) else {}
    attrs.setdefault("source_content_type", content_type or None)
    attrs.setdefault("source_doc_type", doc_type or None)

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
                attrs.setdefault("page", int(page_index + 1))
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
            attrs.setdefault("page", int(out["element_page"]))
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
        t = (tag or "").lower()
        if t == "tr":
            self._in_row = True
            self._cell_buf = []
        elif t in {"td", "th"}:
            self._in_cell = True
            self._cell_buf.append("")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        t = (tag or "").lower()
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
        text = re.sub(r"\s+", " ", data or "").strip()
        if not text:
            return
        idx = len(self._cell_buf) - 1
        self._cell_buf[idx] = (self._cell_buf[idx] + " " + text).strip()


def _html_table_to_markdown(table_html: str) -> str:
    parser = _TableParser()
    parser.feed(table_html or "")
    rows = parser.rows
    if not rows:
        # Fallback: strip tags.
        return re.sub(r"<[^>]+>", " ", table_html or "").strip()

    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]

    def esc(cell: str) -> str:
        cell = _html.unescape(cell or "")
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

    Calls the underlying implementation in deepdoc/parser/docling_parser.py,
    converting sections/tables to LangChain Document format.
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
        self.table_mode = (table_mode or DOCLING_TABLE_MODE or "markdown").strip().lower() or "markdown"
        self.extract_images = DOCLING_EXTRACT_IMAGES if extract_images is None else bool(extract_images)
        self.max_pages = max_pages
        super().__init__()

    def _get_parser_name(self) -> str:
        return "docling"

    def _create_parser(self) -> Any:

        return DeepDocDoclingParser()

    def _check_parser_installation(self, parser: Any) -> tuple[bool, str]:
        ok = parser.check_installation()
        return (ok, "" if ok else "Docling not installed")

    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes | None,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> tuple[list, list]:
        return parser.parse_pdf(
            filepath=str(file_path),
            binary=binary,
            callback=callback,
            delete_output=True,
            **kwargs
        )

    def parse(self, file_path: Path, **kwargs) -> list[Document]:
        documents = super().parse(file_path, **kwargs)

        processed: list[Document] = []
        for doc in documents:
            meta = dict(doc.metadata or {})

            doc_type = str(meta.get("doc_type_kwd") or "").lower()
            if not self.extract_images and doc_type == "image":
                continue

            content_type = str(meta.get("content_type") or "").lower()
            meta = _apply_element_hints(meta, text=doc.page_content or "")
            if content_type == "table":
                content = doc.page_content or ""
                converted = _convert_table_content(content, mode=self.table_mode)
                if converted != content:
                    processed.append(
                        Document(
                            page_content=converted,
                            metadata=_apply_element_hints(meta, text=converted),
                            id=getattr(doc, "id", None),
                        )
                    )
                    continue

            processed.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))

        # Fallback: some PDFs produce no explicit image segments (tables/figures) from Docling,
        # but users still expect to see page images in preview. When enabled, emit page render
        # images only if there are no image segments at all.
        include_page_images = bool(getattr(settings, "DOCLING_INCLUDE_PAGE_IMAGES_IF_EMPTY", True))
        if self.extract_images and include_page_images:
            has_image_segment = any(
                str((d.metadata or {}).get("doc_type_kwd") or "").lower() == "image"
                for d in processed
            )
            if not has_image_segment:
                try:
                    parser = self._get_parser()
                    page_images = getattr(parser, "page_images", None)
                    page_from = int(getattr(parser, "page_from", 0) or 0)
                except Exception:
                    page_images = None
                    page_from = 0

                if isinstance(page_images, list) and page_images:
                    max_pages = int(getattr(settings, "DOCLING_PAGE_IMAGE_MAX_PAGES", 20) or 20)
                    if max_pages > 0:
                        page_images = page_images[:max_pages]

                    base_meta = {
                        "source": file_path.name,
                        "filename": file_path.name,
                        "file_type": file_path.suffix.lstrip(".").lower(),
                        "parser": self._get_parser_name(),
                        "doc_type_kwd": "image",
                        "element_kind": "image",
                        "content_type": "image",
                        "image_source": "page",
                    }

                    page_docs: list[Document] = []
                    for idx, img in enumerate(page_images):
                        page_no = page_from + idx + 1
                        meta = dict(base_meta)
                        meta["page"] = page_no
                        meta["element_page"] = page_no
                        meta["image"] = img
                        meta["element_text"] = f"Page {page_no}"
                        page_docs.append(Document(page_content=f"Page {page_no}", metadata=meta))

                    if page_docs:
                        processed = page_docs + processed

        return processed
