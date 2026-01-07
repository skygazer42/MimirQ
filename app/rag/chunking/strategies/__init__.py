"""
Chunking strategies module.

Available strategies:
- recursive: LangChain RecursiveCharacterTextSplitter wrapper
- token: LangChain TokenTextSplitter wrapper
- parent_child: Two-level parent-child chunking
- semantic: Sentence-based semantic chunking
- separator: Custom separator-based chunking
- llama_index: LlamaIndex-based chunking (disabled)
- markdown_header: Markdown header-based chunking
- markdown_aware: Enhanced markdown-aware chunking
- json: JSON structure-aware chunking
- code: Programming language-aware chunking
- smart_code: AST-like code chunking (Python)
"""
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.chunking.strategies.token import LangChainTokenChunker
from app.rag.chunking.strategies.parent_child import ParentChildChunker
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker
from app.rag.chunking.strategies.separator import SeparatorChunker
from app.rag.chunking.strategies.llama_index import (
    LlamaIndexChunker,
    LlamaIndexHierarchicalChunker,
)
from app.rag.chunking.strategies.markdown import (
    MarkdownHeaderChunker,
    MarkdownAwareChunker,
)
from app.rag.chunking.strategies.json_code import (
    JSONChunker,
    CodeChunker,
    SmartCodeChunker,
)
from app.rag.chunking.strategies.auto import AutoChunker

__all__ = [
    "LangChainRecursiveChunker",
    "LangChainTokenChunker",
    "ParentChildChunker",
    "SemanticSentenceChunker",
    "SeparatorChunker",
    "LlamaIndexChunker",
    "LlamaIndexHierarchicalChunker",
    # New splitters
    "MarkdownHeaderChunker",
    "MarkdownAwareChunker",
    "JSONChunker",
    "CodeChunker",
    "SmartCodeChunker",
    "AutoChunker",
]
