"""
Text / Markdown parsers.
"""
from pathlib import Path
from typing import List
from langchain_core.documents import Document

from app.parsing.utils.text import read_text_file


class TextParser:
    """Plain text parser."""
    def parse(self, file_path: Path) -> List[Document]:
        """
        Parse a plain text file into Document list.
        """
        decoded = read_text_file(file_path)
        content = decoded.text

        file_type = file_path.suffix.lstrip(".").lower() or "txt"
        metadata = {
            "source": str(file_path.name),
            "file_type": file_type,
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        return [Document(page_content=content, metadata=metadata)]


class MarkdownParser:
    """Markdown parser."""

    def parse(self, file_path: Path) -> List[Document]:
        """
        Parse a Markdown file into Document list.
        Preserves raw Markdown text (better for RAG).
        """
        decoded = read_text_file(file_path)
        md_content = decoded.text

        # If you need plain text later, enable the lines below:
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
