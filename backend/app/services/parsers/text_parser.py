"""
文本 / Markdown 解析器
"""
from pathlib import Path
from typing import List

from langchain_core.documents import Document
import markdown  # type: ignore
from bs4 import BeautifulSoup  # type: ignore


class TextParser:
    """纯文本解析器"""

    def parse(self, file_path: Path) -> List[Document]:
        """
        解析纯文本文件为 Document 列表。
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        metadata = {
            "source": str(file_path.name),
            "file_type": "txt",
        }

        return [Document(page_content=content, metadata=metadata)]


class MarkdownParser:
    """Markdown 解析器"""

    def parse(self, file_path: Path) -> List[Document]:
        """
        解析 Markdown 文件为 Document 列表。
        默认保留原始 Markdown 文本，更适合 RAG。
        """
        with open(file_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        # 如果将来需要转成纯文本，可以启用下面几行：
        # html = markdown.markdown(md_content)
        # text = BeautifulSoup(html, "html.parser").get_text()

        metadata = {
            "source": str(file_path.name),
            "file_type": "md",
        }

        return [Document(page_content=md_content, metadata=metadata)]

