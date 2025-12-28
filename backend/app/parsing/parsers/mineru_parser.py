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
from typing import List, Optional

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("parsing.mineru_parser")


class MinerUParser:
    """
    MinerU 高级 PDF 解析器（业务层封装）

    调用 deepdoc/parser/mineru_parser.py 底层实现，
    将 sections/tables 转换为 LangChain Document 格式。
    """

    def __init__(self):
        self._parser = None
        self._api = os.environ.get("MINERU_APISERVER", getattr(settings, "MINERU_APISERVER", ""))
        self._server_url = os.environ.get("MINERU_SERVER_URL", getattr(settings, "MINERU_SERVER_URL", ""))

    def _get_parser(self):
        """延迟加载底层解析器"""
        if self._parser is not None:
            return self._parser

        from app.deepdoc.parser.mineru_parser import MinerUParser as DeepDocMinerUParser
        self._parser = DeepDocMinerUParser(
            mineru_api=self._api,
            mineru_server_url=self._server_url
        )
        return self._parser

    def check_installation(self) -> bool:
        """检查 MinerU 是否可用"""
        parser = self._get_parser()
        ok, reason = parser.check_installation()
        if not ok:
            logger.warning(f"MinerU check failed: {reason}")
        return ok

    def parse(
        self,
        file_path: Path,
        dataset_id: Optional[str] = None,
        document_id: Optional[str] = None,
        **kwargs
    ) -> List[Document]:
        """
        使用 MinerU 解析 PDF 文档。

        Args:
            file_path: PDF 文件路径
            dataset_id: 知识库 ID（可选）
            document_id: 文档 ID（可选）
            **kwargs: 传递给底层解析器的额外参数

        Returns:
            LangChain Document 列表
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        parser = self._get_parser()

        # 检查安装
        ok, reason = parser.check_installation()
        if not ok:
            raise RuntimeError(f"MinerU not available: {reason}")

        # 读取文件
        with open(file_path, "rb") as f:
            binary = f.read()

        # 调用底层解析器
        def callback(progress, msg):
            logger.info(f"[MinerU] {progress:.0%} - {msg}")

        sections, tables = parser.parse_pdf(
            filepath=str(file_path),
            binary=binary,
            callback=callback,
            backend=os.environ.get("MINERU_BACKEND", "pipeline"),
            server_url=self._server_url,
            delete_output=True,
            **kwargs
        )

        # 转换为 LangChain Document 格式
        documents = []
        base_metadata = {
            "source": str(file_path),
            "filename": file_path.name,
            "parser": "mineru",
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
                        # (image, html) 格式
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

        logger.info(f"MinerU parsed {file_path.name}: {len(documents)} documents")
        return documents

    async def aparse(
        self,
        file_path: Path,
        **kwargs,
    ) -> List[Document]:
        """异步解析"""
        import asyncio
        return await asyncio.to_thread(self.parse, file_path, **kwargs)
