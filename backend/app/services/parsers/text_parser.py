"""
文本和 Markdown 解析器
"""
from pathlib import Path
from typing import List
from langchain.docstore.document import Document
import markdown
from bs4 import BeautifulSoup


class TextParser:
    """纯文本解析器"""

    def parse(self, file_path: Path) -> List[Document]:
        """
        解析纯文本文件

        Args:
            file_path: 文本文件路径

        Returns:
            LangChain Document 列表
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        metadata = {
            'source': str(file_path.name),
            'file_type': 'txt'
        }

        return [Document(page_content=content, metadata=metadata)]


class MarkdownParser:
    """Markdown 解析器"""

    def parse(self, file_path: Path) -> List[Document]:
        """
        解析 Markdown 文件

        Args:
            file_path: Markdown 文件路径

        Returns:
            LangChain Document 列表
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # 保留原始 Markdown 格式（适合 RAG）
        # 也可以选择转换为纯文本
        # html = markdown.markdown(md_content)
        # text = BeautifulSoup(html, 'html.parser').get_text()

        metadata = {
            'source': str(file_path.name),
            'file_type': 'md'
        }

        return [Document(page_content=md_content, metadata=metadata)]
