"""
Offline agentic chunker scaffold.

This is a deterministic stand-in for an LLM-as-judge boundary pass. It keeps the
strategy safe for backend-only workflows while exposing the metadata contract
needed for future offline batch re-chunking.
"""


from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


class AgenticChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = max(1, int(chunk_size or 1))
        self.chunk_overlap = max(0, int(chunk_overlap or 0))
        self._semantic = SemanticSentenceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def _signals_for_chunk(self, *, text: str, meta: dict[str, object]) -> list[str]:
        signals: list[str] = []
        content = str(text or "")
        if "\n1." in content or "\n2." in content or "\n- " in content:
            signals.append("list_boundary")
        if "```" in content:
            signals.append("code_boundary")
        start_char = int(meta.get("start_char") or 0)
        if start_char == 0:
            signals.append("document_start")
        if len(content) >= max(1, self.chunk_size - 20):
            signals.append("size_cap")
        if not signals:
            signals.append("semantic_boundary")
        return signals

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents or []:
            for chunk in self._semantic.split_documents([doc]):
                meta = dict(chunk.metadata or {})
                meta.update(
                    {
                        "chunk_strategy": "agentic_chunker",
                        "agentic_chunker_mode": "offline_batch",
                        "agentic_chunker_judge": "heuristic",
                        "agentic_chunker_signals": self._signals_for_chunk(
                            text=chunk.page_content or "",
                            meta=meta,
                        ),
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


__all__ = ["AgenticChunker"]
