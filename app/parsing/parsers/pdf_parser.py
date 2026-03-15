"""
PDF parser (based on PyMuPDF).
"""
from pathlib import Path

import fitz  # PyMuPDF
from langchain_core.documents import Document


class PDFParser:
    """PDF document parser."""

    def parse(self, file_path: Path) -> list[Document]:
        """
        Parse a PDF into a list of LangChain Documents.
        """
        documents: list[Document] = []

        # Open PDF file.
        pdf_document = fitz.open(str(file_path))

        try:
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]

                # Extract text.
                text = page.get_text()

                # Skip blank pages.
                if not text.strip():
                    continue

                # Build metadata.
                metadata = {
                    "source": str(file_path.name),
                    "page": page_num + 1,
                    "total_pages": len(pdf_document),
                    "file_type": "pdf",
                }

                # Create Document object.
                documents.append(
                    Document(
                        page_content=text,
                        metadata=metadata,
                    )
                )

        finally:
            pdf_document.close()

        return documents
