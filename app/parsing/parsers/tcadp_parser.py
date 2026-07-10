"""
Tencent Cloud ADP document parser (service-layer wrapper).
Wraps deepdoc/parser/tcadp_parser.py and outputs LangChain Documents.

Supports:
- PDF parsing
- Table recognition
- Formula recognition
- Multiple output formats
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings

from .base_parser import BaseAdvancedParser


class TCADPParser(BaseAdvancedParser):
    """
    Convert sections/tables into LangChain Documents.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv"}

    def __init__(
        self,
        secret_id: str | None = None,
        secret_key: str | None = None,
        region: str = "ap-guangzhou",
        table_result_type: str = "1",
        markdown_image_response_type: str = "1",
    ):
        """
        Initialize Tencent Cloud ADP parser.

        Args:
            secret_id: Tencent Cloud SecretId.
            secret_key: Tencent Cloud SecretKey.
            region: Region (default ap-guangzhou).
            table_result_type: Table output type.
            markdown_image_response_type: Image response type.
        """
        self.secret_id = secret_id or getattr(settings, "TCADP_SECRET_ID", "")
        self.secret_key = secret_key or getattr(settings, "TCADP_SECRET_KEY", "")
        self.region = region
        self.table_result_type = table_result_type
        self.markdown_image_response_type = markdown_image_response_type
        super().__init__()

    def _get_parser_name(self) -> str:
        return "tcadp"

    def _create_parser(self) -> Any:
        from app.deepdoc.parser.tcadp_parser import TCADPParser as DeepDocTCADPParser

        return DeepDocTCADPParser(
            secret_id=self.secret_id,
            secret_key=self.secret_key,
            region=self.region,
            table_result_type=self.table_result_type,
            markdown_image_response_type=self.markdown_image_response_type,
        )

    def _check_parser_installation(self, parser: Any) -> tuple[bool, str]:
        ok = parser.check_installation()
        return (ok, "" if ok else "TCADP not configured")

    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes | None,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> tuple[list, list]:
        # Determine file type.
        suffix = file_path.suffix.lower()
        file_type_map = {
            ".pdf": "PDF",
            ".xlsx": "XLSX",
            ".xls": "XLSX",
            ".csv": "CSV",
            ".docx": "DOCX",
        }
        file_type = file_type_map.get(suffix, "PDF")

        return parser.parse_pdf(
            filepath=str(file_path),
            binary=binary,
            callback=callback,
            file_type=file_type,
            **kwargs
        )
