from pathlib import Path
import re
from threading import Lock
from typing import Any, List

from langchain_core.documents import Document
from app.deepdoc.parser import PdfParser as DeepDocPdfParser

class DeepDocParser:
    """Bridge DeepDoc's parser so we can reuse it inside our pipeline."""

    def __init__(self):
        self._parser_cls = DeepDocPdfParser
        self._parser = None
        self._lock = Lock()

    def _ensure_parser(self):
        if self._parser is None:
            self._parser = self._parser_cls()
        return self._parser

    def parse(self, file_path: Path) -> List[Document]:
        """
        Run DeepDoc on the provided PDF and normalize the output into LangChain
        Document objects.

        Notes:
        - DeepDoc (RAGFlowPdfParser) returns `(sections, tables)` where sections
          are text blocks (often tagged with positions) and tables/figures may
          include cropped PIL images.
        - We merge text sections into one Document for downstream chunking.
        - We emit separate "image" Documents for tables/figures so the
          downstream pipeline can upload their `metadata["image"]` to MinIO and
          bind `img_id` to the resulting chunk.
        """
        with self._lock:
            parser = self._ensure_parser()
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

        docs: List[Document] = []

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
        text_parts: List[str] = []
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
            docs.append(Document(page_content=merged_text, metadata=dict(base_meta)))

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
                meta["image"] = image_obj
                docs.append(Document(page_content=content, metadata=meta))

        # Ensure at least one doc is returned so downstream does not crash.
        if not docs:
            docs.append(Document(page_content="", metadata=dict(base_meta)))

        return docs
