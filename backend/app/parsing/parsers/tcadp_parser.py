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

import logging
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


class TCADPParser:
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
        self._parser = None

    def _get_parser(self):
        """延迟加载底层解析器"""
        if self._parser is not None:
            return self._parser

        from app.deepdoc.parser.tcadp_parser import TCADPParser as DeepDocTCADPParser
        self._parser = DeepDocTCADPParser(
            secret_id=self.secret_id,
            secret_key=self.secret_key,
            region=self.region,
            table_result_type=self.table_result_type,
            markdown_image_response_type=self.markdown_image_response_type,
        )
        return self._parser

    def check_installation(self) -> bool:
        """检查腾讯云 ADP 是否可用"""
        parser = self._get_parser()
        return parser.check_installation()

    def parse(
        self,
        file_path: Path,
        **kwargs,
    ) -> List[Document]:
        """
        使用腾讯云 ADP 解析文档。

        Args:
            file_path: 文档文件路径
            **kwargs: 额外参数

        Returns:
            LangChain Document 列表
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {file_path.suffix}. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        parser = self._get_parser()

        # 检查安装
        if not parser.check_installation():
            raise RuntimeError("TCADP not available, please check Tencent Cloud API configuration")

        # 读取文件
        with open(file_path, "rb") as f:
            binary = f.read()

        # 确定文件类型
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            file_type = "PDF"
        elif suffix in (".xlsx", ".xls"):
            file_type = "XLSX"
        elif suffix == ".csv":
            file_type = "CSV"
        elif suffix == ".docx":
            file_type = "DOCX"
        else:
            file_type = "PDF"

        # 调用底层解析器
        def callback(progress, msg):
            logger.info(f"[TCADP] {progress:.0%} - {msg}")

        sections, tables = parser.parse_pdf(
            filepath=str(file_path),
            binary=binary,
            callback=callback,
            file_type=file_type,
            **kwargs
        )

        # 转换为 LangChain Document 格式
        documents = []
        base_metadata = {
            "source": str(file_path),
            "filename": file_path.name,
            "parser": "tcadp",
        }

        # 合并 sections 为主文档
        if sections:
            text_parts = []
            for section in sections:
                if isinstance(section, tuple):
                    text = section[0] if section[0] else ""
                else:
                    text = str(section)
                if text.strip():
                    text_parts.append(text.strip())

            if text_parts:
                documents.append(Document(
                    page_content="\n\n".join(text_parts),
                    metadata={**base_metadata, "content_type": "text"}
                ))

        # 添加表格作为单独文档
        if tables:
            for i, table in enumerate(tables):
                table_content = ""
                if isinstance(table, tuple) and len(table) >= 1:
                    table_data = table[0]
                    if isinstance(table_data, tuple) and len(table_data) >= 2:
                        table_content = table_data[1] if table_data[1] else ""
                    elif isinstance(table_data, str):
                        table_content = table_data
                else:
                    table_content = str(table)

                if table_content and table_content.strip():
                    documents.append(Document(
                        page_content=table_content,
                        metadata={
                            **base_metadata,
                            "content_type": "table",
                            "table_index": i,
                        }
                    ))

        logger.info(f"TCADP parsed {file_path.name}: {len(documents)} documents")
        return documents

    async def aparse(
        self,
        file_path: Path,
        **kwargs,
    ) -> List[Document]:
        """异步解析"""
        import asyncio
        return await asyncio.to_thread(self.parse, file_path, **kwargs)
