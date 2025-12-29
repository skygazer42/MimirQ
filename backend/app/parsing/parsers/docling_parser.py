"""
Docling 文档解析器（业务层封装）

封装 deepdoc/parser/docling_parser.py 的底层实现，
提供 LangChain Document 格式的输出。

支持：
- 结构感知 PDF 解析
- 表格结构化提取
- 图片提取
- 多格式支持 (PDF, DOCX, PPTX, HTML 等)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from app.core.config import settings
from .base_parser import BaseAdvancedParser


# Configuration
DOCLING_ENABLED = getattr(settings, "DOCLING_ENABLED", False)
DOCLING_OCR_ENABLED = getattr(settings, "DOCLING_OCR_ENABLED", True)
DOCLING_TABLE_MODE = getattr(settings, "DOCLING_TABLE_MODE", "markdown")


class DoclingParser(BaseAdvancedParser):
    """
    Docling 文档解析器（业务层封装）

    调用 deepdoc/parser/docling_parser.py 底层实现，
    将 sections/tables 转换为 LangChain Document 格式。
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
        初始化 Docling 解析器。

        Args:
            ocr_enabled: 启用 OCR 识别扫描文档
            table_mode: 表格输出格式 (markdown, html, plain)
            extract_images: 提取图片
            max_pages: 最大处理页数 (None = 全部)
        """
        self.ocr_enabled = ocr_enabled
        self.table_mode = table_mode
        self.extract_images = extract_images
        self.max_pages = max_pages
        super().__init__()

    def _get_parser_name(self) -> str:
        return "docling"

    def _create_parser(self) -> Any:
        from app.deepdoc.parser.docling_parser import DoclingParser as DeepDocDoclingParser
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
