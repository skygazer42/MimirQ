"""
Lightweight interfaces/contracts for RAG.

These are intentionally dependency-light so different pipeline implementations
can share a common schema without importing heavy runtime modules.
"""


from typing import Any, Literal, Protocol, TypedDict


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
    rerank_score: float | None
    retrieval_score: float | None
    reranker_provider: str | None
    rerank_elapsed_sec: float | None
    rerank_model_used: str | None
    retrieval_mode: str
    vector_backend: str
    retrieval_elapsed_sec: float
    hit_type: str
    img_id: str | None
    img_url: str | None
    has_image: bool


class PipelineResult(TypedDict, total=False):
    answer: str
    citations: list[Citation]
    model_used: str | None
    route: str | None
    routing_reason: str | None
    metrics: dict[str, Any]


class StreamEvent(TypedDict):
    type: Literal["citations", "token", "done", "error", "route"]
    data: dict[str, Any]


class RAGPipeline(Protocol):
    def run(self, question: str, **kwargs: Any) -> PipelineResult: ...

