"""
Custom separator-based chunking strategy.

Similar to Dify's separator-based chunking with preset options.
"""

import re
from typing import List, Optional

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker


class SeparatorChunker(BaseChunker):
    """
    Custom separator-based chunking (similar to Dify).

    Supports preset separators or custom patterns.
    """

    # Preset separator options
    PRESET_SEPARATORS = {
        "paragraph": "\n\n",
        "line": "\n",
        "sentence_cn": "。",
        "sentence_en": ".",
        "markdown_hr": "---",
        "markdown_h1": "# ",
        "markdown_h2": "## ",
        "custom": None,
    }

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        separator: str = "\n\n",
        keep_separator: bool = True,
        max_chunk_size: int = 0,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator
        self.keep_separator = keep_separator
        self.max_chunk_size = max_chunk_size if max_chunk_size > 0 else chunk_size * 3

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            if not text.strip():
                continue

            # Split by separator, optionally keeping it
            if self.separator:
                if self.keep_separator:
                    # Keep separator by attaching it to the preceding split part.
                    raw_parts = re.split(f"({re.escape(self.separator)})", text)
                    parts: list[str] = []
                    for i, part in enumerate(raw_parts):
                        if i % 2 == 0:
                            parts.append(part)
                        else:
                            if parts:
                                parts[-1] += part
                            else:
                                parts.append(part)
                else:
                    parts = text.split(self.separator)
            else:
                parts = [text]

            offset = 0
            for i, part in enumerate(parts):
                # Derive the absolute location for this part.
                raw_start = offset
                raw_end = raw_start + len(part)

                # Advance offset to the next segment start.
                offset = raw_end
                if not self.keep_separator and self.separator and i < len(parts) - 1:
                    # text.split() drops the separator; account for it between parts.
                    offset += len(self.separator)

                if not part.strip():
                    continue

                # Handle oversized chunks
                if len(part) > self.max_chunk_size:
                    sub_chunks = self._split_large_chunk(part, raw_start, doc.metadata)
                    chunks.extend(sub_chunks)
                else:
                    metadata = dict(doc.metadata or {})
                    content = part
                    start_idx = raw_start
                    end_idx = raw_end

                    # If we're *not* keeping the separator, trim whitespace and adjust offsets
                    # so that `text[start:end] == chunk.page_content` holds for highlighting.
                    if not self.keep_separator:
                        lstrip_len = len(part) - len(part.lstrip())
                        rstrip_len = len(part) - len(part.rstrip())
                        start_idx = raw_start + lstrip_len
                        end_idx = raw_end - rstrip_len
                        content = part[lstrip_len : len(part) - rstrip_len]

                    if not content:
                        continue

                    metadata["start_char"] = start_idx
                    metadata["end_char"] = end_idx
                    metadata["chunk_strategy"] = "separator"
                    metadata["separator"] = repr(self.separator)
                    chunks.append(Document(page_content=content, metadata=metadata))

        return chunks

    def _split_large_chunk(
        self,
        text: str,
        base_pos: int,
        base_metadata: Optional[dict],
    ) -> List[Document]:
        """Split oversized chunks at sentence boundaries."""
        chunks = []
        pos = 0

        while pos < len(text):
            end = min(pos + self.max_chunk_size, len(text))

            # Try to break at sentence boundary
            if end < len(text):
                for sep in ["。", ".", "！", "!", "？", "?", "\n", " "]:
                    last_sep = text.rfind(sep, pos, end)
                    if last_sep > pos:
                        end = last_sep + 1
                        break

            segment = text[pos:end]

            if self.keep_separator:
                chunk_text = segment
                start_char = base_pos + pos
                end_char = base_pos + end
            else:
                lstrip_len = len(segment) - len(segment.lstrip())
                rstrip_len = len(segment) - len(segment.rstrip())
                chunk_text = segment[lstrip_len : len(segment) - rstrip_len]
                start_char = base_pos + pos + lstrip_len
                end_char = base_pos + end - rstrip_len

            if chunk_text:
                metadata = dict(base_metadata or {})
                metadata["start_char"] = start_char
                metadata["end_char"] = end_char
                metadata["chunk_strategy"] = "separator"
                metadata["separator"] = repr(self.separator)
                metadata["is_sub_chunk"] = True
                chunks.append(Document(page_content=chunk_text, metadata=metadata))

            pos = end

        return chunks
