import re
import warnings
from pathlib import Path
from threading import Lock
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.deepdoc.parser import PdfParser as DeepDocPdfParser

_HEADING_LEVEL_RE = re.compile(r"(\d+)")


def _looks_like_heading_style(style_name: str) -> bool:
    s = (style_name or "").strip()
    if not s:
        return False
    s_lower = s.lower()
    return s_lower.startswith("heading") or "标题" in s


def _heading_level(style_name: str) -> int:
    m = _HEADING_LEVEL_RE.search((style_name or "").strip())
    if not m:
        return 2
    try:
        lvl = int(m.group(1))
    except Exception:
        return 2
    return max(1, min(6, lvl))


def _looks_like_list_style(style_name: str) -> bool:
    s = (style_name or "").strip().lower()
    return "list" in s or "bullet" in s or "列表" in s


def _list_marker(style_name: str) -> str:
    s = (style_name or "").strip().lower()
    if "number" in s or "编号" in s or "序号" in s:
        return "1."
    return "-"


class DeepDocParser:
    """Bridge DeepDoc's parser so we can reuse it inside our pipeline."""

    def __init__(self):
        self._pdf_parser_cls = DeepDocPdfParser
        self._pdf_parser = None
        self._docx_parser = None
        self._lock = Lock()

    def _ensure_pdf_parser(self):
        if self._pdf_parser is None:
            self._pdf_parser = self._pdf_parser_cls()
        return self._pdf_parser

    def _ensure_docx_parser(self):
        if self._docx_parser is None:
            from app.deepdoc.parser import DocxParser as DeepDocDocxParser

            self._docx_parser = DeepDocDocxParser()
        return self._docx_parser

    def parse(self, file_path: Path) -> list[Document]:
        """
        Run DeepDoc on the provided document and normalize the output into LangChain
        Document objects.

        Notes:
        - PDF: DeepDoc returns `(sections, media)` where sections are text blocks
          (often tagged with positions) and tables/figures may include cropped PIL images.
          We merge text sections into one Document and emit separate "image" Documents.
        - DOCX: DeepDoc returns `(paragraphs, tables)`; we join paragraphs + tables into one Document.
        """
        ext = file_path.suffix.lower()

        if ext == ".docx":
            with self._lock:
                parser = self._ensure_docx_parser()
                try:
                    sections, tables = parser(str(file_path))
                except Exception as exc:  # pragma: no cover - passthrough
                    raise RuntimeError(f"DeepDoc failed to parse {file_path}") from exc

            parts: list[str] = []
            if isinstance(sections, list):
                for item in sections:
                    if isinstance(item, tuple):
                        text = str((item[0] if item else "") or "").strip()
                        style_name = str((item[1] if len(item) > 1 else "") or "")
                    else:
                        text = str(item or "").strip()
                        style_name = ""
                    if text:
                        if style_name and _looks_like_heading_style(style_name):
                            parts.append(f"{'#' * _heading_level(style_name)} {text}")
                        elif style_name and _looks_like_list_style(style_name):
                            parts.append(f"{_list_marker(style_name)} {text}")
                        else:
                            parts.append(text)
            else:
                text = str(sections or "").strip()
                if text:
                    parts.append(text)

            if isinstance(tables, list):
                for tb in tables:
                    if isinstance(tb, list):
                        joined = "\n".join(str(x).strip() for x in tb if str(x).strip()).strip()
                        if joined:
                            parts.append(joined)
                    else:
                        text = str(tb or "").strip()
                        if text:
                            parts.append(text)

            merged_text = "\n\n".join(parts).strip()
            return [
                Document(
                    page_content=merged_text,
                    metadata={
                        "source": file_path.name,
                        "file_type": "docx",
                        "parser_backend": "deepdoc",
                    },
                )
            ]

        if ext != ".pdf":
            raise ValueError(f"DeepDoc parser supports only .pdf/.docx, got: {ext or '(no ext)'}")

        with self._lock:
            parser = self._ensure_pdf_parser()
            try:
                sections, media = parser(
                    str(file_path),
                    need_image=True,
                    zoomin=3,
                    return_html=True,
                )
            except Exception as exc:  # pragma: no cover - passthrough
                raise RuntimeError(f"DeepDoc failed to parse {file_path}") from exc

            total_pages = getattr(parser, "total_page", None)

        base_meta = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser_backend": "deepdoc",
        }
        if total_pages:
            base_meta["total_pages"] = total_pages

        docs: list[Document] = []

        pos_tag_re = re.compile(r"@@[0-9-]+\t[0-9.\t]+##")

        def _normalize_section(section: Any) -> str:
            """
            Preserve DeepDoc position tags (`@@...##`) when present.

            Notes:
            - Some DeepDoc variants return tuples like (text, tag) or (text, type, tag).
            - Do NOT call `parser.remove_tag()` here; the parsing workspace preview relies on tags
              to locate blocks back to the PDF.
            """
            if isinstance(section, tuple):
                head = section[0] if section else ""
                text = str(head or "").strip()
                if not text:
                    return ""

                tag = ""
                for item in reversed(section[1:]):
                    if isinstance(item, str) and "@@" in item and "##" in item and pos_tag_re.search(item):
                        tag = item.strip()
                        break
                if tag and tag not in text:
                    text = f"{text}{tag}"
                return text

            if isinstance(section, str):
                return section.strip()
            return str(section or "").strip()

        # 1) Merge text sections into one doc (for downstream chunker).
        text_parts: list[str] = []
        if isinstance(sections, str):
            normalized = _normalize_section(sections)
            if normalized:
                text_parts.append(normalized)
        elif isinstance(sections, list):
            for item in sections:
                normalized = _normalize_section(item)
                if normalized:
                    text_parts.append(normalized)

        merged_text = "\n\n".join(text_parts).strip()
        if merged_text:
            text_meta = dict(base_meta)
            text_meta["element_kind"] = "paragraph"
            text_meta["element_text"] = merged_text
            docs.append(Document(page_content=merged_text, metadata=text_meta))

        # 2) Emit image docs for tables/figures so DocumentProcessor can upload.
        if isinstance(media, list):
            for item in media:
                if not (isinstance(item, tuple) and len(item) == 2):
                    continue
                image_obj, payload = item
                if image_obj is None:
                    continue

                if isinstance(payload, str):
                    content = payload.strip()
                elif isinstance(payload, list):
                    content = "\n".join(str(x).strip() for x in payload if str(x).strip()).strip()
                else:
                    content = str(payload).strip() if payload is not None else ""

                if not content:
                    content = "image"
                # Keep media chunks small to avoid splitting into multiple chunks
                # (which would duplicate uploads for the same image).
                if len(content) > 900:
                    content = content[:900].rstrip() + "..."

                meta = dict(base_meta)
                meta["doc_type_kwd"] = "image"
                meta["element_kind"] = "image"
                meta["element_text"] = content
                meta["image"] = image_obj
                docs.append(Document(page_content=content, metadata=meta))

        # 3) Best-effort seal enrichment for PDF documents.
        if bool(getattr(settings, "SEAL_RECOGNITION_ENABLED", False)):
            try:
                from app.parsing.enrich import seal_recognition

                docs.extend(
                    seal_recognition.extract_seal_documents_from_pdf(
                        file_path=file_path,
                        source=file_path.name,
                        parser_backend="deepdoc",
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive: never fail the main parse path
                warnings.warn(
                    f"DeepDoc seal recognition skipped for {file_path.name}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )

        # Ensure at least one doc is returned so downstream does not crash.
        if not docs:
            docs.append(Document(page_content="", metadata=dict(base_meta)))

        return docs
