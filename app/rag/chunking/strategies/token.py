"""
LangChain TokenTextSplitter wrapper.

Splits text by token count using tiktoken encoding.
"""

import logging

from langchain_core.documents import Document
from langchain_text_splitters import TokenTextSplitter

from app.core.token_utils import estimate_tokens
from app.rag.chunking.base import BaseChunker

logger = logging.getLogger(__name__)


class LangChainTokenChunker(BaseChunker):
    """Token-based text splitter using tiktoken encoding."""

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        encoding_name: str = "cl100k_base",
    ):
        # NOTE: For langchain_token strategy, the UI/docs treat chunk_size/chunk_overlap as *tokens*.
        # Keep this strategy token-native (unlike other strategies which use chars).
        self.chunk_size_tokens = max(1, int(chunk_size) or 1)
        self.chunk_overlap_tokens = max(0, int(chunk_overlap) or 0)
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            self.chunk_overlap_tokens = max(0, self.chunk_size_tokens - 1)

        self.encoding_name = encoding_name
        self.splitter = None
        try:
            # TokenTextSplitter uses tiktoken under the hood. In some offline/CI sandbox
            # environments, tiktoken may attempt to download encoding assets on first use,
            # which can fail and should not crash chunking.
            self.splitter = TokenTextSplitter(
                chunk_size=self.chunk_size_tokens,
                chunk_overlap=self.chunk_overlap_tokens,
                encoding_name=encoding_name,
            )
        except Exception:
            # Fall back to a heuristic splitter at runtime.
            self.splitter = None

    def _split_text_fallback(self, text: str) -> list[str]:
        raw = text or ""
        if not raw:
            return []

        # Heuristic: approximate chars/token from the whole text, then split by char window.
        est = estimate_tokens(raw)
        chars_per_token = 4
        if isinstance(est, int) and est > 0:
            chars_per_token = max(1, len(raw) // est)

        chunk_chars = max(1, self.chunk_size_tokens * chars_per_token)
        overlap_chars = max(0, self.chunk_overlap_tokens * chars_per_token)
        step = max(1, chunk_chars - overlap_chars)

        out: list[str] = []
        for start in range(0, len(raw), step):
            out.append(raw[start : start + chunk_chars])
            if start + chunk_chars >= len(raw):
                break
        return out

    def _split_text(self, text: str) -> list[str]:
        splitter = self.splitter
        if splitter is not None:
            try:
                return splitter.split_text(text)
            except Exception as exc:
                # tiktoken/network/proxy issues -> heuristic fallback.
                logger.debug("TokenTextSplitter failed; using heuristic token splitter: %s", exc)
        return self._split_text_fallback(text)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        for doc in documents:
            text = doc.page_content
            split_texts = self._split_text(text)
            current_pos = 0
            for split_text in split_texts:
                start_idx = text.find(split_text, current_pos)
                if start_idx == -1:
                    start_idx = current_pos
                end_idx = start_idx + len(split_text)
                metadata = dict(doc.metadata or {})
                metadata["start_char"] = start_idx
                metadata["end_char"] = end_idx
                metadata["chunk_strategy"] = "langchain_token"
                metadata["encoding_name"] = self.encoding_name
                metadata["chunk_size_tokens"] = self.chunk_size_tokens
                metadata["chunk_overlap_tokens"] = self.chunk_overlap_tokens
                chunks.append(Document(page_content=split_text, metadata=metadata))
                current_pos = max(start_idx + 1, end_idx - len(split_text) // 2)
        return chunks
