"""
Custom separator-based chunking strategy.

Similar to Dify's separator-based chunking with preset options.
"""
from __future__ import annotations

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
            text = doc.page_content
            if not text.strip():
                continue

            # Split by separator, optionally keeping it
            if self.keep_separator:
                parts = re.split(f"({re.escape(self.separator)})", text)
                merged_parts = []
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        merged_parts.append(part)
                    else:
                        if merged_parts:
                            merged_parts[-1] += part
                        else:
                            merged_parts.append(part)
                parts = merged_parts
            else:
                parts = text.split(self.separator)

            current_pos = 0
            for part in parts:
                if not part.strip():
                    current_pos += len(part) + (0 if self.keep_separator else len(self.separator))
                    continue

                # Handle oversized chunks
                if len(part) > self.max_chunk_size:
                    sub_chunks = self._split_large_chunk(part, current_pos, doc.metadata)
                    chunks.extend(sub_chunks)
                else:
                    metadata = dict(doc.metadata or {})
                    start_idx = text.find(part, current_pos)
                    if start_idx == -1:
                        start_idx = current_pos
                    end_idx = start_idx + len(part)
                    metadata["start_char"] = start_idx
                    metadata["end_char"] = end_idx
                    metadata["chunk_strategy"] = "separator"
                    metadata["separator"] = repr(self.separator)
                    chunks.append(Document(page_content=part.strip(), metadata=metadata))

                current_pos += len(part) + (0 if self.keep_separator else len(self.separator))

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

            chunk_text = text[pos:end].strip()
            if chunk_text:
                metadata = dict(base_metadata or {})
                metadata["start_char"] = base_pos + pos
                metadata["end_char"] = base_pos + end
                metadata["chunk_strategy"] = "separator"
                metadata["separator"] = repr(self.separator)
                metadata["is_sub_chunk"] = True
                chunks.append(Document(page_content=chunk_text, metadata=metadata))

            pos = end

        return chunks
