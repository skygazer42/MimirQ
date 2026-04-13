"""
Document parser factory
"""

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.backends import normalize_parser_backend
from app.parsing.parsers.text_parser import MarkdownParser, TextParser
from app.rag.core.logging import get_logger

logger = get_logger("parsing.factory")

DOCX_EXTENSION = '.docx'
PPTX_EXTENSION = '.pptx'
XLSX_EXTENSION = '.xlsx'
HTML_EXTENSION = '.html'
JSON_EXTENSION = '.json'
EML_EXTENSION = '.eml'
MSG_EXTENSION = '.msg'
EPUB_EXTENSION = '.epub'
RTF_EXTENSION = '.rtf'
ODT_EXTENSION = '.odt'
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}

if TYPE_CHECKING:
    from app.parsing.parsers.deepdoc_parser import DeepDocParser
    from app.parsing.parsers.deepseek_ocr_parser import DeepSeekOCRParser
    from app.parsing.parsers.docling_parser import DoclingParser
    from app.parsing.parsers.email_parser import EmailParser
    from app.parsing.parsers.etl4llm_parser import Etl4LlmParser
    from app.parsing.parsers.glm_ocr_parser import GlmOCRParser
    from app.parsing.parsers.image_parser import ImageParser
    from app.parsing.parsers.magic_pdf_parser import MagicPDFParser
    from app.parsing.parsers.marker_parser import MarkerParser
    from app.parsing.parsers.markitdown_parser import MarkItDownParser
    from app.parsing.parsers.mineru_parser import MinerUParser
    from app.parsing.parsers.olmocr_parser import OlmocrParser
    from app.parsing.parsers.paddle_vl_parser import PaddleVLParser
    from app.parsing.parsers.pandoc_parser import PandocParser
    from app.parsing.parsers.pdf_parser import PDFParser
    from app.parsing.parsers.qianfan_ocr_parser import QianfanOCRParser
    from app.parsing.parsers.textin_parser import TextInParser


class ParserFactory:
    """Select appropriate parser based on file type"""

    SUPPORTED_PDF_BACKENDS = {
        "auto",
        "basic",
        "marker",
        "paddle_vl",
        "glm_ocr",
        "olmocr",
        "qianfan_ocr",
        "textin",
        "mineru",
        "deepdoc",
        "deepseek_ocr",
        "etl4llm",
        "markitdown",
        "docling",
        "magicpdf",
    }
    PLAIN_TEXT_EXTENSIONS = {
        ".txt",
        ".rst",
        ".adoc",
        ".asciidoc",
        ".tex",
        ".yaml",
        ".yml",
        ".toml",
        ".sql",
        ".log",
        ".conf",
        ".ini",
        ".cfg",
        ".env",
        ".properties",
        ".patch",
        ".diff",
        ".srt",
        ".vtt",
        ".mk",
        ".xml",
        ".rss",
        ".atom",
        ".graphql",
        ".gql",
        ".proto",
        ".tf",
        ".hcl",
        ".jsonl",
        ".ndjson",
    }
    SUPPORTED_NON_PDF_EXTENSIONS = PLAIN_TEXT_EXTENSIONS | {
        ".doc",
        DOCX_EXTENSION,
        ".ppt",
        PPTX_EXTENSION,
        ".xls",
        XLSX_EXTENSION,
        ".csv",
        HTML_EXTENSION,
        ".htm",
        JSON_EXTENSION,
        EML_EXTENSION,
        MSG_EXTENSION,
        EPUB_EXTENSION,
        RTF_EXTENSION,
        ODT_EXTENSION,
    }
    SUPPORTED_NON_PDF_EXTENSIONS = SUPPORTED_NON_PDF_EXTENSIONS | IMAGE_EXTENSIONS
    # Non-PDF formats are primarily handled by general converters (MarkItDown/Pandoc),
    # but some advanced backends (e.g. DeepDoc/Docling) can also handle DOCX when enabled.
    SUPPORTED_NON_PDF_BACKENDS = {"auto", "markitdown", "pandoc", "excel", "docx", "pptx", "html", "csv", "json", "deepdoc", "docling", "email", "image", "textin"}

    def __init__(self):
        self._basic_pdf_parser: PDFParser | None = None
        self._marker_parser: MarkerParser | None = None
        self._paddle_vl_parser: PaddleVLParser | None = None
        self._glm_ocr_parser: GlmOCRParser | None = None
        self._olmocr_parser: OlmocrParser | None = None
        self._qianfan_ocr_parser: QianfanOCRParser | None = None
        self._textin_parser: TextInParser | None = None
        self._mineru_parser: MinerUParser | None = None
        self._deepdoc_parser: DeepDocParser | None = None
        self._deepseek_ocr_parser: DeepSeekOCRParser | None = None
        self._etl4llm_parser: Etl4LlmParser | None = None
        self._markitdown_parser: MarkItDownParser | None = None
        self._pandoc_parser: PandocParser | None = None
        self._docling_parser: DoclingParser | None = None
        self._magicpdf_parser: MagicPDFParser | None = None
        self._email_parser: EmailParser | None = None
        self._image_parser: ImageParser | None = None

        logger.debug("[pdf] Basic PyMuPDF parser available (lazy)")
        if bool(getattr(settings, "MARKER_ENABLED", False)) and bool((getattr(settings, "MARKER_API_URL", "") or "").strip()):
            logger.debug("[pdf] Marker parser available (requires selection)")
        if bool(getattr(settings, "PADDLE_VL_ENABLED", False)) and bool((getattr(settings, "PADDLE_VL_API_URL", "") or "").strip()):
            logger.debug("[pdf] PaddleOCR-VL parser available (requires selection)")
        if bool(getattr(settings, "GLM_OCR_ENABLED", False)) and bool((getattr(settings, "GLM_OCR_API_URL", "") or "").strip()):
            logger.debug("[pdf] GLM-OCR parser available (requires selection)")
        if bool(getattr(settings, "OLMOCR_ENABLED", False)) and bool((getattr(settings, "OLMOCR_API_URL", "") or "").strip()):
            logger.debug("[pdf] olmOCR parser available (requires selection)")
        if bool(getattr(settings, "QIANFAN_OCR_ENABLED", False)) and bool((getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()):
            logger.debug("[pdf] Qianfan-OCR parser available (requires selection)")
        if bool(getattr(settings, "TEXTIN_ENABLED", False)) and bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip()) and bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip()):
            logger.debug("[pdf] TextIn parser available (requires selection)")
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
            DOCX_EXTENSION: None,
            ".ppt": None,
            PPTX_EXTENSION: None,
            ".xls": None,
            XLSX_EXTENSION: None,
            ".csv": None,
            HTML_EXTENSION: None,
            ".htm": None,
            JSON_EXTENSION: None,
            EML_EXTENSION: None,
            MSG_EXTENSION: None,
        }
        for ext in sorted(self.PLAIN_TEXT_EXTENSIONS):
            self.parsers.setdefault(ext, TextParser())

    def resolve_backend(self, file_ext: str, parser_backend: str | None) -> str:
        """
        Resolve the actual parser to use based on file type and user selection.
        """
        normalized = normalize_parser_backend(parser_backend or settings.DEFAULT_PARSER_BACKEND or "auto") or "auto"
        file_ext = file_ext.lower()

        if file_ext != ".pdf":
            if file_ext in self.PLAIN_TEXT_EXTENSIONS:
                return "text"
            if file_ext == ".md":
                return "markdown"
            if file_ext in {EML_EXTENSION, MSG_EXTENSION}:
                # Keep email parsing deterministic and resilient to unrelated backend hints
                # (e.g. when UI stores a global PDF backend preference).
                return "email"
            if file_ext in IMAGE_EXTENSIONS:
                # Standalone images: treat as a first-class supported ingest type.
                # Ignore unrelated backend hints and always route to the lightweight image adapter.
                if normalized == "textin":
                    return "textin"
                return "image"
            if file_ext not in self.SUPPORTED_NON_PDF_EXTENSIONS:
                raise ValueError(f"Unsupported file type: {file_ext}")

            # If a PDF-only backend is selected (common when frontend stores a global preference),
            # fall back to non-PDF auto routing instead of failing hard.
            if normalized not in {"", "auto"} and normalized not in self.SUPPORTED_NON_PDF_BACKENDS:
                if normalized in self.SUPPORTED_PDF_BACKENDS:
                    normalized = "auto"

            if normalized in {"", "auto"}:
                # Office/HTML defaults:
                # - Prefer Pandoc for better image/table fidelity when enabled.
                # - Prefer the built-in Excel Markdown renderer for .xlsx/.xls.
                if file_ext in {EPUB_EXTENSION, RTF_EXTENSION, ODT_EXTENSION}:
                    if bool(getattr(settings, "PANDOC_ENABLED", False)):
                        return "pandoc"
                    return "markitdown"
                if file_ext in {XLSX_EXTENSION, ".xls"}:
                    return "excel"
                if file_ext in {".doc", ".ppt"}:
                    # Pandoc needs LibreOffice for legacy formats.
                    if bool(getattr(settings, "PANDOC_ENABLED", False)) and bool(getattr(settings, "LIBREOFFICE_ENABLED", False)):
                        return "pandoc"
                    return "markitdown"
                if file_ext in {DOCX_EXTENSION, PPTX_EXTENSION, HTML_EXTENSION, ".htm"}:
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
            if normalized == "excel" and file_ext not in {".xls", XLSX_EXTENSION}:
                raise ValueError("excel backend supports only .xls/.xlsx")
            if normalized == "docx" and file_ext not in {DOCX_EXTENSION}:
                raise ValueError("docx backend supports only .docx")
            if normalized == "pptx" and file_ext not in {PPTX_EXTENSION}:
                raise ValueError("pptx backend supports only .pptx")
            if normalized == "html" and file_ext not in {HTML_EXTENSION, ".htm"}:
                raise ValueError("html backend supports only .html/.htm")
            if normalized == "csv" and file_ext != ".csv":
                raise ValueError("csv backend supports only .csv")
            if normalized == "json" and file_ext != JSON_EXTENSION:
                raise ValueError("json backend supports only .json")
            if normalized == "email" and file_ext not in {EML_EXTENSION, MSG_EXTENSION}:
                raise ValueError("email backend supports only .eml/.msg")
            if normalized == "image" and file_ext not in IMAGE_EXTENSIONS:
                raise ValueError(f"image backend supports only: {sorted(IMAGE_EXTENSIONS)}")
            if normalized == "docling":
                if file_ext not in {DOCX_EXTENSION}:
                    raise ValueError("docling backend currently supports only .docx (non-PDF)")
                if not getattr(settings, "DOCLING_ENABLED", False):
                    raise ValueError(
                        "Docling parser is not enabled. "
                        "Please set DOCLING_ENABLED=True."
                    )
            if normalized == "deepdoc" and file_ext not in {DOCX_EXTENSION}:
                raise ValueError("deepdoc backend currently supports only .docx (non-PDF)")
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

        if normalized == "marker":
            if not bool(getattr(settings, "MARKER_ENABLED", False)):
                raise ValueError(
                    "Marker parser is not enabled. "
                    "Please set MARKER_ENABLED=True and configure MARKER_API_URL."
                )
            if not bool((getattr(settings, "MARKER_API_URL", "") or "").strip()):
                raise ValueError("Marker parser requires MARKER_API_URL.")
            return "marker"

        if normalized == "paddle_vl":
            if not bool(getattr(settings, "PADDLE_VL_ENABLED", False)):
                raise ValueError(
                    "PaddleOCR-VL parser is not enabled. "
                    "Please set PADDLE_VL_ENABLED=True and configure PADDLE_VL_API_URL."
                )
            if not bool((getattr(settings, "PADDLE_VL_API_URL", "") or "").strip()):
                raise ValueError("PaddleOCR-VL parser requires PADDLE_VL_API_URL.")
            return "paddle_vl"

        if normalized == "glm_ocr":
            if not bool(getattr(settings, "GLM_OCR_ENABLED", False)):
                raise ValueError(
                    "GLM-OCR parser is not enabled. "
                    "Please set GLM_OCR_ENABLED=True and configure GLM_OCR_API_URL."
                )
            if not bool((getattr(settings, "GLM_OCR_API_URL", "") or "").strip()):
                raise ValueError("GLM-OCR parser requires GLM_OCR_API_URL.")
            return "glm_ocr"

        if normalized == "olmocr":
            if not bool(getattr(settings, "OLMOCR_ENABLED", False)):
                raise ValueError(
                    "olmOCR parser is not enabled. "
                    "Please set OLMOCR_ENABLED=True and configure OLMOCR_API_URL."
                )
            if not bool((getattr(settings, "OLMOCR_API_URL", "") or "").strip()):
                raise ValueError("olmOCR parser requires OLMOCR_API_URL.")
            return "olmocr"

        if normalized == "qianfan_ocr":
            if not bool(getattr(settings, "QIANFAN_OCR_ENABLED", False)):
                raise ValueError(
                    "Qianfan-OCR parser is not enabled. "
                    "Please set QIANFAN_OCR_ENABLED=True and configure QIANFAN_OCR_API_URL."
                )
            if not bool((getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()):
                raise ValueError("Qianfan-OCR parser requires QIANFAN_OCR_API_URL.")
            return "qianfan_ocr"

        if normalized == "textin":
            if not bool(getattr(settings, "TEXTIN_ENABLED", False)):
                raise ValueError(
                    "TextIn parser is not enabled. "
                    "Please set TEXTIN_ENABLED=True and configure TEXTIN credentials."
                )
            if not bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip()):
                raise ValueError("TextIn parser requires TEXTIN_APP_ID.")
            if not bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip()):
                raise ValueError("TextIn parser requires TEXTIN_SECRET_CODE.")
            return "textin"

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
        parser_backend: str | None = None,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,
        pdf_quality: dict[str, Any] | None = None,
        html_xpath: str | None = None,
    ) -> tuple[list[Document], str]:
        """
        Automatically select parser based on file type and return Document list and actual parser name
        """
        file_ext = file_path.suffix.lower()
        backend = self.resolve_backend(file_ext, parser_backend)

        try:
            if file_ext == ".pdf":
                parser = self._get_pdf_parser(backend)
            elif file_ext in self.PLAIN_TEXT_EXTENSIONS:
                # Text-like formats (rst/yaml/toml/sql/log/conf/patch/diff/srt/vtt/xml/jsonl/ndjson/etc.).
                # Keep this lightweight and deterministic (no Pandoc/MarkItDown needed).
                parser = self.parsers[file_ext]
            elif file_ext == ".md":
                parser = self.parsers[".md"]
            elif file_ext in self.SUPPORTED_NON_PDF_EXTENSIONS:
                if backend in {"deepdoc", "docling", "textin"}:
                    # These parsers are initialized in the PDF backend factory, but can also
                    # handle certain non-PDF formats (e.g. DOCX) when explicitly requested.
                    parser = self._get_pdf_parser(backend)
                elif backend == "markitdown":
                    parser = self._get_markitdown_parser()
                elif backend == "pandoc":
                    parser = self._get_pandoc_parser()
                elif backend == "email":
                    parser = self._get_email_parser()
                elif backend == "image":
                    parser = self._get_image_parser()
                elif backend == "excel":
                    from app.parsing.parsers.excel_parser import ExcelParser

                    parser = ExcelParser()
                elif backend == "docx":
                    from app.parsing.parsers.docx_parser import DocxParser

                    parser = DocxParser()
                elif backend == "pptx":
                    from app.parsing.parsers.pptx_parser import PptxParser

                    parser = PptxParser()
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
            if backend in {"marker", "paddle_vl", "glm_ocr", "olmocr", "qianfan_ocr", "textin", "mineru", "magicpdf", "deepseek_ocr", "etl4llm", "pandoc"}:
                documents = parser.parse(
                    file_path,
                    dataset_id=dataset_id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    pdf_quality=pdf_quality,
                )
            else:
                if backend == "html":
                    documents = parser.parse(file_path, html_xpath=html_xpath)  # type: ignore[call-arg]
                else:
                    documents = parser.parse(file_path)
        except Exception as exc:
            fallback_docs, fallback_backend = self._fallback_parse(
                file_path=file_path,
                file_ext=file_ext,
                requested_backend=backend,
                error=exc,
                html_xpath=html_xpath,
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

    def parse_with_provenance(
        self,
        file_path: Path,
        *,
        parser_backend: str | None = None,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,
        pdf_quality: dict[str, Any] | None = None,
        html_xpath: str | None = None,
    ) -> tuple[list[Document], str, dict[str, Any]]:
        """
        Parse a file and return a small provenance payload (best-effort).

        Intended for observability/auditing:
        - records attempted backends (including fallback) with timings
        - avoids embedding large content or filesystem paths
        """
        file_path = Path(file_path)
        file_ext = file_path.suffix.lower()
        backend = self.resolve_backend(file_ext, parser_backend)

        attempts: list[dict[str, Any]] = []
        total_t0 = time.perf_counter()

        def _select_and_parse(selected_backend: str) -> list[Document]:
            if file_ext == ".pdf":
                parser = self._get_pdf_parser(selected_backend)
            elif file_ext in self.PLAIN_TEXT_EXTENSIONS:
                parser = self.parsers[file_ext]
            elif file_ext == ".md":
                parser = self.parsers[".md"]
            elif file_ext in self.SUPPORTED_NON_PDF_EXTENSIONS:
                if selected_backend in {"deepdoc", "docling", "textin"}:
                    parser = self._get_pdf_parser(selected_backend)
                elif selected_backend == "markitdown":
                    parser = self._get_markitdown_parser()
                elif selected_backend == "pandoc":
                    parser = self._get_pandoc_parser()
                elif selected_backend == "email":
                    parser = self._get_email_parser()
                elif selected_backend == "image":
                    parser = self._get_image_parser()
                elif selected_backend == "excel":
                    from app.parsing.parsers.excel_parser import ExcelParser

                    parser = ExcelParser()
                elif selected_backend == "docx":
                    from app.parsing.parsers.docx_parser import DocxParser

                    parser = DocxParser()
                elif selected_backend == "pptx":
                    from app.parsing.parsers.pptx_parser import PptxParser

                    parser = PptxParser()
                elif selected_backend == "html":
                    from app.parsing.parsers.html_parser import HtmlParser

                    parser = HtmlParser()
                elif selected_backend == "csv":
                    from app.parsing.parsers.csv_parser import CsvParser

                    parser = CsvParser()
                elif selected_backend == "json":
                    from app.parsing.parsers.json_parser import JsonParser

                    parser = JsonParser()
                else:
                    raise ValueError(f"Unsupported parser backend '{selected_backend}' for {file_ext}")
            else:
                raise ValueError(f"Unsupported file type: {file_ext}")

            if selected_backend in {"marker", "paddle_vl", "glm_ocr", "olmocr", "qianfan_ocr", "textin", "mineru", "magicpdf", "deepseek_ocr", "etl4llm", "pandoc"}:
                return parser.parse(
                    file_path,
                    dataset_id=dataset_id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    pdf_quality=pdf_quality,
                )
            if selected_backend == "html":
                return parser.parse(file_path, html_xpath=html_xpath)  # type: ignore[call-arg]
            return parser.parse(file_path)

        primary_t0 = time.perf_counter()
        try:
            documents = _select_and_parse(backend)
            attempts.append(
                {
                    "backend": backend,
                    "ok": True,
                    "elapsed_ms": int(round((time.perf_counter() - primary_t0) * 1000)),
                    "documents": int(len(documents or [])),
                    "selected": True,
                }
            )
        except Exception as exc:
            attempts.append(
                {
                    "backend": backend,
                    "ok": False,
                    "elapsed_ms": int(round((time.perf_counter() - primary_t0) * 1000)),
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc)[:200],
                    "selected": False,
                }
            )

            fb_t0 = time.perf_counter()
            fallback_docs, fallback_backend = self._fallback_parse(
                file_path=file_path,
                file_ext=file_ext,
                requested_backend=backend,
                error=exc,
                html_xpath=html_xpath,
            )
            fb_elapsed_ms = int(round((time.perf_counter() - fb_t0) * 1000))
            if fallback_docs is None:
                raise

            documents = fallback_docs
            backend = fallback_backend
            attempts.append(
                {
                    "backend": backend,
                    "ok": True,
                    "elapsed_ms": int(fb_elapsed_ms),
                    "documents": int(len(documents or [])),
                    "fallback_from": attempts[0].get("backend"),
                    "selected": True,
                }
            )

        for doc in documents:
            meta = dict(doc.metadata or {})
            meta["parser_backend"] = backend
            meta["source"] = str(file_path.name)
            meta.setdefault("filename", file_path.name)
            meta.setdefault("file_type", file_ext.lstrip("."))
            doc.metadata = meta

        provenance: dict[str, Any] = {
            "version": "2",
            "file_type": file_ext.lstrip("."),
            "requested_backend": str(parser_backend or ""),
            "resolved_backend": backend,
            "attempts": attempts,
            "elapsed_ms": int(round((time.perf_counter() - total_t0) * 1000)),
        }
        return documents, backend, provenance

    def _fallback_parse(
        self,
        *,
        file_path: Path,
        file_ext: str,
        requested_backend: str,
        error: Exception,
        html_xpath: str | None = None,
    ) -> tuple[list[Document] | None, str]:
        """
        Best-effort fallback for brittle converter backends.

        We only fall back when we can produce a reasonable text representation
        without introducing new heavy dependencies.
        """
        backend = (requested_backend or "").strip().lower()
        file_ext = (file_ext or "").strip().lower()

        # PDF advanced backends (may fail to import due to binary deps or external services); fall back to basic PyMuPDF.
        if file_ext == ".pdf" and backend in {"docling", "deepdoc", "marker", "paddle_vl", "glm_ocr", "olmocr", "qianfan_ocr", "textin", "mineru", "magicpdf", "deepseek_ocr", "etl4llm"}:
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

        # DOCX advanced backends (optional); fall back to Pandoc/MarkItDown/DocxParser.
        if file_ext == DOCX_EXTENSION and backend in {"docling", "deepdoc", "textin"}:
            logger.warning(
                "[parse] DOCX backend '%s' failed for %s: %s; falling back to office converters",
                backend,
                str(file_path.name),
                str(error)[:200],
            )
            try:
                if bool(getattr(settings, "PANDOC_ENABLED", False)):
                    return self._get_pandoc_parser().parse(file_path), "pandoc"
            except Exception as fallback_exc:
                logger.warning(
                    "[parse] Pandoc fallback also failed for %s: %s",
                    str(file_path.name),
                    str(fallback_exc)[:200],
                )

            try:
                return self._get_markitdown_parser().parse(file_path), "markitdown"
            except Exception as fallback_exc:
                logger.warning(
                    "[parse] MarkItDown fallback also failed for %s: %s",
                    str(file_path.name),
                    str(fallback_exc)[:200],
                )
                try:
                    from app.parsing.parsers.docx_parser import DocxParser

                    return DocxParser().parse(file_path), "docx"
                except Exception:
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
                if file_ext == DOCX_EXTENSION:
                    from app.parsing.parsers.docx_parser import DocxParser

                    return DocxParser().parse(file_path), "docx"
                if file_ext == PPTX_EXTENSION:
                    if bool(getattr(settings, "PANDOC_ENABLED", False)):
                        return self._get_pandoc_parser().parse(file_path), "pandoc"
                    from app.parsing.parsers.pptx_parser import PptxParser

                    return PptxParser().parse(file_path), "pptx"
                if file_ext in {XLSX_EXTENSION, ".xls"}:
                    from app.parsing.parsers.excel_parser import ExcelParser

                    return ExcelParser().parse(file_path), "excel"
                if file_ext == HTML_EXTENSION:
                    from app.parsing.parsers.html_parser import HtmlParser

                    return HtmlParser().parse(file_path, html_xpath=html_xpath), "html"
                if file_ext == ".htm":
                    from app.parsing.parsers.html_parser import HtmlParser

                    return HtmlParser().parse(file_path, html_xpath=html_xpath), "html"
                if file_ext == ".csv":
                    from app.parsing.parsers.csv_parser import CsvParser

                    return CsvParser().parse(file_path), "csv"
                if file_ext == JSON_EXTENSION:
                    from app.parsing.parsers.json_parser import JsonParser

                    return JsonParser().parse(file_path), "json"
                if file_ext in {EPUB_EXTENSION, RTF_EXTENSION, ODT_EXTENSION}:
                    if bool(getattr(settings, "PANDOC_ENABLED", False)):
                        return self._get_pandoc_parser().parse(file_path), "pandoc"
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

        if backend == "marker":
            if self._marker_parser is None:
                from app.parsing.parsers.marker_parser import MarkerParser

                logger.info("[pdf] Initializing Marker parser (external service)")
                self._marker_parser = MarkerParser()
            return self._marker_parser

        if backend == "paddle_vl":
            if self._paddle_vl_parser is None:
                from app.parsing.parsers.paddle_vl_parser import PaddleVLParser

                logger.info("[pdf] Initializing PaddleOCR-VL parser (external service)")
                self._paddle_vl_parser = PaddleVLParser()
            return self._paddle_vl_parser

        if backend == "glm_ocr":
            if self._glm_ocr_parser is None:
                from app.parsing.parsers.glm_ocr_parser import GlmOCRParser

                logger.info("[pdf] Initializing GLM-OCR parser (external service)")
                self._glm_ocr_parser = GlmOCRParser()
            return self._glm_ocr_parser

        if backend == "olmocr":
            if self._olmocr_parser is None:
                from app.parsing.parsers.olmocr_parser import OlmocrParser

                logger.info("[pdf] Initializing olmOCR parser (external service)")
                self._olmocr_parser = OlmocrParser()
            return self._olmocr_parser

        if backend == "qianfan_ocr":
            if self._qianfan_ocr_parser is None:
                from app.parsing.parsers.qianfan_ocr_parser import QianfanOCRParser

                logger.info("[pdf] Initializing Qianfan-OCR parser (external service)")
                self._qianfan_ocr_parser = QianfanOCRParser()
            return self._qianfan_ocr_parser

        if backend == "textin":
            if self._textin_parser is None:
                from app.parsing.parsers.textin_parser import TextInParser

                logger.info("[pdf] Initializing TextIn xParse parser (external API)")
                self._textin_parser = TextInParser()
            return self._textin_parser

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

    def _get_email_parser(self):
        """Lazy init Email parser for .eml/.msg."""
        if self._email_parser is None:
            from app.parsing.parsers.email_parser import EmailParser

            logger.info("[email] Initializing parser for email files")
            self._email_parser = EmailParser()
        return self._email_parser

    def _get_image_parser(self):
        """Lazy init Image parser for standalone image files."""
        if self._image_parser is None:
            from app.parsing.parsers.image_parser import ImageParser

            logger.info("[image] Initializing parser for image files")
            self._image_parser = ImageParser()
        return self._image_parser


_PARSER_FACTORY: ParserFactory | None = None
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
