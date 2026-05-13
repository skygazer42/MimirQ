"""
Markdown Header Text Splitter

Splits markdown documents by header hierarchy while preserving
header context in chunk metadata.
"""


import re
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter as LCMarkdownHeaderTextSplitter,
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
)

from app.rag.chunking.base import BaseChunker
from app.rag.core.logging import get_logger

logger = get_logger("rag.chunking.strategies.markdown")


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
        headers_to_split_on: list[tuple[str, str]] | None = None,
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
            separators=["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", " ", ""],
            keep_separator="end",
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """
        Split documents by markdown headers.

        Args:
            documents: List of Document objects to split

        Returns:
            List of chunked Document objects with header metadata
        """
        all_chunks: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            original_metadata = dict(doc.metadata or {})

            if not text.strip():
                continue

            # Check if document appears to be markdown
            if not self._is_markdown(text):
                # Fall back to recursive splitting
                chunks = self._fallback_split(doc)
                all_chunks.extend(chunks)
                continue

            try:
                # Split by markdown headers
                md_chunks = self._md_splitter.split_text(text)
                search_pos = 0

                for md_doc in md_chunks:
                    # Calculate character positions
                    chunk_text = md_doc.page_content
                    start_pos = text.find(chunk_text, max(0, int(search_pos)))
                    if start_pos < 0:
                        start_pos = max(0, min(int(search_pos), len(text)))
                    end_pos = min(len(text), start_pos + len(chunk_text))

                    # Build metadata
                    chunk_metadata = {
                        **original_metadata,
                        **(md_doc.metadata or {}),
                        "chunk_strategy": "markdown_header",
                        "chunk_index": len(all_chunks),
                        # IMPORTANT: positions are local to `doc.page_content`
                        # (the caller may rebase with page_start_map later).
                        "start_char": start_pos,
                        "end_char": end_pos,
                    }

                    # Build header path for better context
                    header_path = self._build_header_path(md_doc.metadata or {})
                    if header_path:
                        chunk_metadata["header_path"] = header_path

                    # Check if chunk needs further splitting
                    if len(chunk_text) > self.chunk_size * 1.5:
                        # Split large chunks with fallback splitter
                        sub_chunks = self._fallback_splitter.split_text(chunk_text)
                        sub_search_pos = 0
                        for sub_idx, sub_text in enumerate(sub_chunks):
                            rel = chunk_text.find(sub_text, max(0, int(sub_search_pos)))
                            if rel < 0:
                                rel = max(0, min(int(sub_search_pos), len(chunk_text)))
                            sub_start = start_pos + rel
                            sub_end = min(len(text), sub_start + len(sub_text))
                            sub_metadata = {
                                **chunk_metadata,
                                "chunk_index": len(all_chunks),
                                "sub_chunk_index": sub_idx,
                                "start_char": sub_start,
                                "end_char": sub_end,
                            }
                            all_chunks.append(Document(
                                page_content=sub_text,
                                metadata=sub_metadata,
                            ))
                            sub_search_pos = max(sub_end - self.chunk_overlap - start_pos, rel + 1)
                    else:
                        all_chunks.append(Document(
                            page_content=chunk_text,
                            metadata=chunk_metadata,
                        ))

                    search_pos = max(end_pos - self.chunk_overlap, start_pos + 1)

            except Exception as e:
                logger.warning(f"Markdown splitting failed, using fallback: {e}")
                chunks = self._fallback_split(doc)
                all_chunks.extend(chunks)

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

    def _build_header_path(self, metadata: dict[str, Any]) -> str:
        """Build a header path from metadata."""
        parts = []
        for _, meta_key in self.headers_to_split_on:
            if meta_key in metadata:
                parts.append(str(metadata[meta_key]))
        return " > ".join(parts) if parts else ""

    def _fallback_split(self, doc: Document) -> list[Document]:
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
                "start_char": pos,
                "end_char": pos + len(chunk_text),
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
            "。",    # CN sentence end
            "！",
            "？",
            "；",
            ". ",    # Sentence
            " ",     # Word
            "",      # Character
        ])

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=separators,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split documents with markdown awareness."""
        all_chunks: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            original_metadata = dict(doc.metadata or {})

            if not text.strip():
                continue

            # Pre-process to protect code/list blocks (avoid splitting inside a single item/block).
            protected_text, code_blocks = self._protect_code_blocks(text)
            protected_text, list_items = self._protect_list_items(protected_text)

            # Split the protected text
            raw_chunks = self._splitter.split_text(protected_text)

            # Restore code blocks and create documents
            search_pos = 0
            for chunk_text in raw_chunks:
                # Restore placeholders in this chunk (list items first, then code blocks).
                restored_text = self._restore_placeholders(chunk_text, list_items)
                restored_text = self._restore_placeholders(restored_text, code_blocks)

                # Calculate positions
                pos = text.find(restored_text, max(0, int(search_pos)))
                if pos < 0:
                    probe = (restored_text or "").strip()
                    if probe:
                        probe = probe[: min(120, len(probe))]
                        pos = text.find(probe, max(0, int(search_pos)))
                if pos < 0:
                    pos = max(0, min(int(search_pos), len(text)))
                end_pos = min(len(text), pos + len(restored_text))

                chunk_metadata = {
                    **original_metadata,
                    "chunk_strategy": "markdown_aware",
                    "chunk_index": len(all_chunks),
                    "start_char": pos,
                    "end_char": end_pos,
                }

                # Extract current header context
                header_context = self._extract_header_context(text, pos)
                if header_context:
                    chunk_metadata["header_context"] = header_context
                    chunk_metadata.setdefault("header_path", header_context)

                all_chunks.append(Document(
                    page_content=restored_text,
                    metadata=chunk_metadata,
                ))

                search_pos = max(end_pos - self.chunk_overlap, pos + 1)

        return all_chunks

    def _protect_code_blocks(self, text: str) -> tuple[str, dict[str, str]]:
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
            r'(?m)^(?: {4}.+\n)+',
            replace_block,
            protected,
        )

        return protected, code_blocks

    _LIST_ITEM_RE = re.compile(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)")

    def _protect_list_items(self, text: str) -> tuple[str, dict[str, str]]:
        """
        Replace markdown list *items* with placeholders (best-effort).

        Goal: avoid splitting between a list item's bullet line and its indented continuation lines.
        This is intentionally conservative and bounded: extremely large items are left as-is so
        chunking can still make progress under small chunk sizes.
        """
        if not self.preserve_lists:
            return text, {}

        lines = (text or "").splitlines(keepends=True)
        if not lines:
            return text, {}

        items: dict[str, str] = {}
        out: list[str] = []
        idx = 0
        placeholder_idx = 0
        max_preserve_len = int(max(0, self.chunk_size) * 1.5) if self.chunk_size else 0

        def is_item_start(line: str) -> bool:
            return bool(self._LIST_ITEM_RE.match(line or ""))

        def is_continuation(line: str) -> bool:
            if not line:
                return False
            if (line.strip() == ""):
                return True
            return bool(re.match(r"^\s{2,}\S", line))

        while idx < len(lines):
            line = lines[idx]
            if not is_item_start(line):
                out.append(line)
                idx += 1
                continue

            start = idx
            idx += 1

            # Include indented continuations (and some blank lines) until next list item or a new block.
            while idx < len(lines):
                nxt = lines[idx]
                if is_item_start(nxt):
                    break
                if nxt.strip() == "":
                    # Keep blank line only if the next non-empty line is indented (still part of item).
                    j = idx + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines) and is_continuation(lines[j]):
                        idx += 1
                        continue
                    break
                if is_continuation(nxt):
                    idx += 1
                    continue
                break

            block = "".join(lines[start:idx])
            if max_preserve_len > 0 and len(block) > max_preserve_len:
                out.append(block)
                continue

            placeholder = f"__LIST_ITEM_{placeholder_idx}__"
            placeholder_idx += 1
            items[placeholder] = block
            out.append(placeholder)

        return "".join(out), items

    def _restore_placeholders(self, text: str, mapping: dict[str, str]) -> str:
        """Restore placeholders from a mapping (best-effort)."""
        if not mapping:
            return text
        out = text
        for placeholder, value in mapping.items():
            out = out.replace(placeholder, value)
        return out

    def _extract_header_context(self, full_text: str, position: int) -> str | None:
        """Extract the most recent header at-or-before the given position."""
        if not full_text:
            return None

        pos = max(0, min(int(position or 0), len(full_text)))
        line_start = full_text.rfind("\n", 0, pos) + 1
        line_end = full_text.find("\n", line_start)
        if line_end < 0:
            line_end = len(full_text)
        current_line = full_text[line_start:line_end].strip()
        if current_line.startswith("#"):
            return current_line

        # Fallback: scan prior lines.
        text_before = full_text[:line_start]
        for line in reversed(text_before.split("\n")):
            if line.strip().startswith("#"):
                return line.strip()

        return None
