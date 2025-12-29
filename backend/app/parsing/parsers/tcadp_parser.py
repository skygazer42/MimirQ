"""
腾讯云 ADP 文档解析器（业务层封装）
封装 deepdoc/parser/tcadp_parser.py 的底层实现，
提供 LangChain Document 格式的输出。

支持：
- PDF 文档解析
- 表格识别
- 公式识别
- 多种输出格式
"""

from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from app.core.config import settings
from .base_parser import BaseAdvancedParser


class TCADPParser(BaseAdvancedParser):
    """
    腾讯云 ADP 文档解析器（业务层封装）

    调用 deepdoc/parser/tcadp_parser.py 底层实现，
    将 sections/tables 转换为 LangChain Document 格式。
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv"}

    def __init__(
        self,
        secret_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "ap-guangzhou",
        table_result_type: str = "1",
        markdown_image_response_type: str = "1",
    ):
        """
        初始化腾讯云 ADP 解析器。

        Args:
            secret_id: 腾讯云 SecretId
            secret_key: 腾讯云 SecretKey
            region: 区域 (默认 ap-guangzhou)
            table_result_type: 表格输出类型
            markdown_image_response_type: 图片响应类型
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

    def _check_parser_installation(self, parser: Any) -> Tuple[bool, str]:
        ok = parser.check_installation()
        return (ok, "" if ok else "TCADP not configured")

    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> Tuple[List, List]:
        # 确定文件类型
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
