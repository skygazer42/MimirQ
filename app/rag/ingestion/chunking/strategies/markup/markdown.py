"""
Markdown Header Text Splitter

Splits markdown documents by header hierarchy while preserving
header context in chunk metadata.
"""

import logging
import re
from bisect import bisect_right
from collections.abc import Iterator
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter as LCMarkdownHeaderTextSplitter,
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
)

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.heading_parsing import parse_markdown_hash_heading

logger = logging.getLogger("rag.chunking.strategies.markdown")
_FENCE_LINE_RE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<tail>[^\r\n]*)")


def _iter_markdown_heading_lines(text: str) -> Iterator[tuple[int, str, int, str]]:
    fence: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        start = offset
        offset += len(line)
        match = _FENCE_LINE_RE.match(line)
        if match is not None:
            marker, tail = match.groups()
            if fence is not None:
                if marker[0] == fence[0] and len(marker) >= len(fence) and not tail.strip():
                    fence = None
                continue
            if marker[0] == "~" or "`" not in tail:
                fence = marker
                continue
        if fence is None and (heading := parse_markdown_hash_heading(line)) is not None:
            level, title = heading
            yield start, line, level, title


def _find_chunk_position(text: str, chunk_text: str, *, search_pos: int) -> tuple[int | None, int | None]:
    start = text.find(chunk_text, max(0, search_pos))
    if start < 0:
        return None, None
    return start, min(len(text), start + len(chunk_text))


def _is_list_continuation(line: str) -> bool:
    if not line:
        return False
    if not line.strip():
        return True
    return bool(re.match(r"^\s{2,}\S", line))


def _list_item_end(lines: list[str], *, start: int, pattern: re.Pattern[str]) -> int:
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if pattern.match(line):
            break
        if not line.strip():
            next_nonempty = index + 1
            while next_nonempty < len(lines) and not lines[next_nonempty].strip():
                next_nonempty += 1
            if next_nonempty < len(lines) and _is_list_continuation(lines[next_nonempty]):
                index += 1
                continue
            break
        if not _is_list_continuation(line):
            break
        index += 1
    return index


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
    ) -> None:
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
        self.headers_to_split_on = list(
            self.DEFAULT_HEADERS_TO_SPLIT_ON if headers_to_split_on is None else headers_to_split_on
        )
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

    def _header_chunk_metadata(
        self,
        *,
        original_metadata: dict[str, Any],
        markdown_metadata: dict[str, Any],
        chunk_index: int,
        start: int | None,
        end: int | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            **original_metadata,
            **markdown_metadata,
            "chunk_strategy": "markdown_header",
            "chunk_index": chunk_index,
            "start_char": start,
            "end_char": end,
        }
        if start is None or end is None:
            metadata["offset_mapping_error"] = "chunk_text_not_found_in_source"
        header_path = self._build_header_path(markdown_metadata)
        if header_path:
            metadata["header_path"] = header_path
        return metadata

    def _append_header_subchunks(
        self,
        all_chunks: list[Document],
        *,
        text: str,
        chunk_text: str,
        chunk_metadata: dict[str, Any],
        start_pos: int | None,
    ) -> None:
        sub_search_pos = 0
        for sub_idx, sub_text in enumerate(self._fallback_splitter.split_text(chunk_text)):
            relative_start, relative_end = _find_chunk_position(
                chunk_text,
                sub_text,
                search_pos=sub_search_pos,
            )
            if start_pos is not None and relative_start is not None:
                sub_start = start_pos + relative_start
                sub_end = min(len(text), sub_start + len(sub_text))
            else:
                sub_start = None
                sub_end = None
            sub_metadata = {
                **chunk_metadata,
                "chunk_index": len(all_chunks),
                "sub_chunk_index": sub_idx,
                "start_char": sub_start,
                "end_char": sub_end,
            }
            if sub_start is None:
                sub_metadata["offset_mapping_error"] = "chunk_text_not_found_in_source"
            all_chunks.append(Document(page_content=sub_text, metadata=sub_metadata))
            if relative_start is not None and relative_end is not None:
                sub_search_pos = max(relative_end - self.chunk_overlap, relative_start + 1)

    def _append_markdown_chunk(
        self,
        all_chunks: list[Document],
        *,
        text: str,
        markdown_doc: Document,
        original_metadata: dict[str, Any],
        search_pos: int,
    ) -> int:
        chunk_text = markdown_doc.page_content
        start_pos, end_pos = _find_chunk_position(
            text,
            chunk_text,
            search_pos=search_pos,
        )
        metadata = self._header_chunk_metadata(
            original_metadata=original_metadata,
            markdown_metadata=dict(markdown_doc.metadata),
            chunk_index=len(all_chunks),
            start=start_pos,
            end=end_pos,
        )
        if len(chunk_text) > self.chunk_size * 1.5:
            self._append_header_subchunks(
                all_chunks,
                text=text,
                chunk_text=chunk_text,
                chunk_metadata=metadata,
                start_pos=start_pos,
            )
        else:
            all_chunks.append(Document(page_content=chunk_text, metadata=metadata))
        if start_pos is None or end_pos is None:
            return search_pos
        return max(end_pos - self.chunk_overlap, start_pos + 1)

    def _split_markdown_document(self, doc: Document, all_chunks: list[Document]) -> None:
        text = doc.page_content
        if not text.strip():
            return
        if not self._is_markdown(text):
            all_chunks.extend(self._fallback_split(doc))
            return

        original_metadata = dict(doc.metadata)
        checkpoint = len(all_chunks)
        try:
            search_pos = 0
            for markdown_doc in self._md_splitter.split_text(text):
                search_pos = self._append_markdown_chunk(
                    all_chunks,
                    text=text,
                    markdown_doc=markdown_doc,
                    original_metadata=original_metadata,
                    search_pos=search_pos,
                )
        except Exception as exc:
            del all_chunks[checkpoint:]
            logger.warning("Markdown splitting failed, using fallback: %s", exc)
            fallback_chunks = self._fallback_split(doc)
            for chunk in fallback_chunks:
                chunk.metadata["chunk_fallback_error"] = f"{type(exc).__name__}:{str(exc)[:200]}"
            all_chunks.extend(fallback_chunks)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split documents by markdown headers."""
        all_chunks: list[Document] = []
        for doc in documents:
            self._split_markdown_document(doc, all_chunks)
        return all_chunks

    def _is_markdown(self, text: str) -> bool:
        """Check if text appears to be markdown."""
        md_patterns = [
            r"^#{1,6}\s+",  # Headers
            r"\[.*\]\(.*\)",  # Links
            r"\*\*.*\*\*",  # Bold
            r"\*.*\*",  # Italic
            r"^[-*+]\s+",  # Lists
            r"^\d+\.\s+",  # Numbered lists
            r"^```",  # Code blocks
            r"`[^`]+`",  # Inline code
        ]

        for pattern in md_patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True

        # Check header ratio
        lines = text.split("\n")
        header_count = sum(1 for line in lines if line.strip().startswith("#"))
        if len(lines) > 5 and header_count / len(lines) > 0.05:
            return True

        return False

    def _build_header_path(self, metadata: dict[str, Any]) -> str:
        """Build a header path from metadata."""
        parts: list[str] = []
        for _, meta_key in self.headers_to_split_on:
            if meta_key in metadata:
                parts.append(str(metadata[meta_key]))
        return " > ".join(parts)

    def _fallback_split(self, doc: Document) -> list[Document]:
        """Split document using fallback splitter."""
        text = doc.page_content
        original_metadata = dict(doc.metadata)

        chunks = self._fallback_splitter.split_text(text)
        result: list[Document] = []

        current_pos = 0
        for chunk_idx, chunk_text in enumerate(chunks):
            # Try to find exact position
            pos, end_pos = _find_chunk_position(text, chunk_text, search_pos=current_pos)

            chunk_metadata = {
                **original_metadata,
                "chunk_strategy": "markdown_fallback_recursive",
                "chunk_index": chunk_idx,
                "start_char": pos,
                "end_char": end_pos,
            }
            if pos is None:
                chunk_metadata["offset_mapping_error"] = "chunk_text_not_found_in_source"

            result.append(
                Document(
                    page_content=chunk_text,
                    metadata=chunk_metadata,
                )
            )

            if end_pos is not None:
                current_pos = end_pos - self.chunk_overlap

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
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.preserve_code_blocks = preserve_code_blocks
        self.preserve_lists = preserve_lists
        self.max_header_depth = max_header_depth

        # Build separators based on settings
        self._build_separators()

    def _build_separators(self) -> None:
        """Build the separator hierarchy for splitting."""
        separators: list[str] = []

        # Add header separators
        for i in range(1, self.max_header_depth + 1):
            separators.append("\n" + "#" * i + " ")

        # Add structure separators
        separators.extend(
            [
                "\n\n",  # Paragraph break
                "\n",  # Line break
                "。",  # CN sentence end
                "！",
                "？",
                "；",
                ". ",  # Sentence
                " ",  # Word
                "",  # Character
            ]
        )

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=separators,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split documents with markdown awareness."""
        all_chunks: list[Document] = []

        for doc in documents:
            text = doc.page_content
            original_metadata = dict(doc.metadata)

            if not text.strip():
                continue

            headings = [(start, line.strip()) for start, line, _, _ in _iter_markdown_heading_lines(text)]
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
                pos, end_pos = _find_chunk_position(text, restored_text, search_pos=search_pos)

                chunk_metadata = {
                    **original_metadata,
                    "chunk_strategy": "markdown_aware",
                    "chunk_index": len(all_chunks),
                    "start_char": pos,
                    "end_char": end_pos,
                }
                if pos is None:
                    chunk_metadata["offset_mapping_error"] = "chunk_text_not_found_in_source"

                if pos is not None:
                    heading_index = bisect_right(headings, pos, key=lambda item: item[0]) - 1
                    if heading_index >= 0:
                        header_context = headings[heading_index][1]
                        chunk_metadata["header_context"] = header_context
                        chunk_metadata.setdefault("header_path", header_context)

                all_chunks.append(
                    Document(
                        page_content=restored_text,
                        metadata=chunk_metadata,
                    )
                )

                if pos is not None and end_pos is not None:
                    search_pos = max(end_pos - self.chunk_overlap, pos + 1)

        return all_chunks

    def _protect_code_blocks(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace code blocks with placeholders."""
        if not self.preserve_code_blocks:
            return text, {}
        code_blocks: dict[str, str] = {}
        placeholder_idx = 0

        def replace_block(match: re.Match[str]) -> str:
            nonlocal placeholder_idx
            placeholder = f"__CODE_BLOCK_{placeholder_idx}__"
            while placeholder in text:
                placeholder_idx += 1
                placeholder = f"__CODE_BLOCK_{placeholder_idx}__"
            code_blocks[placeholder] = match.group(0)
            placeholder_idx += 1
            return placeholder

        # Protect fenced code blocks
        protected = re.sub(
            r"```[\s\S]*?```",
            replace_block,
            text,
        )

        # Protect indented code blocks (4 spaces)
        protected = re.sub(
            r"(?m)^(?: {4}.+\n)+",
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

        lines = (text).splitlines(keepends=True)
        items: dict[str, str] = {}
        out: list[str] = []
        idx = 0
        placeholder_idx = 0
        max_preserve_len = int(max(0, self.chunk_size) * 1.5) if self.chunk_size else 0

        while idx < len(lines):
            line = lines[idx]
            if not self._LIST_ITEM_RE.match(line):
                out.append(line)
                idx += 1
                continue

            start = idx
            idx = _list_item_end(lines, start=start, pattern=self._LIST_ITEM_RE)

            block = "".join(lines[start:idx])
            if max_preserve_len > 0 and len(block) > max_preserve_len:
                out.append(block)
                continue

            placeholder = f"__LIST_ITEM_{placeholder_idx}__"
            while placeholder in text:
                placeholder_idx += 1
                placeholder = f"__LIST_ITEM_{placeholder_idx}__"
            placeholder_idx += 1
            items[placeholder] = block
            out.append(placeholder)

        return "".join(out), items

    def _restore_placeholders(self, text: str, mapping: dict[str, str]) -> str:
        """Restore placeholders from a mapping (best-effort)."""
        out = text
        for placeholder, value in mapping.items():
            out = out.replace(placeholder, value)
        return out
