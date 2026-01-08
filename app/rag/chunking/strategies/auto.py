"""
Auto chunking strategy.

Selects an appropriate chunker per-document based on metadata + lightweight
content heuristics.
"""


import json
import re
from typing import List

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.json_code import JSONChunker
from app.rag.chunking.strategies.markdown import MarkdownAwareChunker
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


_MD_HINT_RE = re.compile(
    r"(^\s*#{1,6}\s+)|(\[[^\]]+\]\([^)]+\))|(^\s*```)|(^\s*[-*+]\s+)|(^\s*\d{1,3}[.)]\s+)",
    flags=re.MULTILINE,
)


def _looks_like_markdown(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    return bool(_MD_HINT_RE.search(text))


def _looks_like_json(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
        return True
    except Exception:
        return False


class AutoChunker(BaseChunker):
    """
    Smart, lightweight chunker selection.

    Strategy selection (per Document):
    - Markdown-ish content -> markdown_aware (structure-friendly)
    - Valid JSON content -> json (structure-friendly, overlap=0)
    - Long plain text -> semantic_sentence (better boundary alignment)
    - Default -> langchain_recursive (general purpose)
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_recursive = LangChainRecursiveChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._markdown = MarkdownAwareChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._semantic = SemanticSentenceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def _select(self, doc: Document) -> tuple[BaseChunker, str]:
        meta = doc.metadata or {}
        file_type = str(meta.get("file_type", "") or "").strip().lower()
        text = doc.page_content or ""

        if file_type in {"md", "markdown"} or _looks_like_markdown(text):
            return self._markdown, "markdown_aware"

        if file_type in {"json"} or _looks_like_json(text):
            # JSON overlap is usually counterproductive; keep it at 0.
            return JSONChunker(chunk_size=self.chunk_size, chunk_overlap=0), "json"

        # If the document is long enough, sentence-aware splitting tends to
        # reduce broken sentences and improves retrieval.
        if len(text) >= max(self.chunk_size * 2, 1200):
            return self._semantic, "semantic_sentence"

        return self._fallback_recursive, "langchain_recursive"

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            chunker, selected = self._select(doc)
            produced = chunker.split_documents([doc])
            for item in produced:
                meta = dict(item.metadata or {})
                meta["chunk_strategy_auto"] = True
                meta.setdefault("chunk_strategy_selected", selected)
                item.metadata = meta
            chunks.extend(produced)
        return chunks

