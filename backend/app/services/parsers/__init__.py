"""
文档解析器工厂
"""
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from app.services.parsers.pdf_parser import PDFParser
from app.services.parsers.text_parser import TextParser, MarkdownParser
from app.services.parsers.mineru_parser import MinerUParser
from app.config import settings


class ParserFactory:
    """根据文件类型选择合适的解析器"""

    def __init__(self):
        # 根据配置选择 PDF 解析器
        if settings.MINERU_ENABLED and settings.MINERU_API_TOKEN:
            print("🚀 Using MinerU parser for PDF (advanced parsing)")
            pdf_parser = MinerUParser()
        else:
            print("📄 Using PyMuPDF parser for PDF (basic parsing)")
            pdf_parser = PDFParser()

        self.parsers = {
            ".pdf": pdf_parser,
            ".txt": TextParser(),
            ".md": MarkdownParser(),
        }

    def parse(self, file_path: Path) -> List[Document]:
        """
        根据文件类型自动选择解析器并返回 Document 列表
        """
        file_ext = file_path.suffix.lower()

        if file_ext not in self.parsers:
            raise ValueError(f"Unsupported file type: {file_ext}")

        parser = self.parsers[file_ext]
        return parser.parse(file_path)


# 全局实例
parser_factory = ParserFactory()
