"""
Retriever module for RAG systems.

Provides:
- MultiVectorRetriever: Multi-representation document retrieval
- HybridRetriever: Vector + BM25 hybrid search (in app.rag.retriever)
"""

from app.rag.retrievers.multi_vector import (
    BaseDocStore,
    DocumentRepresentation,
    InMemoryDocStore,
    MultiVectorRetriever,
    RepresentationType,
    create_hypothetical_question_retriever,
    create_parent_child_retriever,
    create_summary_retriever,
)

__all__ = [
    "MultiVectorRetriever",
    "RepresentationType",
    "DocumentRepresentation",
    "BaseDocStore",
    "InMemoryDocStore",
    "create_summary_retriever",
    "create_hypothetical_question_retriever",
    "create_parent_child_retriever",
]
