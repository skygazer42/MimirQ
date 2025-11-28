"""
文档解析器工厂
"""
from pathlib import Path
from typing import List
from langchain.docstore.document import Document

from app.services.parsers.pdf_parser import PDFParser
from app.services.parsers.text_parser import TextParser, MarkdownParser


class ParserFactory:
    """解析器工厂"""

    def __init__(self):
        self.parsers = {
            '.pdf': PDFParser(),
            '.txt': TextParser(),
            '.md': MarkdownParser()
        }

    def parse(self, file_path: Path) -> List[Document]:
        """
        根据文件类型自动选择解析器

        Args:
            file_path: 文件路径

        Returns:
            LangChain Document 列表
        """
        file_ext = file_path.suffix.lower()

        if file_ext not in self.parsers:
            raise ValueError(f"Unsupported file type: {file_ext}")

        parser = self.parsers[file_ext]
        return parser.parse(file_path)


# 全局实例
parser_factory = ParserFactory()
