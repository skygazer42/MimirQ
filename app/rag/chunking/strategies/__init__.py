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
- outline: Numbered-outline aware chunking
- transcript: Speaker-turn aware chunking
- qa_pairs: Q/A-pair aware chunking
- paper: Academic paper section-aware chunking
- manuscript: Content-aware preset for manuscripts
- book_structured: Book chapter/part aware chunking
- laws_structured: Legal document clause-aware chunking
- email_thread: Email thread aware chunking
- sop_steps: SOP/procedure step-aware chunking
- glossary: Glossary/dictionary entry-aware chunking
- sentence_window: Sentence window chunking with sentence overlap
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
from app.rag.chunking.strategies.outline import OutlineChunker
from app.rag.chunking.strategies.transcript import TranscriptChunker
from app.rag.chunking.strategies.qa_pairs import QAPairsChunker
from app.rag.chunking.strategies.paper import PaperChunker
from app.rag.chunking.strategies.manuscript import ManuscriptChunker
from app.rag.chunking.strategies.book_structured import BookStructuredChunker
from app.rag.chunking.strategies.laws_structured import LawsStructuredChunker
from app.rag.chunking.strategies.email_thread import EmailThreadChunker
from app.rag.chunking.strategies.sop_steps import SOPStepsChunker
from app.rag.chunking.strategies.glossary import GlossaryChunker
from app.rag.chunking.strategies.sentence_window import SentenceWindowChunker

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
    "OutlineChunker",
    "TranscriptChunker",
    "QAPairsChunker",
    "PaperChunker",
    "ManuscriptChunker",
    "BookStructuredChunker",
    "LawsStructuredChunker",
    "EmailThreadChunker",
    "SOPStepsChunker",
    "GlossaryChunker",
    "SentenceWindowChunker",
]
