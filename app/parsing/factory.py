"""
文档解析器工厂
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from langchain_core.documents import Document

from app.parsing.parsers.pdf_parser import PDFParser
from app.parsing.parsers.text_parser import TextParser, MarkdownParser
from app.parsing.backends import normalize_parser_backend
from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("parsing.factory")

if TYPE_CHECKING:
    from app.parsing.parsers.deepdoc_parser import DeepDocParser
    from app.parsing.parsers.docling_parser import DoclingParser
    from app.parsing.parsers.magic_pdf_parser import MagicPDFParser
    from app.parsing.parsers.markitdown_parser import MarkItDownParser
    from app.parsing.parsers.mineru_parser import MinerUParser


class ParserFactory:
    """根据文件类型选择合适的解析器"""

    SUPPORTED_PDF_BACKENDS = {"auto", "basic", "mineru", "deepdoc", "markitdown", "docling", "magicpdf"}
    SUPPORTED_NON_PDF_MARKITDOWN = {".doc", ".docx", ".xls", ".xlsx", ".csv", ".html", ".json"}

    def __init__(self):
        self._basic_pdf_parser = PDFParser()
        self._mineru_parser: Optional[MinerUParser] = None
        self._deepdoc_parser: Optional[DeepDocParser] = None
        self._markitdown_parser: Optional[MarkItDownParser] = None
        self._docling_parser: Optional[DoclingParser] = None
        self._magicpdf_parser: Optional[MagicPDFParser] = None

        logger.info("[pdf] PyMuPDF parser ready (basic)")
        if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
            logger.info("[pdf] MinerU parser available (requires selection)")
        if settings.DEEPDOC_ENABLED:
            logger.info("[pdf] DeepDoc parser available (requires selection)")
        if settings.MARKITDOWN_ENABLED:
            logger.info("[pdf] MarkItDown parser available (requires selection)")
        if getattr(settings, "DOCLING_ENABLED", False):
            logger.info("[pdf] Docling parser available (requires selection)")
        if getattr(settings, "MAGIC_PDF_ENABLED", False):
            logger.info("[pdf] MagicPDF parser available (requires selection)")

        self.parsers = {
            ".txt": TextParser(),
            ".md": MarkdownParser(),
            ".doc": None,  # lazy init MarkItDown
            ".docx": None,
            ".xls": None,
            ".xlsx": None,
            ".csv": None,
            ".html": None,
            ".json": None,
        }

    def resolve_backend(self, file_ext: str, parser_backend: Optional[str]) -> str:
        """
        根据文件类型和用户选择，解析出将要使用的实际解析器。
        """
        normalized = normalize_parser_backend(parser_backend or settings.DEFAULT_PARSER_BACKEND or "auto") or "auto"
        file_ext = file_ext.lower()

        if file_ext != ".pdf":
            if file_ext == ".txt":
                return "text"
            if file_ext == ".md":
                return "markdown"
            if file_ext in self.SUPPORTED_NON_PDF_MARKITDOWN:
                return "markitdown"
            raise ValueError(f"Unsupported file type: {file_ext}")

        if normalized not in self.SUPPORTED_PDF_BACKENDS:
            raise ValueError(
                f"Unsupported parser backend '{normalized}'. "
                f"Supported backends: {sorted(self.SUPPORTED_PDF_BACKENDS)}"
            )

        if normalized == "auto":
            if getattr(settings, "DOCLING_ENABLED", False):
                return "docling"
            if settings.DEEPDOC_ENABLED:
                return "deepdoc"
            if settings.MARKITDOWN_ENABLED:
                return "markitdown"
            if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
                return "mineru"
            if getattr(settings, "MAGIC_PDF_ENABLED", False):
                return "magicpdf"
            return "basic"

        if normalized == "basic":
            return "basic"

        if normalized == "mineru":
            if not (settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL)):
                raise ValueError(
                    "MinerU parser is not enabled. "
                    "Please set MINERU_ENABLED=True and configure MINERU_API_TOKEN (online) "
                    "or MINERU_LOCAL_SERVER_URL (local ZIP mode)."
                )
            return "mineru"

        if normalized == "deepdoc":
            return "deepdoc"

        if normalized == "markitdown":
            return "markitdown"

        if normalized == "docling":
            if not getattr(settings, "DOCLING_ENABLED", False):
                raise ValueError(
                    "Docling parser is not enabled. "
                    "Please set DOCLING_ENABLED=True."
                )
            return "docling"

        if normalized == "magicpdf":
            if not getattr(settings, "MAGIC_PDF_ENABLED", False):
                raise ValueError(
                    "MagicPDF parser is not enabled. "
                    "Please set MAGIC_PDF_ENABLED=True and install magic-pdf."
                )
            return "magicpdf"

        raise ValueError(f"Unsupported parser backend '{normalized}'")

    def parse(
        self,
        file_path: Path,
        parser_backend: Optional[str] = None,
        dataset_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> Tuple[List[Document], str]:
        """
        根据文件类型自动选择解析器并返回 Document 列表以及实际使用的解析器名称
        """
        file_ext = file_path.suffix.lower()
        backend = self.resolve_backend(file_ext, parser_backend)

        if file_ext == ".pdf":
            parser = self._get_pdf_parser(backend)
        elif file_ext == ".txt":
            parser = self.parsers[".txt"]
        elif file_ext == ".md":
            parser = self.parsers[".md"]
        elif file_ext in self.SUPPORTED_NON_PDF_MARKITDOWN:
            parser = self._get_markitdown_parser()
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        # Some parsers (e.g., MinerU local ZIP mode) need dataset/document ids.
        try:
            if backend in {"mineru", "magicpdf"}:
                documents = parser.parse(file_path, dataset_id=dataset_id, document_id=document_id)
            else:
                documents = parser.parse(file_path)
        except Exception as exc:
            fallback_docs, fallback_backend = self._fallback_parse(
                file_path=file_path,
                file_ext=file_ext,
                requested_backend=backend,
                error=exc,
            )
            if fallback_docs is None:
                raise
            documents = fallback_docs
            backend = fallback_backend

        for doc in documents:
            meta = dict(doc.metadata or {})
            # Normalize common metadata keys so downstream indexing/retrieval is consistent.
            meta["parser_backend"] = backend
            # Security + UX: avoid leaking server filesystem paths; keep filename only.
            meta["source"] = str(file_path.name)
            meta.setdefault("filename", file_path.name)
            meta.setdefault("file_type", file_ext.lstrip("."))
            doc.metadata = meta
        return documents, backend

    def _fallback_parse(
        self,
        *,
        file_path: Path,
        file_ext: str,
        requested_backend: str,
        error: Exception,
    ) -> tuple[Optional[List[Document]], str]:
        """
        Best-effort fallback for brittle converter backends.

        We only fall back when we can produce a reasonable text representation
        without introducing new heavy dependencies.
        """
        backend = (requested_backend or "").strip().lower()
        file_ext = (file_ext or "").strip().lower()

        # MarkItDown is a great general converter, but some inputs may fail.
        if backend == "markitdown":
            logger.warning(
                "[parse] MarkItDown failed for %s (%s): %s",
                str(file_path.name),
                file_ext,
                str(error)[:200],
            )
            try:
                if file_ext == ".html":
                    from app.parsing.parsers.html_parser import HtmlParser

                    return HtmlParser().parse(file_path), "html"
                if file_ext == ".csv":
                    from app.parsing.parsers.csv_parser import CsvParser

                    return CsvParser().parse(file_path), "csv"
                if file_ext == ".json":
                    from app.parsing.parsers.json_parser import JsonParser

                    return JsonParser().parse(file_path), "json"
                if file_ext == ".pdf":
                    # Last-resort fallback: basic text extraction via PyMuPDF.
                    return self._basic_pdf_parser.parse(file_path), "basic"
            except Exception as fallback_exc:
                logger.warning(
                    "[parse] Fallback parser also failed for %s: %s",
                    str(file_path.name),
                    str(fallback_exc)[:200],
                )
                return None, backend

        return None, backend

    def _get_pdf_parser(self, backend: str):
        if backend == "basic":
            return self._basic_pdf_parser

        if backend == "mineru":
            if self._mineru_parser is None:
                from app.parsing.parsers.mineru_parser import MinerUParser

                logger.info("[pdf] Initializing MinerU parser (advanced)")
                self._mineru_parser = MinerUParser()
            return self._mineru_parser

        if backend == "deepdoc":
            if self._deepdoc_parser is None:
                from app.parsing.parsers.deepdoc_parser import DeepDocParser

                logger.info("[pdf] Initializing DeepDoc parser (structure-aware)")
                self._deepdoc_parser = DeepDocParser()
            return self._deepdoc_parser

        if backend == "markitdown":
            if self._markitdown_parser is None:
                from app.parsing.parsers.markitdown_parser import MarkItDownParser

                logger.info("[pdf] Initializing MarkItDown parser (markdown-focused)")
                self._markitdown_parser = MarkItDownParser()
            return self._markitdown_parser

        if backend == "docling":
            if self._docling_parser is None:
                from app.parsing.parsers.docling_parser import DoclingParser

                logger.info("[pdf] Initializing Docling parser (structure-aware)")
                self._docling_parser = DoclingParser()
            return self._docling_parser

        if backend == "magicpdf":
            if self._magicpdf_parser is None:
                from app.parsing.parsers.magic_pdf_parser import MagicPDFParser

                logger.info("[pdf] Initializing MagicPDF parser (local advanced)")
                self._magicpdf_parser = MagicPDFParser()
            return self._magicpdf_parser

        raise ValueError(f"Unsupported PDF parser backend '{backend}'")

    def _get_markitdown_parser(self):
        """Lazy init MarkItDown parser for non-PDF office formats."""
        if self._markitdown_parser is None:
            from app.parsing.parsers.markitdown_parser import MarkItDownParser

            logger.info("[markitdown] Initializing parser for non-PDF formats")
            self._markitdown_parser = MarkItDownParser()
        return self._markitdown_parser


# 全局实例
parser_factory = ParserFactory()
