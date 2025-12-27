"""
文档解析器工厂
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from langchain_core.documents import Document

from app.parsing.parsers.pdf_parser import PDFParser
from app.parsing.parsers.text_parser import TextParser, MarkdownParser
from app.parsing.parsers.mineru_parser import MinerUParser
from app.parsing.parsers.markitdown_parser import MarkItDownParser
from app.core.config import settings


class ParserFactory:
    """根据文件类型选择合适的解析器"""

    SUPPORTED_PDF_BACKENDS = {"auto", "basic", "mineru", "deepdoc", "markitdown"}

    def __init__(self):
        self._basic_pdf_parser = PDFParser()
        self._mineru_parser: Optional[MinerUParser] = None
        self._deepdoc_parser: Optional["DeepDocParser"] = None
        self._markitdown_parser: Optional[MarkItDownParser] = None

        print("[PDF] PyMuPDF parser ready for basic PDF parsing")
        if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
            print("[MinerU] MinerU parser available for PDF parsing (requires selection)")
        if settings.DEEPDOC_ENABLED:
            print("[DeepDoc] DeepDoc parser available for PDF parsing (requires selection)")
        if settings.MARKITDOWN_ENABLED:
            print("[MarkItDown] MarkItDown parser available for PDF parsing (requires selection)")

        self.parsers = {
            ".txt": TextParser(),
            ".md": MarkdownParser(),
            ".doc": None,  # lazy init MarkItDown
            ".docx": None,
            ".xls": None,
            ".xlsx": None,
            ".csv": None,
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
            if file_ext in {".doc", ".docx", ".xls", ".xlsx", ".csv"}:
                return "markitdown"
            raise ValueError(f"Unsupported file type: {file_ext}")

        if normalized not in self.SUPPORTED_PDF_BACKENDS:
            raise ValueError(
                f"Unsupported parser backend '{normalized}'. "
                f"Supported backends: {sorted(self.SUPPORTED_PDF_BACKENDS)}"
            )

        if normalized == "auto":
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
        elif file_ext in {".doc", ".docx", ".xls", ".xlsx", ".csv"}:
            parser = self._get_markitdown_parser()
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        # Some parsers (e.g., MinerU local ZIP mode) need dataset/document ids.
        if backend == "mineru" and isinstance(parser, MinerUParser):
            documents = parser.parse(file_path, dataset_id=dataset_id, document_id=document_id)
        else:
            documents = parser.parse(file_path)
        return documents, backend

    def _get_pdf_parser(self, backend: str):
        if backend == "basic":
            return self._basic_pdf_parser

        if backend == "mineru":
            if self._mineru_parser is None:
                print("[MinerU] Initializing MinerU parser for PDF (advanced parsing)")
                self._mineru_parser = MinerUParser()
            return self._mineru_parser

        if backend == "deepdoc":
            if self._deepdoc_parser is None:
                from app.parsing.parsers.deepdoc_parser import DeepDocParser

                print("[DeepDoc] Initializing DeepDoc parser for PDF (structure-aware parsing)")
                self._deepdoc_parser = DeepDocParser()
            return self._deepdoc_parser

        if backend == "markitdown":
            if self._markitdown_parser is None:
                print("[MarkItDown] Initializing MarkItDown parser for PDF (markdown-focused parsing)")
                self._markitdown_parser = MarkItDownParser()
            return self._markitdown_parser

        raise ValueError(f"Unsupported PDF parser backend '{backend}'")

    def _get_markitdown_parser(self):
        """Lazy init MarkItDown parser for non-PDF office formats."""
        if self._markitdown_parser is None:
            print("[MarkItDown] Initializing MarkItDown parser for office documents")
            self._markitdown_parser = MarkItDownParser()
        return self._markitdown_parser


# 全局实例
parser_factory = ParserFactory()
