"""
Proposition-based chunking (baseline heuristic).

This is a **baseline** implementation for DenseX-style proposition chunking:
- Split content into sentence/list/code units (atomic-ish).
- Emit each unit as its own chunk ("proposition").

Why baseline first:
- Keeps ingest deterministic and cheap (no LLM calls).
- Provides an upgrade path to LLM-based proposition rewriting later.
"""


from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


@dataclass(frozen=True)
class _PropUnit:
    text: str
    start: int
    end: int
    kind: str  # text | list | code


def _units_from_text(text: str) -> list[_PropUnit]:
    """
    Reuse SemanticSentenceChunker's unitization:
    - sentence units (text)
    - fenced code blocks (code)
    - list items (list)
    """
    splitter = SemanticSentenceChunker(chunk_size=1, chunk_overlap=0)
    raw_units = splitter._build_units(text or "")  # noqa: SLF001
    out: list[_PropUnit] = []
    for u in raw_units or []:
        s = int(getattr(u, "start", 0) or 0)
        e = int(getattr(u, "end", 0) or 0)
        body = (getattr(u, "text", "") or "").strip()
        kind = str(getattr(u, "kind", "text") or "text")
        if not body or e <= s:
            continue
        out.append(_PropUnit(text=body, start=s, end=e, kind=kind))
    return out


class PropositionChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        # chunk_size/overlap kept for interface compatibility; proposition chunking emits
        # atomic units and does not aggregate across them in the baseline version.
        self.chunk_size = int(chunk_size or 0)
        self.chunk_overlap = int(chunk_overlap or 0)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            units = _units_from_text(text)
            for i, u in enumerate(units):
                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "proposition"
                meta["start_char"] = int(u.start)
                meta["end_char"] = int(u.end)
                meta["proposition_index"] = int(i)
                meta["proposition_kind"] = str(u.kind)
                out.append(Document(page_content=u.text, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out


__all__ = ["PropositionChunker"]

