"""
Proposition-based chunking (baseline heuristic).

This is a **baseline** implementation for DenseX-style proposition chunking:
- Split content into sentence/list/code units (atomic-ish).
- Emit each unit as its own chunk ("proposition").

Why baseline first:
- Keeps ingest deterministic and cheap (no LLM calls).
- Provides an upgrade path to LLM-based proposition rewriting later.
"""

from typing import Any

from langchain_core.documents import Document

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.strategies.model_based.semantic import SemanticSentenceChunker


class PropositionChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        # chunk_size/overlap kept for interface compatibility; proposition chunking emits
        # atomic units and does not aggregate across them in the baseline version.
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        splitter = SemanticSentenceChunker(chunk_size=1, chunk_overlap=0)

        for doc in documents:
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            proposition_index = 0
            for unit in splitter._build_units(text):  # noqa: SLF001
                body = unit.text.strip()
                if not body:
                    continue
                meta: dict[str, Any] = dict(base_meta)
                start = unit.start + len(unit.text) - len(unit.text.lstrip())
                meta["chunk_strategy"] = "proposition"
                meta["start_char"] = start
                meta["end_char"] = start + len(body)
                meta["proposition_index"] = proposition_index
                meta["proposition_kind"] = unit.kind
                meta["chunk_index"] = len(out)
                out.append(Document(page_content=body, metadata=meta))
                proposition_index += 1

        return out


__all__ = ["PropositionChunker"]
