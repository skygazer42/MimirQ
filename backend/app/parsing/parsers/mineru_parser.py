"""
MinerU PDF 解析器（业务层封装）

封装 deepdoc/parser/mineru_parser.py 的底层实现，
提供 LangChain Document 格式的输出。

支持：
- 表格识别和提取
- 图片识别和描述
- 公式识别
- 复杂版面分析
"""
import os
from pathlib import Path
from typing import Any, Callable, List, Tuple

from app.core.config import settings
from .base_parser import BaseAdvancedParser


class MinerUParser(BaseAdvancedParser):
    """
    MinerU 高级 PDF 解析器（业务层封装）

    调用 deepdoc/parser/mineru_parser.py 底层实现，
    将 sections/tables 转换为 LangChain Document 格式。
    """

    def __init__(self):
        self._api = os.environ.get("MINERU_APISERVER", getattr(settings, "MINERU_APISERVER", ""))
        self._server_url = os.environ.get("MINERU_SERVER_URL", getattr(settings, "MINERU_SERVER_URL", ""))
        super().__init__()

    def _get_parser_name(self) -> str:
        return "mineru"

    def _create_parser(self) -> Any:
        from app.deepdoc.parser.mineru_parser import MinerUParser as DeepDocMinerUParser
        return DeepDocMinerUParser(
            mineru_api=self._api,
            mineru_server_url=self._server_url
        )

    def _check_parser_installation(self, parser: Any) -> Tuple[bool, str]:
        return parser.check_installation()

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
            backend=os.environ.get("MINERU_BACKEND", "pipeline"),
            server_url=self._server_url,
            delete_output=True,
            **kwargs
        )
