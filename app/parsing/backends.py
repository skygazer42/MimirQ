"""
Parser backend normalization helpers.

We accept a few common aliases from UI / env / user input and map them to the
canonical backend names used internally.
"""



_BACKEND_ALIASES: dict[str, str] = {
    # PyMuPDF basic parser aliases
    "pymupdf": "basic",
    "fitz": "basic",
    # MagicPDF (PyPI: magic-pdf, module: magic_pdf, CLI: magic-pdf)
    "magic-pdf": "magicpdf",
    "magicpdf": "magicpdf",
    # DeepSeek OCR (SiliconFlow)
    "deepseek-ocr": "deepseek_ocr",
    "deepseekocr": "deepseek_ocr",
    # Qianfan OCR
    "qianfan-ocr": "qianfan_ocr",
    "qianfanocr": "qianfan_ocr",
    # TextIn xParse
    "textin": "textin",
    "textin-xparse": "textin",
    "textinxparse": "textin",
    # ETL4LLM (layout/table/image-aware parsing service)
    "etl4llm": "etl4llm",
    "etl-4llm": "etl4llm",
    # Pandoc (Office/HTML -> Markdown)
    "pandoc": "pandoc",
    "pan-doc": "pandoc",
    # Marker (PDF -> Markdown external service)
    "marker": "marker",
    "marker-pdf": "marker",
    # PaddleOCR-VL (PDF -> Markdown external service)
    "paddle-vl": "paddle_vl",
    "paddleocr-vl": "paddle_vl",
    "paddleocrvl": "paddle_vl",
    # GLM-OCR (PDF -> Markdown external service)
    "glm-ocr": "glm_ocr",
    "glmocr": "glm_ocr",
    # olmOCR (PDF -> Markdown external service)
    "olmocr": "olmocr",
    "olm-ocr": "olmocr",
    "olmocr-pdf": "olmocr",
    # Backward-compatible aliases (deprecated)
    "bisheng-unstructured": "etl4llm",
    "bishengunstructured": "etl4llm",
    "bisheng": "etl4llm",
}


def normalize_parser_backend(value: str | None) -> str:
    """
    Normalize user-facing backend values into our canonical identifiers.

    Examples:
    - "magic-pdf" / "magic_pdf" -> "magicpdf"
    - "pymupdf" -> "basic"
    """
    text = (value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("_", "-")
    return _BACKEND_ALIASES.get(text, text)
