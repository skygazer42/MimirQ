"""
Docling document parser (business layer wrapper)

Wraps the underlying implementation in deepdoc/parser/docling_parser.py,
providing LangChain Document format output.

Supports:
- Structure-aware PDF parsing
- Table structure extraction
- Image extraction
- Multiple formats (PDF, DOCX, PPTX, HTML, etc.)
"""


from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple
from app.deepdoc.parser.docling_parser import DoclingParser as DeepDocDoclingParser
from app.core.config import settings
from .base_parser import BaseAdvancedParser


# Configuration
DOCLING_ENABLED = getattr(settings, "DOCLING_ENABLED", False)
DOCLING_OCR_ENABLED = getattr(settings, "DOCLING_OCR_ENABLED", True)
DOCLING_TABLE_MODE = getattr(settings, "DOCLING_TABLE_MODE", "markdown")


class DoclingParser(BaseAdvancedParser):
    """
    Docling document parser (business layer wrapper)

    Calls the underlying implementation in deepdoc/parser/docling_parser.py,
    converting sections/tables to LangChain Document format.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".html", ".md", ".asciidoc"}

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_mode: str = "markdown",
        extract_images: bool = False,
        max_pages: Optional[int] = None,
    ):
        """
        Initialize Docling parser.

        Args:
            ocr_enabled: Enable OCR for scanned documents
            table_mode: Table output format (markdown, html, plain)
            extract_images: Extract images
            max_pages: Maximum pages to process (None = all)
        """
        self.ocr_enabled = ocr_enabled
        self.table_mode = table_mode
        self.extract_images = extract_images
        self.max_pages = max_pages
        super().__init__()

    def _get_parser_name(self) -> str:
        return "docling"

    def _create_parser(self) -> Any:

        return DeepDocDoclingParser()

    def _check_parser_installation(self, parser: Any) -> Tuple[bool, str]:
        ok = parser.check_installation()
        return (ok, "" if ok else "Docling not installed")

    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> Tuple[List, List]:
        return parser.parse_pdf(
            filepath=str(file_path),
            binary=binary,
            callback=callback,
            delete_output=True,
            **kwargs
        )
