"""
Deterministic late-chunking scaffold.

This keeps explicit chunk boundaries while emitting the metadata contract for a
"embed whole document then pool by boundary" retrieval lane.
"""


from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


class LateChunkingChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = max(1, int(chunk_size or 1))
        self.chunk_overlap = max(0, int(chunk_overlap or 0))
        self._boundary_chunker = SemanticSentenceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents or []:
            doc_text = str(doc.page_content or "")
            doc_len = len(doc_text)
            for chunk in self._boundary_chunker.split_documents([doc]):
                meta = dict(chunk.metadata or {})
                meta.update(
                    {
                        "chunk_strategy": "late_chunking",
                        "late_chunking_enabled": True,
                        "late_chunking_scope": "document",
                        "late_chunking_pooling": "mean",
                        "late_chunking_doc_chars": doc_len,
                        "late_chunking_base_strategy": "semantic_sentence",
                    }
                )
                out.append(
                    Document(
                        page_content=chunk.page_content,
                        metadata=meta,
                        id=getattr(chunk, "id", None),
                    )
                )
        return out


__all__ = ["LateChunkingChunker"]
