"""
MinerU PDF 解析器（高级）

通过 MinerU 在线 API 进行 PDF 解析，支持：
- 表格识别和提取
- 图片识别和描述
- 公式识别
- 复杂版面分析
"""
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from app.services.mineru_service import mineru_service


class MinerUParser:
    """
    MinerU 高级 PDF 解析器

    使用 MinerU 在线服务进行 PDF 解析，相比 PyMuPDF 提供更强大的功能：
    - 表格结构化提取
    - 图片内容理解
    - 数学公式识别
    - 复杂排版处理
    """

    def parse(self, file_path: Path) -> List[Document]:
        """
        使用 MinerU API 解析 PDF 文档

        Args:
            file_path: PDF 文件路径

        Returns:
            LangChain Document 列表（通常返回单个文档，内容为 Markdown 格式）
        """
        if not mineru_service.enabled:
            raise Exception(
                "MinerU parser is not enabled. "
                "Please set MINERU_ENABLED=True and configure MINERU_API_TOKEN in .env file."
            )

        # 调用 MinerU 服务进行解析
        return mineru_service.parse_file(file_path)
