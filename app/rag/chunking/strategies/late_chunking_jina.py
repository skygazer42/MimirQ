
from langchain_core.documents import Document

from app.rag.chunking.strategies.late_chunking import LateChunkingChunker


class LateChunkingJinaChunker(LateChunkingChunker):
    def split_documents(self, documents: list[Document]) -> list[Document]:
        out = super().split_documents(documents)
        for doc in out:
            meta = dict(doc.metadata or {})
            meta.update(
                {
                    "chunk_strategy": "late_chunking_jina",
                    "late_chunking_provider": "jina_v3",
                    "late_chunking_boundary_mode": "boundary_pooling",
                }
            )
            doc.metadata.clear()
            doc.metadata.update(meta)
        return out


__all__ = ["LateChunkingJinaChunker"]
