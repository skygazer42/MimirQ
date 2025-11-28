"""
PDF 解析器 (使用 PyMuPDF)
"""
from pathlib import Path
from typing import List
from langchain.docstore.document import Document
import fitz  # PyMuPDF


class PDFParser:
    """PDF 文档解析器"""

    def parse(self, file_path: Path) -> List[Document]:
        """
        解析 PDF 文档

        Args:
            file_path: PDF 文件路径

        Returns:
            LangChain Document 列表
        """
        documents = []

        # 打开 PDF 文件
        pdf_document = fitz.open(str(file_path))

        try:
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]

                # 提取文本
                text = page.get_text()

                # 跳过空白页
                if not text.strip():
                    continue

                # 构建元数据
                metadata = {
                    'source': str(file_path.name),
                    'page': page_num + 1,
                    'total_pages': len(pdf_document),
                    'file_type': 'pdf'
                }

                # 创建 Document 对象
                documents.append(Document(
                    page_content=text,
                    metadata=metadata
                ))

        finally:
            pdf_document.close()

        return documents
