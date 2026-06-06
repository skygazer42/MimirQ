"""
Document parser factory
"""

import importlib
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
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
SOURCE_CODE_EXTENSIONS = {
    '.astro',
    '.bash',
    '.c',
    '.cc',
    '.cjs',
    '.cpp',
    '.cs',
    '.css',
    '.cts',
    '.cxx',
    '.go',
    '.h',
    '.hpp',
    '.java',
    '.js',
    '.jsx',
    '.kt',
    '.kts',
    '.less',
    '.lua',
    '.mjs',
    '.mts',
    '.php',
    '.ps1',
    '.py',
    '.pyi',
    '.r',
    '.rb',
    '.rs',
    '.sass',
    '.scala',
    '.scss',
    '.sh',
    '.svelte',
    '.swift',
    '.ts',
    '.tsx',
    '.vue',
    '.zsh',
}

if TYPE_CHECKING:
    from app.parsing.parsers.audio_parser import AudioParser
    from app.parsing.parsers.colpali_parser import ColPaliParser
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
    from app.parsing.parsers.video_parser import VideoParser


class ParserFactory:
    """Select appropriate parser based on file type"""

    PDF_ADVANCED_FALLBACK_BACKENDS = {
        "docling",
        "deepdoc",
        "marker",
        "paddle_vl",
        "glm_ocr",
        "olmocr",
        "qianfan_ocr",
        "textin",
        "mineru",
        "magicpdf",
        "deepseek_ocr",
        "etl4llm",
    }
    DOCX_ADVANCED_FALLBACK_BACKENDS = {"docling", "deepdoc", "textin"}

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
        "colpali",
    }
    PLAIN_TEXT_EXTENSIONS = SOURCE_CODE_EXTENSIONS | {
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
    SUPPORTED_NON_PDF_EXTENSIONS = PLAIN_TEXT_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | {
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
    # Non-PDF formats are primarily handled by general converters (MarkItDown/Pandoc),
    # but some advanced backends (e.g. DeepDoc/Docling) can also handle DOCX when enabled.
    SUPPORTED_NON_PDF_BACKENDS = {"auto", "markitdown", "pandoc", "excel", "docx", "pptx", "html", "csv", "json", "deepdoc", "docling", "email", "image", "audio", "video", "textin", "colpali"}

    PDF_SETTING_REQUIREMENTS = {
        "marker": (
            "MARKER_ENABLED",
            "Marker parser is not enabled. Please set MARKER_ENABLED=True and configure MARKER_API_URL.",
            (("MARKER_API_URL", "Marker parser requires MARKER_API_URL."),),
        ),
        "paddle_vl": (
            "PADDLE_VL_ENABLED",
            "PaddleOCR-VL parser is not enabled. Please set PADDLE_VL_ENABLED=True and configure PADDLE_VL_API_URL.",
            (("PADDLE_VL_API_URL", "PaddleOCR-VL parser requires PADDLE_VL_API_URL."),),
        ),
        "glm_ocr": (
            "GLM_OCR_ENABLED",
            "GLM-OCR parser is not enabled. Please set GLM_OCR_ENABLED=True and configure GLM_OCR_API_URL.",
            (("GLM_OCR_API_URL", "GLM-OCR parser requires GLM_OCR_API_URL."),),
        ),
        "olmocr": (
            "OLMOCR_ENABLED",
            "olmOCR parser is not enabled. Please set OLMOCR_ENABLED=True and configure OLMOCR_API_URL.",
            (("OLMOCR_API_URL", "olmOCR parser requires OLMOCR_API_URL."),),
        ),
        "qianfan_ocr": (
            "QIANFAN_OCR_ENABLED",
            "Qianfan-OCR parser is not enabled. Please set QIANFAN_OCR_ENABLED=True and configure QIANFAN_OCR_API_URL.",
            (("QIANFAN_OCR_API_URL", "Qianfan-OCR parser requires QIANFAN_OCR_API_URL."),),
        ),
        "textin": (
            "TEXTIN_ENABLED",
            "TextIn parser is not enabled. Please set TEXTIN_ENABLED=True and configure TEXTIN credentials.",
            (
                ("TEXTIN_APP_ID", "TextIn parser requires TEXTIN_APP_ID."),
                ("TEXTIN_SECRET_CODE", "TextIn parser requires TEXTIN_SECRET_CODE."),
            ),
        ),
        "deepseek_ocr": (
            "DEEPSEEK_OCR_ENABLED",
            "DeepSeek OCR parser is not enabled. Please set DEEPSEEK_OCR_ENABLED=True and configure SILICONFLOW_API_KEY.",
            (("SILICONFLOW_API_KEY", "DeepSeek OCR parser requires SILICONFLOW_API_KEY."),),
        ),
        "etl4llm": (
            "ETL4LLM_ENABLED",
            "ETL4LLM parser is not enabled. Please set ETL4LLM_ENABLED=True and configure ETL4LLM_API_URL.",
            (("ETL4LLM_API_URL", "ETL4LLM parser requires ETL4LLM_API_URL."),),
        ),
    }

    NON_PDF_BACKEND_EXTENSION_RULES = {
        "excel": ({".xls", XLSX_EXTENSION}, "excel backend supports only .xls/.xlsx"),
        "docx": ({DOCX_EXTENSION}, "docx backend supports only .docx"),
        "pptx": ({PPTX_EXTENSION}, "pptx backend supports only .pptx"),
        "html": ({HTML_EXTENSION, ".htm"}, "html backend supports only .html/.htm"),
        "csv": ({".csv"}, "csv backend supports only .csv"),
        "json": ({JSON_EXTENSION}, "json backend supports only .json"),
        "email": ({EML_EXTENSION, MSG_EXTENSION}, "email backend supports only .eml/.msg"),
        "image": (IMAGE_EXTENSIONS, f"image backend supports only: {sorted(IMAGE_EXTENSIONS)}"),
        "docling": ({DOCX_EXTENSION}, "docling backend currently supports only .docx (non-PDF)"),
        "deepdoc": ({DOCX_EXTENSION}, "deepdoc backend currently supports only .docx (non-PDF)"),
    }

    PDF_PARSER_SPECS = {
        "marker": ("_marker_parser", "app.parsing.parsers.marker_parser", "MarkerParser", "[pdf] Initializing Marker parser (external service)"),
        "paddle_vl": ("_paddle_vl_parser", "app.parsing.parsers.paddle_vl_parser", "PaddleVLParser", "[pdf] Initializing PaddleOCR-VL parser (external service)"),
        "glm_ocr": ("_glm_ocr_parser", "app.parsing.parsers.glm_ocr_parser", "GlmOCRParser", "[pdf] Initializing GLM-OCR parser (external service)"),
        "olmocr": ("_olmocr_parser", "app.parsing.parsers.olmocr_parser", "OlmocrParser", "[pdf] Initializing olmOCR parser (external service)"),
        "qianfan_ocr": ("_qianfan_ocr_parser", "app.parsing.parsers.qianfan_ocr_parser", "QianfanOCRParser", "[pdf] Initializing Qianfan-OCR parser (external service)"),
        "textin": ("_textin_parser", "app.parsing.parsers.textin_parser", "TextInParser", "[pdf] Initializing TextIn xParse parser (external API)"),
        "mineru": ("_mineru_parser", "app.parsing.parsers.mineru_parser", "MinerUParser", "[pdf] Initializing MinerU parser (advanced)"),
        "deepdoc": ("_deepdoc_parser", "app.parsing.parsers.deepdoc_parser", "DeepDocParser", "[pdf] Initializing DeepDoc parser (structure-aware)"),
        "deepseek_ocr": ("_deepseek_ocr_parser", "app.parsing.parsers.deepseek_ocr_parser", "DeepSeekOCRParser", "[pdf] Initializing DeepSeek OCR parser (SiliconFlow)"),
        "etl4llm": ("_etl4llm_parser", "app.parsing.parsers.etl4llm_parser", "Etl4LlmParser", "[pdf] Initializing ETL4LLM parser (layout-aware)"),
        "markitdown": ("_markitdown_parser", "app.parsing.parsers.markitdown_parser", "MarkItDownParser", "[pdf] Initializing MarkItDown parser (markdown-focused)"),
        "docling": ("_docling_parser", "app.parsing.parsers.docling_parser", "DoclingParser", "[pdf] Initializing Docling parser (structure-aware)"),
        "magicpdf": ("_magicpdf_parser", "app.parsing.parsers.magic_pdf_parser", "MagicPDFParser", "[pdf] Initializing MagicPDF parser (local advanced)"),
    }

    def __init__(self):
        self._initialize_parser_cache()
        self._log_available_parsers()
        self.parsers = self._build_default_parsers()

    def _initialize_parser_cache(self) -> None:
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
        self._colpali_parser: ColPaliParser | None = None
        self._email_parser: EmailParser | None = None
        self._image_parser: ImageParser | None = None
        self._audio_parser: AudioParser | None = None
        self._video_parser: VideoParser | None = None

    @staticmethod
    def _settings_enabled(flag_name: str, *value_names: str) -> bool:
        if not bool(getattr(settings, flag_name, False)):
            return False
        return all(bool((getattr(settings, value_name, "") or "").strip()) for value_name in value_names)

    @staticmethod
    def _mineru_configured() -> bool:
        return bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))

    def _log_available_parsers(self) -> None:
        logger.debug("[pdf] Basic PyMuPDF parser available (lazy)")
        availability_logs = (
            (self._settings_enabled("MARKER_ENABLED", "MARKER_API_URL"), "[pdf] Marker parser available (requires selection)"),
            (self._settings_enabled("PADDLE_VL_ENABLED", "PADDLE_VL_API_URL"), "[pdf] PaddleOCR-VL parser available (requires selection)"),
            (self._settings_enabled("GLM_OCR_ENABLED", "GLM_OCR_API_URL"), "[pdf] GLM-OCR parser available (requires selection)"),
            (self._settings_enabled("OLMOCR_ENABLED", "OLMOCR_API_URL"), "[pdf] olmOCR parser available (requires selection)"),
            (self._settings_enabled("QIANFAN_OCR_ENABLED", "QIANFAN_OCR_API_URL"), "[pdf] Qianfan-OCR parser available (requires selection)"),
            (self._settings_enabled("TEXTIN_ENABLED", "TEXTIN_APP_ID", "TEXTIN_SECRET_CODE"), "[pdf] TextIn parser available (requires selection)"),
            (self._mineru_configured(), "[pdf] MinerU parser available (requires selection)"),
            (bool(settings.DEEPDOC_ENABLED), "[pdf] DeepDoc parser available (requires selection)"),
            (self._settings_enabled("DEEPSEEK_OCR_ENABLED", "SILICONFLOW_API_KEY"), "[pdf] DeepSeek OCR parser available (requires selection)"),
            (self._settings_enabled("ETL4LLM_ENABLED", "ETL4LLM_API_URL"), "[pdf] ETL4LLM parser available (requires selection)"),
            (bool(settings.MARKITDOWN_ENABLED), "[pdf] MarkItDown parser available (requires selection)"),
            (bool(getattr(settings, "DOCLING_ENABLED", False)), "[pdf] Docling parser available (requires selection)"),
            (bool(getattr(settings, "MAGIC_PDF_ENABLED", False)), "[pdf] MagicPDF parser available (requires selection)"),
        )
        for available, message in availability_logs:
            if available:
                logger.debug(message)

    def _build_default_parsers(self) -> dict[str, Any]:
        parsers = {
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
            parsers.setdefault(ext, TextParser())
        return parsers

    @staticmethod
    def _magicpdf_runtime_ready() -> bool:
        if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
            return False
        try:
            from app.parsing.parsers.magic_pdf_parser import magicpdf_service_configured, resolve_magicpdf_models_dir
            from app.parsing.utils.cli import resolve_cli_command

            if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
                return True

            cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
            return bool(
                resolve_cli_command(cli)
                and resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
            )
        except Exception as exc:
            logger.debug("MagicPDF runtime availability check failed: %s", exc)
            return False

    def resolve_backend(self, file_ext: str, parser_backend: str | None) -> str:
        """
        Resolve the actual parser to use based on file type and user selection.
        """
        explicit_backend = bool(str(parser_backend or "").strip())
        normalized = normalize_parser_backend(parser_backend or settings.DEFAULT_PARSER_BACKEND or "auto") or "auto"
        file_ext = file_ext.lower()

        if file_ext != ".pdf":
            return self._resolve_non_pdf_backend(file_ext=file_ext, backend=normalized, explicit_backend=explicit_backend)
        return self._resolve_pdf_backend(normalized)

    def _resolve_non_pdf_backend(self, *, file_ext: str, backend: str, explicit_backend: bool = True) -> str:
        direct_backend = self._direct_non_pdf_backend(file_ext=file_ext, backend=backend)
        if direct_backend:
            return direct_backend
        if file_ext not in self.SUPPORTED_NON_PDF_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_ext}")

        backend = self._normalize_non_pdf_backend(backend)
        if backend in {"", "auto"}:
            return self._resolve_auto_non_pdf_backend(file_ext)

        if not explicit_backend and not self._non_pdf_backend_supports_extension(backend=backend, file_ext=file_ext):
            return self._resolve_auto_non_pdf_backend(file_ext)

        self._validate_non_pdf_backend(backend=backend, file_ext=file_ext)
        return backend

    def _direct_non_pdf_backend(self, *, file_ext: str, backend: str) -> str | None:
        if file_ext in self.PLAIN_TEXT_EXTENSIONS:
            return "text"
        if file_ext == ".md":
            return "markdown"
        if file_ext in {EML_EXTENSION, MSG_EXTENSION}:
            return "email"
        if file_ext in IMAGE_EXTENSIONS:
            return "textin" if backend == "textin" else "image"
        if file_ext in AUDIO_EXTENSIONS:
            return "audio"
        if file_ext in VIDEO_EXTENSIONS:
            return "video"
        if backend == "colpali":
            return "colpali"
        return None

    def _normalize_non_pdf_backend(self, backend: str) -> str:
        if backend in {"", "auto"} or backend in self.SUPPORTED_NON_PDF_BACKENDS:
            return backend
        if backend in self.SUPPORTED_PDF_BACKENDS:
            return "auto"
        return backend

    def _resolve_auto_non_pdf_backend(self, file_ext: str) -> str:
        if file_ext in {EPUB_EXTENSION, RTF_EXTENSION, ODT_EXTENSION}:
            return "pandoc" if bool(getattr(settings, "PANDOC_ENABLED", False)) else "markitdown"
        if file_ext in {XLSX_EXTENSION, ".xls"}:
            return "excel"
        if file_ext in {".doc", ".ppt"}:
            pandoc_with_libreoffice = bool(getattr(settings, "PANDOC_ENABLED", False)) and bool(
                getattr(settings, "LIBREOFFICE_ENABLED", False)
            )
            return "pandoc" if pandoc_with_libreoffice else "markitdown"
        if file_ext in {DOCX_EXTENSION, PPTX_EXTENSION, HTML_EXTENSION, ".htm"}:
            return "pandoc" if bool(getattr(settings, "PANDOC_ENABLED", False)) else "markitdown"
        return "markitdown"

    def _validate_non_pdf_backend(self, *, backend: str, file_ext: str) -> None:
        if backend not in self.SUPPORTED_NON_PDF_BACKENDS:
            raise ValueError(
                f"Unsupported parser backend '{backend}' for {file_ext}. "
                f"Supported: {sorted(self.SUPPORTED_NON_PDF_BACKENDS)}"
            )
        self._validate_non_pdf_extension_rule(backend=backend, file_ext=file_ext)
        if backend == "docling" and not getattr(settings, "DOCLING_ENABLED", False):
            raise ValueError(
                "Docling parser is not enabled. "
                "Please set DOCLING_ENABLED=True."
            )

    def _validate_non_pdf_extension_rule(self, *, backend: str, file_ext: str) -> None:
        rule = self.NON_PDF_BACKEND_EXTENSION_RULES.get(backend)
        if not rule:
            return
        supported_extensions, message = rule
        if file_ext not in supported_extensions:
            raise ValueError(message)

    def _non_pdf_backend_supports_extension(self, *, backend: str, file_ext: str) -> bool:
        rule = self.NON_PDF_BACKEND_EXTENSION_RULES.get(backend)
        if not rule:
            return True
        supported_extensions, _message = rule
        return file_ext in supported_extensions

    def _resolve_pdf_backend(self, backend: str) -> str:
        if backend not in self.SUPPORTED_PDF_BACKENDS:
            raise ValueError(
                f"Unsupported parser backend '{backend}'. "
                f"Supported backends: {sorted(self.SUPPORTED_PDF_BACKENDS)}"
            )
        if backend == "auto":
            return self._resolve_auto_pdf_backend()
        self._validate_pdf_backend(backend)
        return backend

    def _resolve_auto_pdf_backend(self) -> str:
        if getattr(settings, "DOCLING_ENABLED", False):
            return "docling"
        if self._settings_enabled("ETL4LLM_ENABLED", "ETL4LLM_API_URL"):
            return "etl4llm"
        if settings.DEEPDOC_ENABLED:
            return "deepdoc"
        if settings.MARKITDOWN_ENABLED:
            return "markitdown"
        if self._mineru_configured():
            return "mineru"
        if self._magicpdf_runtime_ready():
            return "magicpdf"
        return "basic"

    def _validate_pdf_backend(self, backend: str) -> None:
        if backend in {"basic", "deepdoc", "markitdown", "colpali"}:
            return
        if backend in self.PDF_SETTING_REQUIREMENTS:
            self._validate_pdf_setting_requirements(backend)
            return
        if backend == "mineru":
            self._validate_mineru_backend()
            return
        if backend == "docling":
            self._validate_docling_backend()
            return
        if backend == "magicpdf":
            self._validate_magicpdf_backend()
            return
        raise ValueError(f"Unsupported parser backend '{backend}'")

    def _validate_pdf_setting_requirements(self, backend: str) -> None:
        flag_name, disabled_message, required_values = self.PDF_SETTING_REQUIREMENTS[backend]
        if not bool(getattr(settings, flag_name, False)):
            raise ValueError(disabled_message)
        for value_name, missing_message in required_values:
            if not bool((getattr(settings, value_name, "") or "").strip()):
                raise ValueError(missing_message)

    def _validate_mineru_backend(self) -> None:
        if self._mineru_configured():
            return
        raise ValueError(
            "MinerU parser is not enabled. "
            "Please set MINERU_ENABLED=True and configure MINERU_API_TOKEN (online) "
            "or MINERU_LOCAL_SERVER_URL (local ZIP mode)."
        )

    @staticmethod
    def _validate_docling_backend() -> None:
        if getattr(settings, "DOCLING_ENABLED", False):
            return
        raise ValueError(
            "Docling parser is not enabled. "
            "Please set DOCLING_ENABLED=True."
        )

    def _validate_magicpdf_backend(self) -> None:
        if not getattr(settings, "MAGIC_PDF_ENABLED", False):
            raise ValueError(
                "MagicPDF parser is not enabled. "
                "Please set MAGIC_PDF_ENABLED=True."
            )
        if not self._magicpdf_runtime_ready():
            raise ValueError(
                "MagicPDF parser is not available. "
                "Configure MAGIC_PDF_API_URL for the service mode, or install the magic-pdf CLI "
                "and mount PDF-Extract-Kit models (or set MAGIC_PDF_MODELS_DIR)."
            )

    def _resolve_non_pdf_parser(self, *, backend: str, file_ext: str) -> Any:
        if backend in {"deepdoc", "docling", "textin"}:
            # These parsers are initialized in the PDF backend factory, but can also
            # handle certain non-PDF formats (e.g. DOCX) when explicitly requested.
            return self._get_pdf_parser(backend)

        direct_factories = {
            "markitdown": self._get_markitdown_parser,
            "pandoc": self._get_pandoc_parser,
            "email": self._get_email_parser,
            "image": self._get_image_parser,
            "colpali": self._get_colpali_parser,
            "audio": self._get_audio_parser,
            "video": self._get_video_parser,
        }
        if backend in direct_factories:
            return direct_factories[backend]()

        if backend == "excel":
            from app.parsing.parsers.excel_parser import ExcelParser

            return ExcelParser()
        if backend == "docx":
            from app.parsing.parsers.docx_parser import DocxParser

            return DocxParser()
        if backend == "pptx":
            from app.parsing.parsers.pptx_parser import PptxParser

            return PptxParser()
        if backend == "html":
            from app.parsing.parsers.html_parser import HtmlParser

            return HtmlParser()
        if backend == "csv":
            from app.parsing.parsers.csv_parser import CsvParser

            return CsvParser()
        if backend == "json":
            from app.parsing.parsers.json_parser import JsonParser

            return JsonParser()
        raise ValueError(f"Unsupported parser backend '{backend}' for {file_ext}")

    def _select_parser(self, *, file_ext: str, backend: str) -> Any:
        if file_ext == ".pdf":
            return self._get_pdf_parser(backend)
        if file_ext in self.PLAIN_TEXT_EXTENSIONS:
            return self.parsers[file_ext]
        if file_ext == ".md":
            return self.parsers[".md"]
        if file_ext in self.SUPPORTED_NON_PDF_EXTENSIONS:
            return self._resolve_non_pdf_parser(backend=backend, file_ext=file_ext)
        raise ValueError(f"Unsupported file type: {file_ext}")

    def _parse_with_selected_backend(
        self,
        *,
        parser: Any,
        backend: str,
        file_path: Path,
        dataset_id: str | None,
        document_id: str | None,
        tenant_id: str | None,
        pdf_quality: dict[str, Any] | None,
        html_xpath: str | None,
    ) -> list[Document]:
        if backend in {
            "marker",
            "paddle_vl",
            "glm_ocr",
            "olmocr",
            "qianfan_ocr",
            "textin",
            "mineru",
            "magicpdf",
            "deepseek_ocr",
            "etl4llm",
            "pandoc",
        }:
            return parser.parse(
                file_path,
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=tenant_id,
                pdf_quality=pdf_quality,
            )
        if backend == "html":
            return parser.parse(file_path, html_xpath=html_xpath)  # type: ignore[call-arg]
        return parser.parse(file_path)

    def _parse_backend_documents(
        self,
        *,
        file_path: Path,
        file_ext: str,
        backend: str,
        dataset_id: str | None,
        document_id: str | None,
        tenant_id: str | None,
        pdf_quality: dict[str, Any] | None,
        html_xpath: str | None,
    ) -> list[Document]:
        parser = self._select_parser(file_ext=file_ext, backend=backend)
        return self._parse_with_selected_backend(
            parser=parser,
            backend=backend,
            file_path=file_path,
            dataset_id=dataset_id,
            document_id=document_id,
            tenant_id=tenant_id,
            pdf_quality=pdf_quality,
            html_xpath=html_xpath,
        )

    @staticmethod
    def _apply_document_metadata(documents: list[Document], *, backend: str, filename: str, file_ext: str) -> None:
        for doc in documents:
            meta = dict(doc.metadata or {})
            meta["parser_backend"] = backend
            meta["source"] = filename
            meta.setdefault("filename", filename)
            meta.setdefault("file_type", file_ext.lstrip("."))
            doc.metadata = meta

    @staticmethod
    def _successful_attempt(*, backend: str, started_at: float, documents: list[Document], selected: bool = True) -> dict[str, Any]:
        return {
            "backend": backend,
            "ok": True,
            "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            "documents": int(len(documents or [])),
            "selected": selected,
        }

    @staticmethod
    def _failed_attempt(*, backend: str, started_at: float, error: Exception) -> dict[str, Any]:
        return {
            "backend": backend,
            "ok": False,
            "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            "error_type": error.__class__.__name__,
            "error_message": str(error)[:200],
            "selected": False,
        }

    def _fallback_with_attempt(
        self,
        *,
        file_path: Path,
        file_ext: str,
        backend: str,
        error: Exception,
        html_xpath: str | None,
        attempts: list[dict[str, Any]],
    ) -> tuple[list[Document], str] | None:
        fb_t0 = time.perf_counter()
        fallback_docs, fallback_backend = self._fallback_parse(
            file_path=file_path,
            file_ext=file_ext,
            requested_backend=backend,
            error=error,
            html_xpath=html_xpath,
        )
        if fallback_docs is None:
            return None
        attempt = self._successful_attempt(backend=fallback_backend, started_at=fb_t0, documents=fallback_docs)
        attempt["fallback_from"] = attempts[0].get("backend") if attempts else backend
        attempts.append(attempt)
        return fallback_docs, fallback_backend

    def parse(
        self,
        file_path: Path,
        parser_backend: str | None = None,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,
        pdf_quality: dict[str, Any] | None = None,
        html_xpath: str | None = None,
        allow_fallback: bool = True,
    ) -> tuple[list[Document], str]:
        """
        Automatically select parser based on file type and return Document list and actual parser name
        """
        file_ext = file_path.suffix.lower()
        backend = self.resolve_backend(file_ext, parser_backend)

        try:
            documents = self._parse_backend_documents(
                file_path=file_path,
                file_ext=file_ext,
                backend=backend,
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=tenant_id,
                pdf_quality=pdf_quality,
                html_xpath=html_xpath,
            )
        except Exception as exc:
            if not bool(allow_fallback):
                raise
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

        self._apply_document_metadata(documents, backend=backend, filename=str(file_path.name), file_ext=file_ext)
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

        primary_t0 = time.perf_counter()
        try:
            documents = self._parse_backend_documents(
                file_path=file_path,
                file_ext=file_ext,
                backend=backend,
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=tenant_id,
                pdf_quality=pdf_quality,
                html_xpath=html_xpath,
            )
            attempts.append(self._successful_attempt(backend=backend, started_at=primary_t0, documents=documents))
        except Exception as exc:
            attempts.append(self._failed_attempt(backend=backend, started_at=primary_t0, error=exc))
            fallback = self._fallback_with_attempt(
                file_path=file_path,
                file_ext=file_ext,
                backend=backend,
                error=exc,
                html_xpath=html_xpath,
                attempts=attempts,
            )
            if fallback is None:
                raise
            documents, backend = fallback

        self._apply_document_metadata(documents, backend=backend, filename=str(file_path.name), file_ext=file_ext)

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

        if file_ext == ".pdf" and backend in self.PDF_ADVANCED_FALLBACK_BACKENDS:
            return self._fallback_pdf_parse(file_path=file_path, backend=backend, error=error)
        if file_ext == DOCX_EXTENSION and backend in self.DOCX_ADVANCED_FALLBACK_BACKENDS:
            return self._fallback_docx_parse(file_path=file_path, backend=backend, error=error)
        if backend == "markitdown":
            return self._fallback_markitdown_parse(
                file_path=file_path,
                file_ext=file_ext,
                backend=backend,
                error=error,
                html_xpath=html_xpath,
            )
        if backend == "excel":
            return self._fallback_to_markitdown(
                file_path=file_path,
                file_ext=file_ext,
                backend=backend,
                error=error,
                failed_backend_label="Excel parser",
            )
        if backend == "pandoc":
            return self._fallback_pandoc_parse(file_path=file_path, file_ext=file_ext, backend=backend, error=error)

        return None, backend

    def _fallback_pdf_parse(
        self,
        *,
        file_path: Path,
        backend: str,
        error: Exception,
    ) -> tuple[list[Document] | None, str]:
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

    def _fallback_docx_parse(
        self,
        *,
        file_path: Path,
        backend: str,
        error: Exception,
    ) -> tuple[list[Document] | None, str]:
        logger.warning(
            "[parse] DOCX backend '%s' failed for %s: %s; falling back to office converters",
            backend,
            str(file_path.name),
            str(error)[:200],
        )
        pandoc_result = self._try_docx_pandoc_fallback(file_path)
        if pandoc_result is not None:
            return pandoc_result

        try:
            return self._get_markitdown_parser().parse(file_path), "markitdown"
        except Exception as fallback_exc:
            logger.warning(
                "[parse] MarkItDown fallback also failed for %s: %s",
                str(file_path.name),
                str(fallback_exc)[:200],
            )
            return self._try_docx_lightweight_fallback(file_path, backend)

    def _try_docx_pandoc_fallback(self, file_path: Path) -> tuple[list[Document], str] | None:
        if not bool(getattr(settings, "PANDOC_ENABLED", False)):
            return None
        try:
            return self._get_pandoc_parser().parse(file_path), "pandoc"
        except Exception as fallback_exc:
            logger.warning(
                "[parse] Pandoc fallback also failed for %s: %s",
                str(file_path.name),
                str(fallback_exc)[:200],
            )
            return None

    @staticmethod
    def _try_docx_lightweight_fallback(file_path: Path, backend: str) -> tuple[list[Document] | None, str]:
        try:
            from app.parsing.parsers.docx_parser import DocxParser

            return DocxParser().parse(file_path), "docx"
        except Exception:
            return None, backend

    def _fallback_markitdown_parse(
        self,
        *,
        file_path: Path,
        file_ext: str,
        backend: str,
        error: Exception,
        html_xpath: str | None,
    ) -> tuple[list[Document] | None, str]:
        logger.warning(
            "[parse] MarkItDown failed for %s (%s): %s",
            str(file_path.name),
            file_ext,
            str(error)[:200],
        )
        try:
            return self._markitdown_fallback_result(file_path=file_path, file_ext=file_ext, html_xpath=html_xpath)
        except Exception as fallback_exc:
            logger.warning(
                "[parse] Fallback parser also failed for %s: %s",
                str(file_path.name),
                str(fallback_exc)[:200],
            )
            return None, backend

    def _markitdown_fallback_result(
        self,
        *,
        file_path: Path,
        file_ext: str,
        html_xpath: str | None,
    ) -> tuple[list[Document] | None, str]:
        if file_ext == DOCX_EXTENSION:
            return self._parse_docx_file(file_path), "docx"
        if file_ext == PPTX_EXTENSION:
            return self._parse_pptx_markitdown_fallback(file_path)
        if file_ext in {XLSX_EXTENSION, ".xls"}:
            return self._parse_excel_file(file_path), "excel"
        if file_ext in {HTML_EXTENSION, ".htm"}:
            return self._parse_html_file(file_path, html_xpath=html_xpath), "html"
        if file_ext == ".csv":
            return self._parse_csv_file(file_path), "csv"
        if file_ext == JSON_EXTENSION:
            return self._parse_json_file(file_path), "json"
        if file_ext in {EPUB_EXTENSION, RTF_EXTENSION, ODT_EXTENSION}:
            return self._parse_extended_office_fallback(file_path)
        if file_ext in {".doc", ".ppt"}:
            return self._try_legacy_office_pandoc_fallback(file_path)
        if file_ext == ".pdf":
            return self._get_pdf_parser("basic").parse(file_path), "basic"
        return None, "markitdown"

    def _parse_pptx_markitdown_fallback(self, file_path: Path) -> tuple[list[Document], str]:
        if bool(getattr(settings, "PANDOC_ENABLED", False)):
            return self._get_pandoc_parser().parse(file_path), "pandoc"
        return self._parse_pptx_file(file_path), "pptx"

    def _parse_extended_office_fallback(self, file_path: Path) -> tuple[list[Document] | None, str]:
        if bool(getattr(settings, "PANDOC_ENABLED", False)):
            return self._get_pandoc_parser().parse(file_path), "pandoc"
        return None, "markitdown"

    @staticmethod
    def _try_legacy_office_pandoc_fallback(file_path: Path) -> tuple[list[Document] | None, str]:
        from app.parsing.parsers.pandoc_parser import PandocParser

        try:
            return PandocParser(force_enabled=True, force_libreoffice=True).parse(file_path), "pandoc"
        except Exception as exc:
            logger.warning(
                "[parse] Legacy Office Pandoc fallback also failed for %s: %s",
                str(file_path.name),
                str(exc)[:200],
            )
            return None, "markitdown"

    @staticmethod
    def _parse_docx_file(file_path: Path) -> list[Document]:
        from app.parsing.parsers.docx_parser import DocxParser

        return DocxParser().parse(file_path)

    @staticmethod
    def _parse_pptx_file(file_path: Path) -> list[Document]:
        from app.parsing.parsers.pptx_parser import PptxParser

        return PptxParser().parse(file_path)

    @staticmethod
    def _parse_excel_file(file_path: Path) -> list[Document]:
        from app.parsing.parsers.excel_parser import ExcelParser

        return ExcelParser().parse(file_path)

    @staticmethod
    def _parse_html_file(file_path: Path, *, html_xpath: str | None) -> list[Document]:
        from app.parsing.parsers.html_parser import HtmlParser

        return HtmlParser().parse(file_path, html_xpath=html_xpath)

    @staticmethod
    def _parse_csv_file(file_path: Path) -> list[Document]:
        from app.parsing.parsers.csv_parser import CsvParser

        return CsvParser().parse(file_path)

    @staticmethod
    def _parse_json_file(file_path: Path) -> list[Document]:
        from app.parsing.parsers.json_parser import JsonParser

        return JsonParser().parse(file_path)

    def _fallback_to_markitdown(
        self,
        *,
        file_path: Path,
        file_ext: str,
        backend: str,
        error: Exception,
        failed_backend_label: str,
    ) -> tuple[list[Document] | None, str]:
        logger.warning(
            "[parse] %s failed for %s (%s): %s",
            failed_backend_label,
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

    def _fallback_pandoc_parse(
        self,
        *,
        file_path: Path,
        file_ext: str,
        backend: str,
        error: Exception,
    ) -> tuple[list[Document] | None, str]:
        fallback_docs, fallback_backend = self._fallback_to_markitdown(
            file_path=file_path,
            file_ext=file_ext,
            backend=backend,
            error=error,
            failed_backend_label="Pandoc",
        )
        if fallback_docs is not None:
            return fallback_docs, fallback_backend
        return self._fallback_parse(file_path=file_path, file_ext=file_ext, requested_backend="markitdown", error=error)

    def _get_pdf_parser(self, backend: str):
        if backend == "basic":
            return self._get_basic_pdf_parser()
        spec = self.PDF_PARSER_SPECS.get(backend)
        if spec is None:
            raise ValueError(f"Unsupported PDF parser backend '{backend}'")
        return self._get_cached_parser(*spec)

    def _get_basic_pdf_parser(self):
        if self._basic_pdf_parser is None:
            from app.parsing.parsers.pdf_parser import PDFParser

            logger.debug("[pdf] Initializing PyMuPDF parser (basic)")
            self._basic_pdf_parser = PDFParser()
        else:
            # Keep the lazy-import contract observable in tests that clear `sys.modules["fitz"]`
            # after previous parser initialization.
            try:
                importlib.import_module("fitz")
            except Exception as exc:
                logger.debug("[pdf] Ignoring PyMuPDF lazy import probe failure: %s", exc)
        return self._basic_pdf_parser

    def _get_cached_parser(
        self,
        cache_attr: str,
        module_name: str,
        class_name: str,
        log_message: str,
    ) -> Any:
        parser = getattr(self, cache_attr)
        if parser is None:
            module = importlib.import_module(module_name)
            logger.info(log_message)
            parser = getattr(module, class_name)()
            setattr(self, cache_attr, parser)
        return parser

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

    def _get_colpali_parser(self):
        """Lazy init ColPali visual parser scaffold."""
        if self._colpali_parser is None:
            from app.parsing.parsers.colpali_parser import ColPaliParser

            logger.info("[colpali] Initializing parser scaffold")
            self._colpali_parser = ColPaliParser()
        return self._colpali_parser

    def _get_audio_parser(self):
        """Lazy init Audio parser for standalone audio files."""
        if self._audio_parser is None:
            from app.parsing.parsers.audio_parser import AudioParser

            logger.info("[audio] Initializing parser for audio files")
            self._audio_parser = AudioParser()
        return self._audio_parser

    def _get_video_parser(self):
        """Lazy init Video parser for standalone video files."""
        if self._video_parser is None:
            from app.parsing.parsers.video_parser import VideoParser

            logger.info("[video] Initializing parser for video files")
            self._video_parser = VideoParser()
        return self._video_parser


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
