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
    OutlineChunker,
    TranscriptChunker,
    QAPairsChunker,
    PaperChunker,
    ManuscriptChunker,
    BookStructuredChunker,
    LawsStructuredChunker,
    EmailThreadChunker,
    SOPStepsChunker,
    GlossaryChunker,
    SentenceWindowChunker,
    ResumeStructuredChunker,
    PresentationSlidesChunker,
    CsvRowsChunker,
    SpreadsheetSheetChunker,
    MarkdownTableChunker,
    ChatHistoryChunker,
)


class ChunkerFactory:
    """
    Factory for creating chunking strategy instances.

    Supported strategies:
    - auto: Content-aware strategy selection
    - manuscript: Preset for manuscript-like documents
    - langchain_recursive: RecursiveCharacterTextSplitter (default)
    - langchain_token: TokenTextSplitter (by token count)
    - parent_child: Two-level parent-child chunking
    - semantic_sentence: Sentence-boundary aggregation
    - sentence_window: Sentence window (sentence overlap)
    - separator: Custom separator-based chunking
    - llama_index: LlamaIndex SentenceSplitter (disabled)
    - llama_index_hierarchical: LlamaIndex hierarchical (disabled)
    - markdown_header: Markdown header-based chunking
    - markdown_aware: Enhanced markdown-aware chunking
    - json: JSON structure-aware chunking
    - code: Programming language-aware chunking
    - smart_code: AST-like code chunking (Python)
    - outline: Numbered-outline aware chunking
    - transcript: Transcript / dialogue aware chunking
    - qa_pairs: Q/A pair aware chunking
    - paper: Academic paper section aware chunking
    - book_structured: Book chapter/part aware chunking
    - laws_structured: Legal document clause-aware chunking
    - email_thread: Email thread aware chunking
    - sop_steps: SOP/procedure step-aware chunking
    - glossary: Glossary/dictionary entry-aware chunking
    - resume_structured: Resume/CV section-aware chunking
    - presentation_slides: Slide-aware chunking
    - csv_rows: CSV row-aware chunking
    - spreadsheet_sheet: Spreadsheet sheet-aware chunking
    - markdown_table: Markdown table-aware chunking
    - chat_history: Timestamped chat history chunking

    RAGFlow strategies (handled separately):
    - ragflow_naive: General-purpose chunking
    - ragflow_book: Book format chunking
    - ragflow_laws: Legal document chunking
    - ragflow_email: Email format chunking
    """

    SUPPORTED_STRATEGIES = {
        "auto": AutoChunker,
        "manuscript": ManuscriptChunker,
        "langchain_recursive": LangChainRecursiveChunker,
        "langchain_token": LangChainTokenChunker,
        "semantic_sentence": SemanticSentenceChunker,
        "sentence_window": SentenceWindowChunker,
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
        "outline": OutlineChunker,
        "transcript": TranscriptChunker,
        "qa_pairs": QAPairsChunker,
        "paper": PaperChunker,
        "book_structured": BookStructuredChunker,
        "laws_structured": LawsStructuredChunker,
        "email_thread": EmailThreadChunker,
        "sop_steps": SOPStepsChunker,
        "glossary": GlossaryChunker,
        "resume_structured": ResumeStructuredChunker,
        "presentation_slides": PresentationSlidesChunker,
        "csv_rows": CsvRowsChunker,
        "spreadsheet_sheet": SpreadsheetSheetChunker,
        "markdown_table": MarkdownTableChunker,
        "chat_history": ChatHistoryChunker,
    }

    RAGFLOW_STRATEGIES = {
        "ragflow_naive",
        "ragflow_book",
        "ragflow_laws",
        "ragflow_email",
    }

    STRATEGY_ALIASES = {
        # RAGFlow presets
        "ragflow": "ragflow_naive",
        "naive": "ragflow_naive",
        "book": "ragflow_book",
        "law": "ragflow_laws",
        "laws": "ragflow_laws",
        "legal": "ragflow_laws",
        "email": "ragflow_email",
        "mail": "ragflow_email",
        # Local presets
        "faq": "qa_pairs",
        "qa": "qa_pairs",
        "qna": "qa_pairs",
        "sop": "sop_steps",
        "procedure": "sop_steps",
        "workflow": "sop_steps",
        "steps": "sop_steps",
        "contract": "laws_structured",
        "policy": "laws_structured",
        "regulation": "laws_structured",
        "dictionary": "glossary",
        "terminology": "glossary",
        "emailthread": "email_thread",
        "mail_thread": "email_thread",
        "book_local": "book_structured",
        "laws_local": "laws_structured",
        # New local presets
        "resume": "resume_structured",
        "cv": "resume_structured",
        "简历": "resume_structured",
        "履历": "resume_structured",
        "slides": "presentation_slides",
        "slide": "presentation_slides",
        "ppt": "presentation_slides",
        "pptx": "presentation_slides",
        "presentation": "presentation_slides",
        "deck": "presentation_slides",
        "幻灯片": "presentation_slides",
        "csv": "csv_rows",
        "excel": "spreadsheet_sheet",
        "xlsx": "spreadsheet_sheet",
        "xls": "spreadsheet_sheet",
        "spreadsheet": "spreadsheet_sheet",
        "table": "markdown_table",
        "md_table": "markdown_table",
        "chat": "chat_history",
        "chatlog": "chat_history",
        "im": "chat_history",
        "聊天记录": "chat_history",
        "对话记录": "chat_history",
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

        if normalized in self.STRATEGY_ALIASES:
            normalized = self.STRATEGY_ALIASES[normalized]

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
