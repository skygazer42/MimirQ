"""
文本 / Markdown 解析器
"""
from pathlib import Path
from typing import List
from langchain_core.documents import Document

from app.parsing.utils.text import read_text_file


class TextParser:
    """纯文本解析器"""
    def parse(self, file_path: Path) -> List[Document]:
        """
        解析纯文本文件为 Document 列表。
        """
        decoded = read_text_file(file_path)
        content = decoded.text

        metadata = {
            "source": str(file_path.name),
            "file_type": "txt",
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        return [Document(page_content=content, metadata=metadata)]


class MarkdownParser:
    """Markdown 解析器"""

    def parse(self, file_path: Path) -> List[Document]:
        """
        解析 Markdown 文件为 Document 列表。
        默认保留原始 Markdown 文本，更适合 RAG。
        """
        decoded = read_text_file(file_path)
        md_content = decoded.text

        # 如果将来需要转成纯文本，可以启用下面几行：
        # html = markdown.markdown(md_content)
        # text = BeautifulSoup(html, "html.parser").get_text()

        metadata = {
            "source": str(file_path.name),
            "file_type": "md",
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        return [Document(page_content=md_content, metadata=metadata)]
