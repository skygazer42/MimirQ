"""
文档解析器工厂
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from langchain_core.documents import Document

from app.parsing.parsers.pdf_parser import PDFParser
from app.parsing.parsers.text_parser import TextParser, MarkdownParser
from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("parsing.factory")


class ParserFactory:
    """根据文件类型选择合适的解析器"""

    SUPPORTED_PDF_BACKENDS = {"auto", "basic", "mineru", "deepdoc", "markitdown", "docling"}
    SUPPORTED_NON_PDF_MARKITDOWN = {".doc", ".docx", ".xls", ".xlsx", ".csv", ".html", ".json"}

    def __init__(self):
        self._basic_pdf_parser = PDFParser()
        self._mineru_parser: Optional["MinerUParser"] = None
        self._deepdoc_parser: Optional["DeepDocParser"] = None
        self._markitdown_parser: Optional["MarkItDownParser"] = None
        self._docling_parser: Optional["DoclingParser"] = None

        logger.info("[pdf] PyMuPDF parser ready (basic)")
        if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
            logger.info("[pdf] MinerU parser available (requires selection)")
        if settings.DEEPDOC_ENABLED:
            logger.info("[pdf] DeepDoc parser available (requires selection)")
        if settings.MARKITDOWN_ENABLED:
            logger.info("[pdf] MarkItDown parser available (requires selection)")
        if getattr(settings, "DOCLING_ENABLED", False):
            logger.info("[pdf] Docling parser available (requires selection)")

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
        normalized = (parser_backend or settings.DEFAULT_PARSER_BACKEND or "auto").lower()
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
        if backend == "mineru":
            documents = parser.parse(file_path, dataset_id=dataset_id, document_id=document_id)
        else:
            documents = parser.parse(file_path)
        return documents, backend

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
