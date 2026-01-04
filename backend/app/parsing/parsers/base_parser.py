"""
高级解析器基类
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, List, Optional, Set, Tuple

from langchain_core.documents import Document


class BaseAdvancedParser(ABC):
    """
    高级解析器抽象基类

    提供以下公共功能：
    - 延迟加载底层解析器
    - 文件验证
    - sections/tables 转换为 LangChain Document
    - 异步包装

    子类需要实现：
    - _create_parser(): 创建底层解析器实例
    - _get_parser_name(): 返回解析器名称（用于日志和元数据）
    - _check_parser_installation(): 检查解析器是否可用
    - _call_parse_method(): 调用底层解析器的解析方法
    """

    # 子类可覆盖，设为 None 表示不检查扩展名
    SUPPORTED_EXTENSIONS: Optional[Set[str]] = None

    def __init__(self):
        self._parser = None
        self._logger = logging.getLogger(f"parsing.{self._get_parser_name()}_parser")

    def _get_parser(self):
        """延迟加载底层解析器"""
        if self._parser is not None:
            return self._parser
        self._parser = self._create_parser()
        return self._parser

    @abstractmethod
    def _create_parser(self) -> Any:
        """
        创建底层解析器实例

        Returns:
            底层解析器实例
        """
        pass

    @abstractmethod
    def _get_parser_name(self) -> str:
        """
        返回解析器名称（用于日志和元数据）

        Returns:
            解析器名称，如 "mineru", "docling", "tcadp"
        """
        pass

    @abstractmethod
    def _check_parser_installation(self, parser: Any) -> Tuple[bool, str]:
        """
        检查解析器是否可用

        Args:
            parser: 底层解析器实例

        Returns:
            (是否可用, 原因/错误信息)
        """
        pass

    @abstractmethod
    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> Tuple[List, List]:
        """
        调用底层解析器的解析方法

        Args:
            parser: 底层解析器实例
            file_path: 文件路径
            binary: 文件二进制内容
            callback: 进度回调函数
            **kwargs: 额外参数

        Returns:
            (sections, tables)
        """
        pass

    def check_installation(self) -> bool:
        """检查解析器是否可用"""
        parser = self._get_parser()
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            self._logger.warning(f"{self._get_parser_name()} check failed: {reason}")
        return ok

    def _validate_file(self, file_path: Path) -> None:
        """
        验证文件路径和扩展名

        Args:
            file_path: 文件路径

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的文件类型
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if self.SUPPORTED_EXTENSIONS is not None:
            if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f"Unsupported file type: {file_path.suffix}. "
                    f"Supported: {self.SUPPORTED_EXTENSIONS}"
                )

    def _create_callback(self) -> Callable[[float, str], None]:
        """创建进度回调函数"""
        parser_name = self._get_parser_name().upper()
        def callback(progress: float, msg: str):
            self._logger.info(f"[{parser_name}] {progress:.0%} - {msg}")
        return callback

    def _convert_sections_to_documents(
        self,
        sections: List,
        base_metadata: dict
    ) -> List[Document]:
        """
        将 sections 转换为 Document 列表

        Args:
            sections: 底层解析器返回的 sections
            base_metadata: 基础元数据

        Returns:
            Document 列表
        """
        if not sections:
            return []

        text_parts = []
        for section in sections:
            if isinstance(section, tuple):
                text = section[0] if section[0] else ""
            else:
                text = str(section)
            if text.strip():
                text_parts.append(text.strip())

        if not text_parts:
            return []

        return [Document(
            page_content="\n\n".join(text_parts),
            metadata={**base_metadata, "content_type": "text"}
        )]

    def _convert_tables_to_documents(
        self,
        tables: List,
        base_metadata: dict
    ) -> List[Document]:
        """
        将 tables 转换为 Document 列表

        Args:
            tables: 底层解析器返回的 tables
            base_metadata: 基础元数据

        Returns:
            Document 列表
        """
        if not tables:
            return []

        documents = []
        for i, table in enumerate(tables):
            table_content = self._extract_table_content(table)

            if table_content and table_content.strip():
                documents.append(Document(
                    page_content=table_content,
                    metadata={
                        **base_metadata,
                        "content_type": "table",
                        "table_index": i,
                    }
                ))

        return documents

    def _extract_table_content(self, table: Any) -> str:
        """
        从表格数据中提取内容

        Args:
            table: 表格数据（可能是多种格式）

        Returns:
            表格内容字符串
        """
        if isinstance(table, tuple) and len(table) >= 1:
            table_data = table[0]
            if isinstance(table_data, tuple) and len(table_data) >= 2:
                # (image, html) 格式
                html_content = table_data[1]
                if isinstance(html_content, str):
                    return html_content
                elif isinstance(html_content, list):
                    return "\n".join(str(x) for x in html_content)
                return html_content if html_content else ""
            elif isinstance(table_data, str):
                return table_data
        return str(table)

    def parse(
        self,
        file_path: Path,
        **kwargs
    ) -> List[Document]:
        """
        解析文档

        Args:
            file_path: 文档文件路径
            **kwargs: 额外参数

        Returns:
            LangChain Document 列表
        """
        file_path = Path(file_path)
        self._validate_file(file_path)

        parser = self._get_parser()

        # 检查安装
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            raise RuntimeError(f"{self._get_parser_name()} not available: {reason}")

        # 读取文件
        with open(file_path, "rb") as f:
            binary = f.read()

        # 调用底层解析器
        callback = self._create_callback()
        sections, tables = self._call_parse_method(
            parser=parser,
            file_path=file_path,
            binary=binary,
            callback=callback,
            **kwargs
        )

        # 转换为 LangChain Document 格式
        base_metadata = {
            "source": str(file_path),
            "filename": file_path.name,
            "parser": self._get_parser_name(),
        }

        documents = []
        documents.extend(self._convert_sections_to_documents(sections, base_metadata))
        documents.extend(self._convert_tables_to_documents(tables, base_metadata))

        self._logger.info(
            f"{self._get_parser_name()} parsed {file_path.name}: {len(documents)} documents"
        )
        return documents

    async def aparse(
        self,
        file_path: Path,
        **kwargs,
    ) -> List[Document]:
        """
        异步解析文档（使用 aiofiles 进行异步文件读取）
        
        Args:
            file_path: 文档文件路径
            **kwargs: 额外参数
        
        Returns:
            LangChain Document 列表
        """
        import aiofiles
        
        file_path = Path(file_path)
        self._validate_file(file_path)

        parser = self._get_parser()

        # 检查安装
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            raise RuntimeError(f"{self._get_parser_name()} not available: {reason}")

        # 异步读取文件
        async with aiofiles.open(file_path, "rb") as f:
            binary = await f.read()

        # 在线程池中调用底层解析器（解析器本身可能是同步的）
        def _parse_in_thread():
            callback = self._create_callback()
            sections, tables = self._call_parse_method(
                parser=parser,
                file_path=file_path,
                binary=binary,
                callback=callback,
                **kwargs
            )
            
            # 转换为 LangChain Document 格式
            base_metadata = {
                "source": str(file_path),
                "filename": file_path.name,
                "parser": self._get_parser_name(),
            }

            documents = []
            documents.extend(self._convert_sections_to_documents(sections, base_metadata))
            documents.extend(self._convert_tables_to_documents(tables, base_metadata))
            
            return documents
        
        documents = await asyncio.to_thread(_parse_in_thread)
        
        self._logger.info(
            f"{self._get_parser_name()} parsed {file_path.name}: {len(documents)} documents"
        )
        return documents
