"""
LangChain RecursiveCharacterTextSplitter wrapper.

Preserves start/end character positions for highlighting.
"""

import re

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
        separators: list[str] = None,
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

    def _split_text_segment(self, *, text: str, base_metadata: dict, offset: int = 0) -> list[Document]:
        docs = self.splitter.create_documents(texts=[text], metadatas=[dict(base_metadata)])
        out: list[Document] = []
        for chunk in docs:
            start_index = chunk.metadata.pop("start_index", None)
            metadata = dict(base_metadata)
            metadata.update(chunk.metadata or {})
            if start_index is not None:
                abs_start = offset + int(start_index)
                metadata["start_char"] = abs_start
                metadata["end_char"] = abs_start + len(chunk.page_content)
            metadata["chunk_strategy"] = "langchain_recursive"
            out.append(Document(page_content=chunk.page_content, metadata=metadata))
        return out

    @staticmethod
    def _table_chunk(*, table_text: str, base_metadata: dict, start: int, end: int) -> Document | None:
        if not table_text.strip():
            return None

        metadata = dict(base_metadata)
        metadata["start_char"] = start
        metadata["end_char"] = end
        metadata["chunk_strategy"] = "langchain_recursive"
        metadata.setdefault("doc_type_kwd", "table")
        return Document(page_content=table_text, metadata=metadata)

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content or ""
        if not text.strip():
            return []

        base_metadata = dict(doc.metadata or {})
        matches = list(self._HTML_TABLE_RE.finditer(text))
        if not matches:
            return self._split_text_segment(text=text, base_metadata=base_metadata)

        chunks: list[Document] = []
        cursor = 0
        for match in matches:
            start = match.start()
            end = match.end()
            prefix = text[cursor:start]
            if prefix.strip():
                chunks.extend(self._split_text_segment(text=prefix, base_metadata=base_metadata, offset=cursor))

            table_doc = self._table_chunk(
                table_text=text[start:end],
                base_metadata=base_metadata,
                start=start,
                end=end,
            )
            if table_doc is not None:
                chunks.append(table_doc)
            cursor = end

        tail = text[cursor:]
        if tail.strip():
            chunks.extend(self._split_text_segment(text=tail, base_metadata=base_metadata, offset=cursor))
        return chunks

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        for doc in documents:
            chunks.extend(self._split_document(doc))
        return chunks
