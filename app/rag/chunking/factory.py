"""
Chunker factory for selecting and creating chunking strategies.

Usage:
    from app.rag.chunking import chunker_factory

    chunker = chunker_factory.get_chunker("langchain_recursive", chunk_size=1000, chunk_overlap=200)
    chunks = chunker.split_documents(documents)
"""

from typing import Optional

from app.core.config import settings
from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies import (
    LangChainRecursiveChunker,
    LangChainTokenChunker,
    ParentChildChunker,
    SemanticSentenceChunker,
    SeparatorChunker,
    LlamaIndexChunker,
    LlamaIndexHierarchicalChunker,
    # New splitters
    MarkdownHeaderChunker,
    MarkdownAwareChunker,
    JSONChunker,
    CodeChunker,
    SmartCodeChunker,
    AutoChunker,
)


class ChunkerFactory:
    """
    Factory for creating chunking strategy instances.

    Supported strategies:
    - auto: Content-aware strategy selection
    - langchain_recursive: RecursiveCharacterTextSplitter (default)
    - langchain_token: TokenTextSplitter (by token count)
    - parent_child: Two-level parent-child chunking
    - semantic_sentence: Sentence-boundary aggregation
    - separator: Custom separator-based chunking
    - llama_index: LlamaIndex SentenceSplitter (disabled)
    - llama_index_hierarchical: LlamaIndex hierarchical (disabled)
    - markdown_header: Markdown header-based chunking
    - markdown_aware: Enhanced markdown-aware chunking
    - json: JSON structure-aware chunking
    - code: Programming language-aware chunking
    - smart_code: AST-like code chunking (Python)

    RAGFlow strategies (handled separately):
    - ragflow_naive: General-purpose chunking
    - ragflow_book: Book format chunking
    - ragflow_laws: Legal document chunking
    - ragflow_email: Email format chunking
    """

    SUPPORTED_STRATEGIES = {
        "auto": AutoChunker,
        "langchain_recursive": LangChainRecursiveChunker,
        "langchain_token": LangChainTokenChunker,
        "semantic_sentence": SemanticSentenceChunker,
        "separator": SeparatorChunker,
        "llama_index": LlamaIndexChunker,
        "llama_index_hierarchical": LlamaIndexHierarchicalChunker,
        "parent_child": ParentChildChunker,
        # New splitters
        "markdown_header": MarkdownHeaderChunker,
        "markdown_aware": MarkdownAwareChunker,
        "markdown": MarkdownHeaderChunker,  # Alias
        "json": JSONChunker,
        "code": CodeChunker,
        "smart_code": SmartCodeChunker,
    }

    RAGFLOW_STRATEGIES = {
        "ragflow_naive",
        "ragflow_book",
        "ragflow_laws",
        "ragflow_email",
    }

    def resolve_strategy(self, strategy: Optional[str]) -> str:
        """
        Resolve and validate the chunking strategy name.

        Args:
            strategy: Strategy name or None for default.

        Returns:
            Normalized strategy name.

        Raises:
            ValueError: If strategy is not supported.
        """
        normalized = (strategy or settings.DEFAULT_CHUNK_STRATEGY).lower()

        if normalized in self.RAGFLOW_STRATEGIES:
            return normalized

        if normalized not in self.SUPPORTED_STRATEGIES:
            all_strategies = sorted(self.SUPPORTED_STRATEGIES) + sorted(self.RAGFLOW_STRATEGIES)
            raise ValueError(
                f"Unsupported chunk strategy '{strategy}'. "
                f"Supported strategies: {all_strategies}"
            )

        if normalized.startswith("llama_index") and not settings.LLAMA_INDEX_ENABLED:
            raise ValueError(
                "LlamaIndex chunker is disabled. Set LLAMA_INDEX_ENABLED=True to use it."
            )

        return normalized

    def get_chunker(
        self,
        strategy: Optional[str],
        chunk_size: int,
        chunk_overlap: int,
    ) -> BaseChunker:
        """
        Create a chunker instance for the specified strategy.

        Args:
            strategy: Chunking strategy name.
            chunk_size: Target chunk size in characters.
            chunk_overlap: Overlap between chunks in characters.

        Returns:
            BaseChunker instance.

        Raises:
            ValueError: If strategy is RAGFlow-based (requires different handling).
        """
        resolved = self.resolve_strategy(strategy)

        if resolved in self.RAGFLOW_STRATEGIES:
            raise ValueError(
                f"Chunk strategy '{resolved}' is handled by the RAGFlow pipeline. "
                f"Use 'chunk_file' from app.rag.chunking.ragflow.bridge instead."
            )

        chunker_cls = self.SUPPORTED_STRATEGIES[resolved]
        return chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def is_ragflow_strategy(self, strategy: Optional[str]) -> bool:
        """Check if the strategy requires RAGFlow pipeline."""
        try:
            resolved = self.resolve_strategy(strategy)
            return resolved in self.RAGFLOW_STRATEGIES
        except ValueError:
            return False


# Singleton factory instance
chunker_factory = ChunkerFactory()
