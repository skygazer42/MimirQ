"""
文档解析器工厂
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from langchain_core.documents import Document

from app.services.parsers.pdf_parser import PDFParser
from app.services.parsers.text_parser import TextParser, MarkdownParser
from app.services.parsers.mineru_parser import MinerUParser
from app.config import settings


class ParserFactory:
    """根据文件类型选择合适的解析器"""

    SUPPORTED_PDF_BACKENDS = {"auto", "basic", "mineru", "deepdoc"}

    def __init__(self):
        self._basic_pdf_parser = PDFParser()
        self._mineru_parser: Optional[MinerUParser] = None
        self._deepdoc_parser: Optional["DeepDocParser"] = None

        print("📄 PyMuPDF parser ready for basic PDF parsing")
        if settings.MINERU_ENABLED and settings.MINERU_API_TOKEN:
            print("🚀 MinerU parser available for PDF parsing (requires selection)")
        if settings.DEEPDOC_ENABLED:
            print("🧠 DeepDoc parser available for PDF parsing (requires selection)")

        self.parsers = {
            ".txt": TextParser(),
            ".md": MarkdownParser(),
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
            raise ValueError(f"Unsupported file type: {file_ext}")

        if normalized not in self.SUPPORTED_PDF_BACKENDS:
            raise ValueError(
                f"Unsupported parser backend '{normalized}'. "
                f"Supported backends: {sorted(self.SUPPORTED_PDF_BACKENDS)}"
            )

        if normalized == "auto":
            if settings.MINERU_ENABLED and settings.MINERU_API_TOKEN:
                return "mineru"
            return "basic"

        if normalized == "basic":
            return "basic"

        if normalized == "mineru":
            if not (settings.MINERU_ENABLED and settings.MINERU_API_TOKEN):
                raise ValueError("MinerU parser is not enabled. Please configure MINERU_API_TOKEN.")
            return "mineru"

        if normalized == "deepdoc":
            if not settings.DEEPDOC_ENABLED:
                raise ValueError("DeepDoc parser is not enabled. Set DEEPDOC_ENABLED=True to use it.")
            return "deepdoc"

        raise ValueError(f"Unsupported parser backend '{normalized}'")

    def parse(self, file_path: Path, parser_backend: Optional[str] = None) -> Tuple[List[Document], str]:
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
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        documents = parser.parse(file_path)
        return documents, backend

    def _get_pdf_parser(self, backend: str):
        if backend == "basic":
            return self._basic_pdf_parser

        if backend == "mineru":
            if self._mineru_parser is None:
                print("🚀 Initializing MinerU parser for PDF (advanced parsing)")
                self._mineru_parser = MinerUParser()
            return self._mineru_parser

        if backend == "deepdoc":
            if self._deepdoc_parser is None:
                from app.services.parsers.deepdoc_parser import DeepDocParser

                print("🧠 Initializing DeepDoc parser for PDF (structure-aware parsing)")
                self._deepdoc_parser = DeepDocParser()
            return self._deepdoc_parser

        raise ValueError(f"Unsupported PDF parser backend '{backend}'")


# 全局实例
parser_factory = ParserFactory()
