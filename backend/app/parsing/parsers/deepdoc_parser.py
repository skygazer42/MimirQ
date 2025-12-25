"""
Wrapper that adapts DeepDoc's PDF parser to LangChain Document objects.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, List

from langchain_core.documents import Document


class DeepDocParser:
    """Bridge DeepDoc's parser so we can reuse it inside our pipeline."""

    def __init__(self):
        try:
            from deepdoc.parser import PdfParser as DeepDocPdfParser
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "DeepDoc is not installed. Please ensure deepdoc and its "
                "dependencies are available before enabling this parser."
            ) from exc

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

        def _clean_text(val: Any) -> str:
            if not isinstance(val, str):
                return ""
            text = val
            if hasattr(parser, "remove_tag"):
                try:
                    text = parser.remove_tag(text)
                except Exception:
                    text = val
            return (text or "").strip()

        # 1) Merge text sections into one doc (for downstream chunker).
        text_parts: List[str] = []
        if isinstance(sections, str):
            cleaned = _clean_text(sections)
            if cleaned:
                text_parts.append(cleaned)
        elif isinstance(sections, list):
            for item in sections:
                # Some variants return (text, tag) tuples.
                if isinstance(item, tuple) and item:
                    cleaned = _clean_text(item[0])
                else:
                    cleaned = _clean_text(item)
                if cleaned:
                    text_parts.append(cleaned)

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
