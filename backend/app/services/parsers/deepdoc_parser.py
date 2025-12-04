"""
Wrapper that adapts DeepDoc's PDF parser to LangChain Document objects.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import List

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
        Run DeepDoc on the provided PDF and normalize the output into a single
        LangChain Document. DeepDoc already performs sophisticated layout
        reconstruction, so we keep its markdown intact and let the downstream
        chunker handle segmentation.
        """
        with self._lock:
            parser = self._ensure_parser()
            try:
                text_content, _ = parser(str(file_path))
            except Exception as exc:  # pragma: no cover - passthrough
                raise RuntimeError(f"DeepDoc failed to parse {file_path}") from exc

            total_pages = getattr(parser, "total_page", None)

        content = text_content if isinstance(text_content, str) else ""
        metadata = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser_backend": "deepdoc",
        }
        if total_pages:
            metadata["total_pages"] = total_pages

        return [Document(page_content=content, metadata=metadata)]
