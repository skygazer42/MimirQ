"""
Document parser factory
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from langchain_core.documents import Document

from app.parsing.parsers.text_parser import TextParser, MarkdownParser
from app.parsing.backends import normalize_parser_backend
from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("parsing.factory")

if TYPE_CHECKING:
    from app.parsing.parsers.deepdoc_parser import DeepDocParser
    from app.parsing.parsers.deepseek_ocr_parser import DeepSeekOCRParser
    from app.parsing.parsers.etl4llm_parser import Etl4LlmParser
    from app.parsing.parsers.docling_parser import DoclingParser
    from app.parsing.parsers.magic_pdf_parser import MagicPDFParser
    from app.parsing.parsers.markitdown_parser import MarkItDownParser
    from app.parsing.parsers.mineru_parser import MinerUParser
    from app.parsing.parsers.pandoc_parser import PandocParser
    from app.parsing.parsers.pdf_parser import PDFParser


class ParserFactory:
    """Select appropriate parser based on file type"""

    SUPPORTED_PDF_BACKENDS = {
        "auto",
        "basic",
        "mineru",
        "deepdoc",
        "deepseek_ocr",
        "etl4llm",
        "markitdown",
        "docling",
        "magicpdf",
    }
    SUPPORTED_NON_PDF_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".html", ".htm", ".json"}
    SUPPORTED_NON_PDF_BACKENDS = {"auto", "markitdown", "pandoc", "excel", "docx", "html", "csv", "json"}

    def __init__(self):
        self._basic_pdf_parser: Optional[PDFParser] = None
        self._mineru_parser: Optional[MinerUParser] = None
        self._deepdoc_parser: Optional[DeepDocParser] = None
        self._deepseek_ocr_parser: Optional[DeepSeekOCRParser] = None
        self._etl4llm_parser: Optional[Etl4LlmParser] = None
        self._markitdown_parser: Optional[MarkItDownParser] = None
        self._pandoc_parser: Optional[PandocParser] = None
        self._docling_parser: Optional[DoclingParser] = None
        self._magicpdf_parser: Optional[MagicPDFParser] = None

        logger.debug("[pdf] Basic PyMuPDF parser available (lazy)")
        if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
            logger.debug("[pdf] MinerU parser available (requires selection)")
        if settings.DEEPDOC_ENABLED:
            logger.debug("[pdf] DeepDoc parser available (requires selection)")
        if bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(getattr(settings, "SILICONFLOW_API_KEY", "")):
            logger.debug("[pdf] DeepSeek OCR parser available (requires selection)")
        if bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
            (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
        ):
            logger.debug("[pdf] ETL4LLM parser available (requires selection)")
        if settings.MARKITDOWN_ENABLED:
            logger.debug("[pdf] MarkItDown parser available (requires selection)")
        if getattr(settings, "DOCLING_ENABLED", False):
            logger.debug("[pdf] Docling parser available (requires selection)")
        if getattr(settings, "MAGIC_PDF_ENABLED", False):
            logger.debug("[pdf] MagicPDF parser available (requires selection)")

        self.parsers = {
            ".txt": TextParser(),
            ".md": MarkdownParser(),
            ".doc": None,  # lazy init MarkItDown
            ".docx": None,
            ".ppt": None,
            ".pptx": None,
            ".xls": None,
            ".xlsx": None,
            ".csv": None,
            ".html": None,
            ".htm": None,
            ".json": None,
        }

    def resolve_backend(self, file_ext: str, parser_backend: Optional[str]) -> str:
        """
        Resolve the actual parser to use based on file type and user selection.
        """
        normalized = normalize_parser_backend(parser_backend or settings.DEFAULT_PARSER_BACKEND or "auto") or "auto"
        file_ext = file_ext.lower()

        if file_ext != ".pdf":
            if file_ext == ".txt":
                return "text"
            if file_ext == ".md":
                return "markdown"
            if file_ext not in self.SUPPORTED_NON_PDF_EXTENSIONS:
                raise ValueError(f"Unsupported file type: {file_ext}")

            if normalized in {"", "auto"}:
                # Office/HTML defaults:
                # - Prefer Pandoc for better image/table fidelity when enabled.
                # - Prefer the built-in Excel Markdown renderer for .xlsx/.xls.
                if file_ext in {".xlsx", ".xls"}:
                    return "excel"
                if file_ext in {".doc", ".ppt"}:
                    # Pandoc needs LibreOffice for legacy formats.
                    if bool(getattr(settings, "PANDOC_ENABLED", False)) and bool(getattr(settings, "LIBREOFFICE_ENABLED", False)):
                        return "pandoc"
                    return "markitdown"
                if file_ext in {".docx", ".pptx", ".html", ".htm"}:
                    if bool(getattr(settings, "PANDOC_ENABLED", False)):
                        return "pandoc"
                    return "markitdown"
                # csv/json: keep MarkItDown as the general converter.
                return "markitdown"

            if normalized not in self.SUPPORTED_NON_PDF_BACKENDS:
                raise ValueError(
                    f"Unsupported parser backend '{normalized}' for {file_ext}. "
                    f"Supported: {sorted(self.SUPPORTED_NON_PDF_BACKENDS)}"
                )

            # Backend compatibility checks (best-effort).
            if normalized == "excel" and file_ext not in {".xls", ".xlsx"}:
                raise ValueError("excel backend supports only .xls/.xlsx")
            if normalized == "docx" and file_ext not in {".docx"}:
                raise ValueError("docx backend supports only .docx")
            if normalized == "html" and file_ext not in {".html", ".htm"}:
                raise ValueError("html backend supports only .html/.htm")
            if normalized == "csv" and file_ext != ".csv":
                raise ValueError("csv backend supports only .csv")
            if normalized == "json" and file_ext != ".json":
                raise ValueError("json backend supports only .json")
            return normalized

        if normalized not in self.SUPPORTED_PDF_BACKENDS:
            raise ValueError(
                f"Unsupported parser backend '{normalized}'. "
                f"Supported backends: {sorted(self.SUPPORTED_PDF_BACKENDS)}"
            )

        if normalized == "auto":
            if getattr(settings, "DOCLING_ENABLED", False):
                return "docling"
            if bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
                (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
            ):
                return "etl4llm"
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

        if normalized == "deepseek_ocr":
            if not bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)):
                raise ValueError(
                    "DeepSeek OCR parser is not enabled. "
                    "Please set DEEPSEEK_OCR_ENABLED=True and configure SILICONFLOW_API_KEY."
                )
            if not bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()):
                raise ValueError("DeepSeek OCR parser requires SILICONFLOW_API_KEY.")
            return "deepseek_ocr"

        if normalized == "etl4llm":
            if not bool(getattr(settings, "ETL4LLM_ENABLED", False)):
                raise ValueError(
                    "ETL4LLM parser is not enabled. "
                    "Please set ETL4LLM_ENABLED=True and configure ETL4LLM_API_URL."
                )
            if not bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip()):
                raise ValueError("ETL4LLM parser requires ETL4LLM_API_URL.")
            return "etl4llm"

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
        tenant_id: Optional[str] = None,
        pdf_quality: Optional[dict[str, Any]] = None,
    ) -> Tuple[List[Document], str]:
        """
        Automatically select parser based on file type and return Document list and actual parser name
        """
        file_ext = file_path.suffix.lower()
        backend = self.resolve_backend(file_ext, parser_backend)

        try:
            if file_ext == ".pdf":
                parser = self._get_pdf_parser(backend)
            elif file_ext == ".txt":
                parser = self.parsers[".txt"]
            elif file_ext == ".md":
                parser = self.parsers[".md"]
            elif file_ext in self.SUPPORTED_NON_PDF_EXTENSIONS:
                if backend == "markitdown":
                    parser = self._get_markitdown_parser()
                elif backend == "pandoc":
                    parser = self._get_pandoc_parser()
                elif backend == "excel":
                    from app.parsing.parsers.excel_parser import ExcelParser

                    parser = ExcelParser()
                elif backend == "docx":
                    from app.parsing.parsers.docx_parser import DocxParser

                    parser = DocxParser()
                elif backend == "html":
                    from app.parsing.parsers.html_parser import HtmlParser

                    parser = HtmlParser()
                elif backend == "csv":
                    from app.parsing.parsers.csv_parser import CsvParser

                    parser = CsvParser()
                elif backend == "json":
                    from app.parsing.parsers.json_parser import JsonParser

                    parser = JsonParser()
                else:
                    raise ValueError(f"Unsupported parser backend '{backend}' for {file_ext}")
            else:
                raise ValueError(f"Unsupported file type: {file_ext}")

            # Some parsers need dataset/document ids to produce stable artifacts.
            if backend in {"mineru", "magicpdf", "deepseek_ocr", "etl4llm", "pandoc"}:
                documents = parser.parse(
                    file_path,
                    dataset_id=dataset_id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    pdf_quality=pdf_quality,
                )
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

        # PDF advanced backends (may fail to import due to binary deps or external services); fall back to basic PyMuPDF.
        if file_ext == ".pdf" and backend in {"docling", "deepdoc", "mineru", "magicpdf", "deepseek_ocr", "etl4llm"}:
            logger.warning(
                "[parse] PDF backend '%s' failed for %s: %s; falling back to 'basic'",
                backend,
                str(file_path.name),
                str(error)[:200],
            )
            try:
                return self._get_pdf_parser("basic").parse(file_path), "basic"
            except Exception as fallback_exc:
                logger.warning(
                    "[parse] PDF basic fallback also failed for %s: %s",
                    str(file_path.name),
                    str(fallback_exc)[:200],
                )
                return None, backend

        # MarkItDown is a great general converter, but some inputs may fail.
        if backend == "markitdown":
            logger.warning(
                "[parse] MarkItDown failed for %s (%s): %s",
                str(file_path.name),
                file_ext,
                str(error)[:200],
            )
            try:
                if file_ext == ".docx":
                    from app.parsing.parsers.docx_parser import DocxParser

                    return DocxParser().parse(file_path), "docx"
                if file_ext == ".pptx":
                    if bool(getattr(settings, "PANDOC_ENABLED", False)):
                        return self._get_pandoc_parser().parse(file_path), "pandoc"
                if file_ext in {".xlsx", ".xls"}:
                    from app.parsing.parsers.excel_parser import ExcelParser

                    return ExcelParser().parse(file_path), "excel"
                if file_ext == ".html":
                    from app.parsing.parsers.html_parser import HtmlParser

                    return HtmlParser().parse(file_path), "html"
                if file_ext == ".htm":
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
                    return self._get_pdf_parser("basic").parse(file_path), "basic"
            except Exception as fallback_exc:
                logger.warning(
                    "[parse] Fallback parser also failed for %s: %s",
                    str(file_path.name),
                    str(fallback_exc)[:200],
                )
                return None, backend

        # Excel parser may fail for legacy .xls when optional engines are missing; fall back to MarkItDown.
        if backend == "excel":
            logger.warning(
                "[parse] Excel parser failed for %s (%s): %s",
                str(file_path.name),
                file_ext,
                str(error)[:200],
            )
            try:
                return self._get_markitdown_parser().parse(file_path), "markitdown"
            except Exception as fallback_exc:
                logger.warning(
                    "[parse] MarkItDown fallback also failed for %s: %s",
                    str(file_path.name),
                    str(fallback_exc)[:200],
                )
                return None, backend

        # Pandoc may fail when the CLI isn't installed; fall back to MarkItDown or lightweight parsers.
        if backend == "pandoc":
            logger.warning(
                "[parse] Pandoc failed for %s (%s): %s",
                str(file_path.name),
                file_ext,
                str(error)[:200],
            )
            try:
                return self._get_markitdown_parser().parse(file_path), "markitdown"
            except Exception:
                # Reuse MarkItDown fallback logic by pretending MarkItDown failed.
                return self._fallback_parse(file_path=file_path, file_ext=file_ext, requested_backend="markitdown", error=error)

        return None, backend

    def _get_pdf_parser(self, backend: str):
        if backend == "basic":
            if self._basic_pdf_parser is None:
                from app.parsing.parsers.pdf_parser import PDFParser

                logger.debug("[pdf] Initializing PyMuPDF parser (basic)")
                self._basic_pdf_parser = PDFParser()
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

        if backend == "deepseek_ocr":
            if self._deepseek_ocr_parser is None:
                from app.parsing.parsers.deepseek_ocr_parser import DeepSeekOCRParser

                logger.info("[pdf] Initializing DeepSeek OCR parser (SiliconFlow)")
                self._deepseek_ocr_parser = DeepSeekOCRParser()
            return self._deepseek_ocr_parser

        if backend == "etl4llm":
            if self._etl4llm_parser is None:
                from app.parsing.parsers.etl4llm_parser import Etl4LlmParser

                logger.info("[pdf] Initializing ETL4LLM parser (layout-aware)")
                self._etl4llm_parser = Etl4LlmParser()
            return self._etl4llm_parser

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

    def _get_pandoc_parser(self):
        """Lazy init Pandoc parser for Office/HTML formats."""
        if self._pandoc_parser is None:
            from app.parsing.parsers.pandoc_parser import PandocParser

            logger.info("[pandoc] Initializing parser for Office/HTML formats")
            self._pandoc_parser = PandocParser()
        return self._pandoc_parser


_PARSER_FACTORY: Optional[ParserFactory] = None
_PARSER_FACTORY_LOCK = threading.Lock()


def get_parser_factory() -> ParserFactory:
    """
    Return the global parser factory instance (lazy init).

    This avoids importing heavy PDF deps (PyMuPDF) and emitting availability logs
    during module import (e.g. when exporting OpenAPI).
    """
    global _PARSER_FACTORY
    if _PARSER_FACTORY is None:
        with _PARSER_FACTORY_LOCK:
            if _PARSER_FACTORY is None:
                _PARSER_FACTORY = ParserFactory()
    return _PARSER_FACTORY


class _ParserFactoryProxy:
    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        return getattr(get_parser_factory(), name)


# Keep the historical import surface: `from app.parsing.factory import parser_factory`.
parser_factory = _ParserFactoryProxy()
