"""
LangChain RecursiveCharacterTextSplitter wrapper.

Preserves start/end character positions for highlighting.
"""

import re
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


class LangChainRecursiveChunker(BaseChunker):
    """RecursiveCharacterTextSplitter wrapper with position tracking."""

    # Default separators optimized for Chinese and English
    DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
    _HTML_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        separators: List[str] = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self.separators,
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            text = doc.page_content or ""
            if not text.strip():
                continue

            matches = list(self._HTML_TABLE_RE.finditer(text))
            if not matches:
                docs = self.splitter.create_documents(
                    texts=[text],
                    metadatas=[dict(doc.metadata or {})]
                )
                for chunk in docs:
                    start_index = chunk.metadata.pop("start_index", None)
                    metadata = dict(doc.metadata or {})
                    metadata.update(chunk.metadata or {})
                    if start_index is not None:
                        metadata["start_char"] = start_index
                        metadata["end_char"] = start_index + len(chunk.page_content)
                    metadata["chunk_strategy"] = "langchain_recursive"
                    chunks.append(Document(page_content=chunk.page_content, metadata=metadata))
                continue

            # Preserve HTML tables as atomic chunks to avoid breaking table structure during splitting.
            cursor = 0
            for m in matches:
                start = m.start()
                end = m.end()

                # Chunk non-table text preceding this table.
                if start > cursor:
                    prefix = text[cursor:start]
                    if prefix.strip():
                        docs = self.splitter.create_documents(
                            texts=[prefix],
                            metadatas=[dict(doc.metadata or {})]
                        )
                        for chunk in docs:
                            start_index = chunk.metadata.pop("start_index", None)
                            metadata = dict(doc.metadata or {})
                            metadata.update(chunk.metadata or {})
                            if start_index is not None:
                                abs_start = cursor + int(start_index)
                                metadata["start_char"] = abs_start
                                metadata["end_char"] = abs_start + len(chunk.page_content)
                            metadata["chunk_strategy"] = "langchain_recursive"
                            chunks.append(Document(page_content=chunk.page_content, metadata=metadata))

                # Chunk the table itself (do not split).
                table_text = text[start:end]
                if table_text.strip():
                    metadata = dict(doc.metadata or {})
                    metadata["start_char"] = start
                    metadata["end_char"] = end
                    metadata["chunk_strategy"] = "langchain_recursive"
                    metadata.setdefault("doc_type_kwd", "table")
                    chunks.append(Document(page_content=table_text, metadata=metadata))

                cursor = end

            # Chunk any remaining non-table tail text.
            if cursor < len(text):
                tail = text[cursor:]
                if tail.strip():
                    docs = self.splitter.create_documents(
                        texts=[tail],
                        metadatas=[dict(doc.metadata or {})]
                    )
                    for chunk in docs:
                        start_index = chunk.metadata.pop("start_index", None)
                        metadata = dict(doc.metadata or {})
                        metadata.update(chunk.metadata or {})
                        if start_index is not None:
                            abs_start = cursor + int(start_index)
                            metadata["start_char"] = abs_start
                            metadata["end_char"] = abs_start + len(chunk.page_content)
                        metadata["chunk_strategy"] = "langchain_recursive"
                        chunks.append(Document(page_content=chunk.page_content, metadata=metadata))
        return chunks
