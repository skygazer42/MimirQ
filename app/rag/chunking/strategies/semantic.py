"""
Semantic sentence-based chunking strategy.

Splits text at sentence boundaries, then aggregates
sentences into chunks of the target size.
"""
from __future__ import annotations

import re
from typing import List

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker


class SemanticSentenceChunker(BaseChunker):
    """
    Lightweight semantic chunking based on sentence boundaries.

    Splits at sentence-ending punctuation, then aggregates
    sentences to reach the target chunk size.
    """

    # Regex pattern for sentence boundaries (Chinese and English)
    SENTENCE_PATTERN = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = max(chunk_size, 1)
        self.chunk_overlap = max(chunk_overlap, 0)

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []

        for doc in documents:
            text = doc.page_content
            sentence_matches = list(self.SENTENCE_PATTERN.finditer(text))

            buffer_text = ""
            buffer_start = 0
            last_end = 0

            def flush_chunk(end_idx: int):
                nonlocal buffer_text, buffer_start, last_end
                if not buffer_text:
                    return

                metadata = dict(doc.metadata or {})
                metadata["start_char"] = buffer_start
                metadata["end_char"] = end_idx
                metadata["chunk_strategy"] = "semantic_sentence"
                chunks.append(Document(page_content=buffer_text, metadata=metadata))

                # Handle overlap
                if self.chunk_overlap > 0 and len(buffer_text) > self.chunk_overlap:
                    overlap_text = buffer_text[-self.chunk_overlap:]
                    buffer_text = overlap_text
                    buffer_start = end_idx - len(overlap_text)
                else:
                    buffer_text = ""
                    buffer_start = end_idx
                last_end = end_idx

            for m in sentence_matches:
                sentence = m.group()
                start_idx, end_idx = m.start(), m.end()

                if not buffer_text:
                    buffer_start = start_idx

                # Flush if adding this sentence would exceed chunk size
                if len(buffer_text) + len(sentence) > self.chunk_size and buffer_text:
                    flush_chunk(last_end)

                buffer_text += sentence
                last_end = end_idx

            # Flush remaining buffer
            if buffer_text:
                flush_chunk(last_end)

        return chunks
