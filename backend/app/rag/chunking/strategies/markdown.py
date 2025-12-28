"""
Markdown Header Text Splitter

Splits markdown documents by header hierarchy while preserving
header context in chunk metadata.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter as LCMarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.rag.chunking.base import BaseChunker

logger = logging.getLogger(__name__)


class MarkdownHeaderChunker(BaseChunker):
    """
    Markdown header-based chunker.

    Splits documents by markdown headers (#, ##, ###, etc.) while
    preserving the header hierarchy in chunk metadata.

    Features:
    - Splits on configurable header levels
    - Preserves header hierarchy in metadata
    - Optionally strips headers from content
    - Falls back to recursive splitting for large sections
    """

    # Default headers to split on
    DEFAULT_HEADERS_TO_SPLIT_ON = [
        ("#", "header_1"),
        ("##", "header_2"),
        ("###", "header_3"),
        ("####", "header_4"),
    ]

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        headers_to_split_on: Optional[List[Tuple[str, str]]] = None,
        strip_headers: bool = False,
        return_each_line: bool = False,
    ):
        """
        Initialize the Markdown header chunker.

        Args:
            chunk_size: Maximum size of each chunk (for fallback splitting)
            chunk_overlap: Overlap between chunks (for fallback splitting)
            headers_to_split_on: List of (header_marker, metadata_key) tuples
            strip_headers: Whether to remove headers from chunk content
            return_each_line: Whether to return each line as separate document
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.headers_to_split_on = headers_to_split_on or self.DEFAULT_HEADERS_TO_SPLIT_ON
        self.strip_headers = strip_headers
        self.return_each_line = return_each_line

        # Create the markdown splitter
        self._md_splitter = LCMarkdownHeaderTextSplitter(
            headers_to_split_on=self.headers_to_split_on,
            strip_headers=self.strip_headers,
            return_each_line=self.return_each_line,
        )

        # Create fallback splitter for large sections
        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """
        Split documents by markdown headers.

        Args:
            documents: List of Document objects to split

        Returns:
            List of chunked Document objects with header metadata
        """
        all_chunks: List[Document] = []
        char_offset = 0

        for doc_idx, doc in enumerate(documents):
            text = doc.page_content or ""
            original_metadata = dict(doc.metadata or {})

            if not text.strip():
                continue

            # Check if document appears to be markdown
            if not self._is_markdown(text):
                # Fall back to recursive splitting
                chunks = self._fallback_split(doc, char_offset)
                all_chunks.extend(chunks)
                char_offset += len(text)
                continue

            try:
                # Split by markdown headers
                md_chunks = self._md_splitter.split_text(text)

                for chunk_idx, md_doc in enumerate(md_chunks):
                    # Calculate character positions
                    chunk_text = md_doc.page_content
                    start_pos = text.find(chunk_text, char_offset - (len(text) if doc_idx > 0 else 0))
                    if start_pos == -1:
                        start_pos = char_offset

                    # Build metadata
                    chunk_metadata = {
                        **original_metadata,
                        **(md_doc.metadata or {}),
                        "chunk_strategy": "markdown_header",
                        "chunk_index": len(all_chunks),
                        "start_char": char_offset + start_pos if start_pos >= 0 else char_offset,
                        "end_char": char_offset + start_pos + len(chunk_text) if start_pos >= 0 else char_offset + len(chunk_text),
                    }

                    # Build header path for better context
                    header_path = self._build_header_path(md_doc.metadata or {})
                    if header_path:
                        chunk_metadata["header_path"] = header_path

                    # Check if chunk needs further splitting
                    if len(chunk_text) > self.chunk_size * 1.5:
                        # Split large chunks with fallback splitter
                        sub_chunks = self._fallback_splitter.split_text(chunk_text)
                        for sub_idx, sub_text in enumerate(sub_chunks):
                            sub_metadata = {
                                **chunk_metadata,
                                "chunk_index": len(all_chunks),
                                "sub_chunk_index": sub_idx,
                            }
                            all_chunks.append(Document(
                                page_content=sub_text,
                                metadata=sub_metadata,
                            ))
                    else:
                        all_chunks.append(Document(
                            page_content=chunk_text,
                            metadata=chunk_metadata,
                        ))

                char_offset += len(text)

            except Exception as e:
                logger.warning(f"Markdown splitting failed, using fallback: {e}")
                chunks = self._fallback_split(doc, char_offset)
                all_chunks.extend(chunks)
                char_offset += len(text)

        return all_chunks

    def _is_markdown(self, text: str) -> bool:
        """Check if text appears to be markdown."""
        md_patterns = [
            r'^#{1,6}\s+',  # Headers
            r'\[.*\]\(.*\)',  # Links
            r'\*\*.*\*\*',  # Bold
            r'\*.*\*',  # Italic
            r'^[-*+]\s+',  # Lists
            r'^\d+\.\s+',  # Numbered lists
            r'^```',  # Code blocks
            r'`[^`]+`',  # Inline code
        ]

        for pattern in md_patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True

        # Check header ratio
        lines = text.split('\n')
        header_count = sum(1 for line in lines if line.strip().startswith('#'))
        if len(lines) > 5 and header_count / len(lines) > 0.05:
            return True

        return False

    def _build_header_path(self, metadata: Dict[str, Any]) -> str:
        """Build a header path from metadata."""
        parts = []
        for _, meta_key in self.headers_to_split_on:
            if meta_key in metadata:
                parts.append(str(metadata[meta_key]))
        return " > ".join(parts) if parts else ""

    def _fallback_split(self, doc: Document, char_offset: int) -> List[Document]:
        """Split document using fallback splitter."""
        text = doc.page_content or ""
        original_metadata = dict(doc.metadata or {})

        chunks = self._fallback_splitter.split_text(text)
        result = []

        current_pos = 0
        for chunk_idx, chunk_text in enumerate(chunks):
            # Try to find exact position
            pos = text.find(chunk_text, current_pos)
            if pos == -1:
                pos = current_pos

            chunk_metadata = {
                **original_metadata,
                "chunk_strategy": "markdown_fallback_recursive",
                "chunk_index": chunk_idx,
                "start_char": char_offset + pos,
                "end_char": char_offset + pos + len(chunk_text),
            }

            result.append(Document(
                page_content=chunk_text,
                metadata=chunk_metadata,
            ))

            current_pos = pos + len(chunk_text) - self.chunk_overlap

        return result


class MarkdownAwareChunker(BaseChunker):
    """
    Enhanced markdown-aware chunker that combines header splitting
    with content-aware chunking.

    Features:
    - Respects markdown structure (headers, lists, code blocks)
    - Preserves code block integrity
    - Maintains list continuity when possible
    - Adds semantic context from headers
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        preserve_code_blocks: bool = True,
        preserve_lists: bool = True,
        max_header_depth: int = 4,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.preserve_code_blocks = preserve_code_blocks
        self.preserve_lists = preserve_lists
        self.max_header_depth = max_header_depth

        # Build separators based on settings
        self._build_separators()

    def _build_separators(self) -> None:
        """Build the separator hierarchy for splitting."""
        separators = []

        # Add header separators
        for i in range(1, self.max_header_depth + 1):
            separators.append("\n" + "#" * i + " ")

        # Add structure separators
        separators.extend([
            "\n\n",  # Paragraph break
            "\n",    # Line break
            ". ",    # Sentence
            " ",     # Word
            "",      # Character
        ])

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=separators,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """Split documents with markdown awareness."""
        all_chunks: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            original_metadata = dict(doc.metadata or {})

            if not text.strip():
                continue

            # Pre-process to protect code blocks
            protected_text, code_blocks = self._protect_code_blocks(text)

            # Split the protected text
            raw_chunks = self._splitter.split_text(protected_text)

            # Restore code blocks and create documents
            char_offset = 0
            for chunk_idx, chunk_text in enumerate(raw_chunks):
                # Restore code blocks in this chunk
                restored_text = self._restore_code_blocks(chunk_text, code_blocks)

                # Calculate positions
                pos = text.find(restored_text[:50] if len(restored_text) > 50 else restored_text)
                if pos == -1:
                    pos = char_offset

                chunk_metadata = {
                    **original_metadata,
                    "chunk_strategy": "markdown_aware",
                    "chunk_index": len(all_chunks),
                    "start_char": pos,
                    "end_char": pos + len(restored_text),
                }

                # Extract current header context
                header_context = self._extract_header_context(text, pos)
                if header_context:
                    chunk_metadata["header_context"] = header_context

                all_chunks.append(Document(
                    page_content=restored_text,
                    metadata=chunk_metadata,
                ))

                char_offset = pos + len(restored_text) - self.chunk_overlap

        return all_chunks

    def _protect_code_blocks(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Replace code blocks with placeholders."""
        code_blocks = {}
        placeholder_idx = 0

        def replace_block(match):
            nonlocal placeholder_idx
            placeholder = f"__CODE_BLOCK_{placeholder_idx}__"
            code_blocks[placeholder] = match.group(0)
            placeholder_idx += 1
            return placeholder

        # Protect fenced code blocks
        protected = re.sub(
            r'```[\s\S]*?```',
            replace_block,
            text,
        )

        # Protect indented code blocks (4 spaces)
        protected = re.sub(
            r'(?m)^(    .+\n)+',
            replace_block,
            protected,
        )

        return protected, code_blocks

    def _restore_code_blocks(self, text: str, code_blocks: Dict[str, str]) -> str:
        """Restore code blocks from placeholders."""
        for placeholder, code in code_blocks.items():
            text = text.replace(placeholder, code)
        return text

    def _extract_header_context(self, full_text: str, position: int) -> Optional[str]:
        """Extract the most recent header before the given position."""
        text_before = full_text[:position]
        lines = text_before.split('\n')

        for line in reversed(lines):
            if line.strip().startswith('#'):
                return line.strip()

        return None
