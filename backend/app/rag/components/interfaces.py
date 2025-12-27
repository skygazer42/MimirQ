"""
Lightweight interfaces/contracts for RAG.

These are intentionally dependency-light so different pipeline implementations
can share a common schema without importing heavy runtime modules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol, TypedDict


class Citation(TypedDict, total=False):
    chunk_id: Any
    document_id: Any
    document_name: str
    chunk_content: str
    page_number: Any
    relevance_score: float
    vector_score: float
    bm25_score: float
    keyword_score: float
    rerank_score: Optional[float]
    retrieval_score: Optional[float]
    reranker_provider: Optional[str]
    rerank_elapsed_sec: Optional[float]
    rerank_model_used: Optional[str]
    retrieval_mode: str
    vector_backend: str
    retrieval_elapsed_sec: float
    hit_type: str
    img_id: Optional[str]
    img_url: Optional[str]
    has_image: bool


class PipelineResult(TypedDict, total=False):
    answer: str
    citations: List[Citation]
    model_used: Optional[str]
    route: Optional[str]
    routing_reason: Optional[str]
    metrics: Dict[str, Any]


class StreamEvent(TypedDict):
    type: Literal["citations", "token", "done", "error", "route"]
    data: Dict[str, Any]


class RAGPipeline(Protocol):
    def run(self, question: str, **kwargs: Any) -> PipelineResult: ...

