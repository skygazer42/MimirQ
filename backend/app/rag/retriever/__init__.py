"""
Retriever module for RAG systems.

Provides:
- MultiVectorRetriever: Multi-representation document retrieval
- HybridRetriever: Vector + BM25 hybrid search (in parent module)
"""

from app.rag.retriever.multi_vector import (
    MultiVectorRetriever,
    RepresentationType,
    DocumentRepresentation,
    BaseDocStore,
    InMemoryDocStore,
    create_summary_retriever,
    create_hypothetical_question_retriever,
    create_parent_child_retriever,
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
