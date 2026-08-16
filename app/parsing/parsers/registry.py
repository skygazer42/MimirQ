"""Static parser registry.

The registry is data-only: it describes parser exports and backend families
without importing parser implementations.
"""


from dataclasses import dataclass
from importlib import import_module

from app.parsing.backends import _BACKEND_ALIASES

DOCX_EXTENSION = ".docx"
PPTX_EXTENSION = ".pptx"
XLSX_EXTENSION = ".xlsx"
HTML_EXTENSIONS = (".html", ".htm")
JSON_EXTENSION = ".json"
EMAIL_EXTENSIONS = (".eml", ".msg")
IMAGE_EXTENSIONS = (".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp")
AUDIO_EXTENSIONS = (".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav")
VIDEO_EXTENSIONS = (".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm")


@dataclass(frozen=True)
class ParserExport:
    export_name: str
    module_name: str
    class_name: str
    backend_name: str


@dataclass(frozen=True)
class ParserBackendFamily:
    canonical_name: str
    aliases: tuple[str, ...]
    tier: str
    category: str
    lazy_modules: tuple[str, ...]
    supports_pdf: bool = False
    supports_non_pdf: bool = False
    user_selectable: bool = True
    implicit_only: bool = False
    reuse_pdf_parser_for_non_pdf: bool = False
    pdf_factory_getter_name: str | None = None
    pdf_cache_attr: str | None = None
    parser_module_name: str | None = None
    parser_class_name: str | None = None
    init_log_message: str | None = None
    non_pdf_factory_getter_name: str | None = None
    non_pdf_constructor_module_name: str | None = None
    non_pdf_constructor_class_name: str | None = None
    non_pdf_extensions: tuple[str, ...] = ()
    non_pdf_extension_error: str | None = None
    pdf_required_setting_flag: str | None = None
    pdf_disabled_message: str | None = None
    pdf_required_settings: tuple[tuple[str, str], ...] = ()
    pdf_validation_kind: str | None = None
    pdf_advanced_fallback: bool = False
    docx_advanced_fallback: bool = False


def _aliases_for(canonical_name: str, *extra_aliases: str) -> tuple[str, ...]:
    aliases: list[str] = []

    def _add(alias: str) -> None:
        token = str(alias or "").strip().lower()
        if token and token not in aliases:
            aliases.append(token)

    _add(canonical_name)
    for alias in extra_aliases:
        _add(alias)
    for alias, resolved in _BACKEND_ALIASES.items():
        if resolved == canonical_name:
            _add(alias)
    return tuple(aliases)


_EXPORTS: tuple[ParserExport, ...] = (
    ParserExport("MinerUParser", "app.parsing.parsers.mineru_parser", "MinerUParser", "mineru"),
    ParserExport("DoclingParser", "app.parsing.parsers.docling_parser", "DoclingParser", "docling"),
    ParserExport("TCADPParser", "app.parsing.parsers.tcadp_parser", "TCADPParser", "tcadp"),
    ParserExport("Etl4LlmParser", "app.parsing.parsers.etl4llm_parser", "Etl4LlmParser", "etl4llm"),
)

_BACKEND_FAMILIES: tuple[ParserBackendFamily, ...] = (
    ParserBackendFamily(
        canonical_name="auto",
        aliases=_aliases_for("auto"),
        tier="default",
        category="router",
        lazy_modules=(),
        supports_pdf=True,
        supports_non_pdf=True,
    ),
    ParserBackendFamily(
        canonical_name="basic",
        aliases=_aliases_for("basic"),
        tier="default",
        category="pdf_local",
        lazy_modules=("app.parsing.parsers.pdf_parser",),
        supports_pdf=True,
        pdf_factory_getter_name="_get_basic_pdf_parser",
    ),
    ParserBackendFamily(
        canonical_name="marker",
        aliases=_aliases_for("marker"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.marker_parser",),
        supports_pdf=True,
        pdf_cache_attr="_marker_parser",
        parser_module_name="app.parsing.parsers.marker_parser",
        parser_class_name="MarkerParser",
        init_log_message="[pdf] Initializing Marker parser (external service)",
        pdf_required_setting_flag="MARKER_ENABLED",
        pdf_disabled_message="Marker parser is not enabled. Please set MARKER_ENABLED=True and configure MARKER_API_URL.",
        pdf_required_settings=(("MARKER_API_URL", "Marker parser requires MARKER_API_URL."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="paddle_vl",
        aliases=_aliases_for("paddle_vl"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.paddle_vl_parser",),
        supports_pdf=True,
        pdf_cache_attr="_paddle_vl_parser",
        parser_module_name="app.parsing.parsers.paddle_vl_parser",
        parser_class_name="PaddleVLParser",
        init_log_message="[pdf] Initializing PaddleOCR-VL parser (external service)",
        pdf_required_setting_flag="PADDLE_VL_ENABLED",
        pdf_disabled_message="PaddleOCR-VL parser is not enabled. Please set PADDLE_VL_ENABLED=True and configure PADDLE_VL_API_URL.",
        pdf_required_settings=(("PADDLE_VL_API_URL", "PaddleOCR-VL parser requires PADDLE_VL_API_URL."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="glm_ocr",
        aliases=_aliases_for("glm_ocr"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.glm_ocr_parser",),
        supports_pdf=True,
        pdf_cache_attr="_glm_ocr_parser",
        parser_module_name="app.parsing.parsers.glm_ocr_parser",
        parser_class_name="GlmOCRParser",
        init_log_message="[pdf] Initializing GLM-OCR parser (external service)",
        pdf_required_setting_flag="GLM_OCR_ENABLED",
        pdf_disabled_message="GLM-OCR parser is not enabled. Please set GLM_OCR_ENABLED=True and configure GLM_OCR_API_URL.",
        pdf_required_settings=(("GLM_OCR_API_URL", "GLM-OCR parser requires GLM_OCR_API_URL."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="olmocr",
        aliases=_aliases_for("olmocr"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.olmocr_parser",),
        supports_pdf=True,
        pdf_cache_attr="_olmocr_parser",
        parser_module_name="app.parsing.parsers.olmocr_parser",
        parser_class_name="OlmocrParser",
        init_log_message="[pdf] Initializing olmOCR parser (external service)",
        pdf_required_setting_flag="OLMOCR_ENABLED",
        pdf_disabled_message="olmOCR parser is not enabled. Please set OLMOCR_ENABLED=True and configure OLMOCR_API_URL.",
        pdf_required_settings=(("OLMOCR_API_URL", "olmOCR parser requires OLMOCR_API_URL."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="qianfan_ocr",
        aliases=_aliases_for("qianfan_ocr"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.qianfan_ocr_parser",),
        supports_pdf=True,
        pdf_cache_attr="_qianfan_ocr_parser",
        parser_module_name="app.parsing.parsers.qianfan_ocr_parser",
        parser_class_name="QianfanOCRParser",
        init_log_message="[pdf] Initializing Qianfan-OCR parser (external service)",
        pdf_required_setting_flag="QIANFAN_OCR_ENABLED",
        pdf_disabled_message="Qianfan-OCR parser is not enabled. Please set QIANFAN_OCR_ENABLED=True and configure QIANFAN_OCR_API_URL.",
        pdf_required_settings=(("QIANFAN_OCR_API_URL", "Qianfan-OCR parser requires QIANFAN_OCR_API_URL."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="textin",
        aliases=_aliases_for("textin"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.textin_parser",),
        supports_pdf=True,
        supports_non_pdf=True,
        reuse_pdf_parser_for_non_pdf=True,
        pdf_cache_attr="_textin_parser",
        parser_module_name="app.parsing.parsers.textin_parser",
        parser_class_name="TextInParser",
        init_log_message="[pdf] Initializing TextIn xParse parser (external API)",
        pdf_required_setting_flag="TEXTIN_ENABLED",
        pdf_disabled_message="TextIn parser is not enabled. Please set TEXTIN_ENABLED=True and configure TEXTIN credentials.",
        pdf_required_settings=(
            ("TEXTIN_APP_ID", "TextIn parser requires TEXTIN_APP_ID."),
            ("TEXTIN_SECRET_CODE", "TextIn parser requires TEXTIN_SECRET_CODE."),
        ),
        pdf_advanced_fallback=True,
        docx_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="mineru",
        aliases=_aliases_for("mineru"),
        tier="optional",
        category="advanced_pdf",
        lazy_modules=("app.parsing.parsers.mineru_parser",),
        supports_pdf=True,
        pdf_cache_attr="_mineru_parser",
        parser_module_name="app.parsing.parsers.mineru_parser",
        parser_class_name="MinerUParser",
        init_log_message="[pdf] Initializing MinerU parser (advanced)",
        pdf_validation_kind="mineru",
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="deepdoc",
        aliases=_aliases_for("deepdoc"),
        tier="optional",
        category="advanced_pdf",
        lazy_modules=("app.parsing.parsers.deepdoc_parser",),
        supports_pdf=True,
        supports_non_pdf=True,
        reuse_pdf_parser_for_non_pdf=True,
        pdf_cache_attr="_deepdoc_parser",
        parser_module_name="app.parsing.parsers.deepdoc_parser",
        parser_class_name="DeepDocParser",
        init_log_message="[pdf] Initializing DeepDoc parser (structure-aware)",
        pdf_advanced_fallback=True,
        docx_advanced_fallback=True,
        non_pdf_extensions=(DOCX_EXTENSION,),
        non_pdf_extension_error="deepdoc backend currently supports only .docx (non-PDF)",
    ),
    ParserBackendFamily(
        canonical_name="deepseek_ocr",
        aliases=_aliases_for("deepseek_ocr"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.deepseek_ocr_parser",),
        supports_pdf=True,
        pdf_cache_attr="_deepseek_ocr_parser",
        parser_module_name="app.parsing.parsers.deepseek_ocr_parser",
        parser_class_name="DeepSeekOCRParser",
        init_log_message="[pdf] Initializing DeepSeek OCR parser (SiliconFlow)",
        pdf_required_setting_flag="DEEPSEEK_OCR_ENABLED",
        pdf_disabled_message="DeepSeek OCR parser is not enabled. Please set DEEPSEEK_OCR_ENABLED=True and configure SILICONFLOW_API_KEY.",
        pdf_required_settings=(("SILICONFLOW_API_KEY", "DeepSeek OCR parser requires SILICONFLOW_API_KEY."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="etl4llm",
        aliases=_aliases_for("etl4llm"),
        tier="optional",
        category="service",
        lazy_modules=("app.parsing.parsers.etl4llm_parser",),
        supports_pdf=True,
        pdf_cache_attr="_etl4llm_parser",
        parser_module_name="app.parsing.parsers.etl4llm_parser",
        parser_class_name="Etl4LlmParser",
        init_log_message="[pdf] Initializing ETL4LLM parser (layout-aware)",
        pdf_required_setting_flag="ETL4LLM_ENABLED",
        pdf_disabled_message="ETL4LLM parser is not enabled. Please set ETL4LLM_ENABLED=True and configure ETL4LLM_API_URL.",
        pdf_required_settings=(("ETL4LLM_API_URL", "ETL4LLM parser requires ETL4LLM_API_URL."),),
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="markitdown",
        aliases=_aliases_for("markitdown"),
        tier="default",
        category="converter",
        lazy_modules=("app.parsing.parsers.markitdown_parser",),
        supports_pdf=True,
        supports_non_pdf=True,
        pdf_cache_attr="_markitdown_parser",
        parser_module_name="app.parsing.parsers.markitdown_parser",
        parser_class_name="MarkItDownParser",
        init_log_message="[pdf] Initializing MarkItDown parser (markdown-focused)",
        non_pdf_factory_getter_name="_get_markitdown_parser",
    ),
    ParserBackendFamily(
        canonical_name="docling",
        aliases=_aliases_for("docling"),
        tier="optional",
        category="advanced_pdf",
        lazy_modules=("app.parsing.parsers.docling_parser",),
        supports_pdf=True,
        supports_non_pdf=True,
        reuse_pdf_parser_for_non_pdf=True,
        pdf_cache_attr="_docling_parser",
        parser_module_name="app.parsing.parsers.docling_parser",
        parser_class_name="DoclingParser",
        init_log_message="[pdf] Initializing Docling parser (structure-aware)",
        pdf_validation_kind="docling",
        pdf_advanced_fallback=True,
        docx_advanced_fallback=True,
        non_pdf_extensions=(DOCX_EXTENSION,),
        non_pdf_extension_error="docling backend currently supports only .docx (non-PDF)",
    ),
    ParserBackendFamily(
        canonical_name="magicpdf",
        aliases=_aliases_for("magicpdf"),
        tier="optional",
        category="advanced_pdf",
        lazy_modules=("app.parsing.parsers.magic_pdf_parser",),
        supports_pdf=True,
        pdf_cache_attr="_magicpdf_parser",
        parser_module_name="app.parsing.parsers.magic_pdf_parser",
        parser_class_name="MagicPDFParser",
        init_log_message="[pdf] Initializing MagicPDF parser (local advanced)",
        pdf_validation_kind="magicpdf",
        pdf_advanced_fallback=True,
    ),
    ParserBackendFamily(
        canonical_name="colpali",
        aliases=_aliases_for("colpali"),
        tier="experimental",
        category="vision",
        lazy_modules=("app.parsing.parsers.colpali_parser",),
        supports_pdf=True,
        supports_non_pdf=True,
        pdf_factory_getter_name="_get_colpali_parser",
        non_pdf_factory_getter_name="_get_colpali_parser",
    ),
    ParserBackendFamily(
        canonical_name="pandoc",
        aliases=_aliases_for("pandoc"),
        tier="optional",
        category="converter",
        lazy_modules=("app.parsing.parsers.pandoc_parser",),
        supports_non_pdf=True,
        non_pdf_factory_getter_name="_get_pandoc_parser",
    ),
    ParserBackendFamily(
        canonical_name="excel",
        aliases=_aliases_for("excel"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.excel_parser",),
        supports_non_pdf=True,
        non_pdf_constructor_module_name="app.parsing.parsers.excel_parser",
        non_pdf_constructor_class_name="ExcelParser",
        non_pdf_extensions=(".xls", XLSX_EXTENSION),
        non_pdf_extension_error="excel backend supports only .xls/.xlsx",
    ),
    ParserBackendFamily(
        canonical_name="docx",
        aliases=_aliases_for("docx"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.docx_parser",),
        supports_non_pdf=True,
        non_pdf_constructor_module_name="app.parsing.parsers.docx_parser",
        non_pdf_constructor_class_name="DocxParser",
        non_pdf_extensions=(DOCX_EXTENSION,),
        non_pdf_extension_error="docx backend supports only .docx",
    ),
    ParserBackendFamily(
        canonical_name="pptx",
        aliases=_aliases_for("pptx"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.pptx_parser",),
        supports_non_pdf=True,
        non_pdf_constructor_module_name="app.parsing.parsers.pptx_parser",
        non_pdf_constructor_class_name="PptxParser",
        non_pdf_extensions=(PPTX_EXTENSION,),
        non_pdf_extension_error="pptx backend supports only .pptx",
    ),
    ParserBackendFamily(
        canonical_name="html",
        aliases=_aliases_for("html"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.html_parser",),
        supports_non_pdf=True,
        non_pdf_constructor_module_name="app.parsing.parsers.html_parser",
        non_pdf_constructor_class_name="HtmlParser",
        non_pdf_extensions=HTML_EXTENSIONS,
        non_pdf_extension_error="html backend supports only .html/.htm",
    ),
    ParserBackendFamily(
        canonical_name="csv",
        aliases=_aliases_for("csv"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.csv_parser",),
        supports_non_pdf=True,
        non_pdf_constructor_module_name="app.parsing.parsers.csv_parser",
        non_pdf_constructor_class_name="CsvParser",
        non_pdf_extensions=(".csv",),
        non_pdf_extension_error="csv backend supports only .csv",
    ),
    ParserBackendFamily(
        canonical_name="json",
        aliases=_aliases_for("json"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.json_parser",),
        supports_non_pdf=True,
        non_pdf_constructor_module_name="app.parsing.parsers.json_parser",
        non_pdf_constructor_class_name="JsonParser",
        non_pdf_extensions=(JSON_EXTENSION,),
        non_pdf_extension_error="json backend supports only .json",
    ),
    ParserBackendFamily(
        canonical_name="email",
        aliases=_aliases_for("email"),
        tier="default",
        category="structured",
        lazy_modules=("app.parsing.parsers.email_parser",),
        supports_non_pdf=True,
        non_pdf_factory_getter_name="_get_email_parser",
        non_pdf_extensions=EMAIL_EXTENSIONS,
        non_pdf_extension_error="email backend supports only .eml/.msg",
    ),
    ParserBackendFamily(
        canonical_name="image",
        aliases=_aliases_for("image"),
        tier="default",
        category="media",
        lazy_modules=("app.parsing.parsers.image_parser",),
        supports_non_pdf=True,
        non_pdf_factory_getter_name="_get_image_parser",
        non_pdf_extensions=IMAGE_EXTENSIONS,
        non_pdf_extension_error=f"image backend supports only: {sorted(IMAGE_EXTENSIONS)}",
    ),
    ParserBackendFamily(
        canonical_name="audio",
        aliases=_aliases_for("audio"),
        tier="default",
        category="media",
        lazy_modules=("app.parsing.parsers.audio_parser",),
        supports_non_pdf=True,
        non_pdf_factory_getter_name="_get_audio_parser",
    ),
    ParserBackendFamily(
        canonical_name="video",
        aliases=_aliases_for("video"),
        tier="default",
        category="media",
        lazy_modules=("app.parsing.parsers.video_parser",),
        supports_non_pdf=True,
        non_pdf_factory_getter_name="_get_video_parser",
    ),
    ParserBackendFamily(
        canonical_name="text",
        aliases=_aliases_for("text"),
        tier="default",
        category="builtin",
        lazy_modules=("app.parsing.parsers.text_parser",),
        supports_non_pdf=True,
        user_selectable=False,
        implicit_only=True,
    ),
    ParserBackendFamily(
        canonical_name="markdown",
        aliases=_aliases_for("markdown"),
        tier="default",
        category="builtin",
        lazy_modules=("app.parsing.parsers.text_parser",),
        supports_non_pdf=True,
        user_selectable=False,
        implicit_only=True,
    ),
)

_EXPORT_BY_NAME = {item.export_name: item for item in _EXPORTS}
_BACKEND_BY_ALIAS = {
    alias: family
    for family in _BACKEND_FAMILIES
    for alias in family.aliases
}


def get_parser_export(name: str) -> ParserExport | None:
    normalized = str(name or "").strip()
    if not normalized:
        return None
    return _EXPORT_BY_NAME.get(normalized)


def iter_parser_exports() -> tuple[ParserExport, ...]:
    return _EXPORTS


def resolve_parser_export(name: str):
    export = get_parser_export(name)
    if export is None:
        raise AttributeError(f"module 'app.parsing.parsers' has no attribute {name!r}")
    return getattr(import_module(export.module_name), export.class_name)


def get_parser_backend_family(backend: str | None) -> ParserBackendFamily | None:
    normalized = str(backend or "").strip().lower()
    if not normalized:
        return None
    return _BACKEND_BY_ALIAS.get(normalized)


def iter_parser_backend_families(*, include_implicit: bool = True) -> tuple[ParserBackendFamily, ...]:
    if include_implicit:
        return _BACKEND_FAMILIES
    return tuple(family for family in _BACKEND_FAMILIES if not family.implicit_only)


def list_registered_parser_backends(*, include_implicit: bool = True) -> list[str]:
    return [family.canonical_name for family in iter_parser_backend_families(include_implicit=include_implicit)]


__all__ = [
    "ParserBackendFamily",
    "ParserExport",
    "get_parser_backend_family",
    "get_parser_export",
    "iter_parser_backend_families",
    "iter_parser_exports",
    "list_registered_parser_backends",
    "resolve_parser_export",
]
