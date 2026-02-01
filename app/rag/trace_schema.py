"""
RAG trace schema for UI visualization (History / Graph).

Design constraints:
- Stable: frontend relies on a consistent shape.
- PII-safe: never return raw user question/query or chunk text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RagTraceCitation(BaseModel):
    # Identifiers
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    page_number: Optional[int] = None

    # Positions (when available)
    start_char: Optional[int] = None
    end_char: Optional[int] = None

    # Provenance
    doc_pipeline_key: Optional[str] = None
    pipeline_hash: Optional[str] = None

    # Scores / timing
    relevance_score: Optional[float] = None
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rerank_score: Optional[float] = None
    retrieval_score: Optional[float] = None

    reranker_provider: Optional[str] = None
    rerank_elapsed_sec: Optional[float] = None
    rerank_model_used: Optional[str] = None

    retrieval_mode: Optional[str] = None
    vector_backend: Optional[str] = None
    retrieval_elapsed_sec: Optional[float] = None
    hit_type: Optional[str] = None  # vector | keyword | mmr | hybrid

    # Image-related fields (no URLs here; only flags/ids)
    has_image: bool = False

    model_config = ConfigDict(extra="ignore")


class RagTraceRetrievalQuery(BaseModel):
    kind: Optional[str] = None  # main|mq|subq|hyde
    query_chars: Optional[int] = None
    elapsed_sec: Optional[float] = None
    ok: Optional[bool] = None

    model_config = ConfigDict(extra="ignore")


class RagTraceRetrieval(BaseModel):
    mode: Optional[str] = None
    requested_mode: Optional[str] = None
    auto_routed: Optional[bool] = None

    top_k: Optional[int] = None
    query_parallelism: Optional[int] = None
    query_count: Optional[int] = None

    per_query: List[RagTraceRetrievalQuery] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    enable_reranker: Optional[bool] = None
    reranker_provider: Optional[str] = None
    reranker_top_n: Optional[int] = None

    elapsed_sec: Optional[float] = None

    model_config = ConfigDict(extra="ignore")


class RagTraceRerank(BaseModel):
    enabled: bool = False
    provider: Optional[str] = None
    top_n: Optional[int] = None
    elapsed_sec: Optional[float] = None
    model_used: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class RagTraceStep(BaseModel):
    key: str
    label: str
    elapsed_sec: Optional[float] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class RagTrace(BaseModel):
    schema_version: int = 1

    ts_ms: int = 0
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None

    retrieval: RagTraceRetrieval = Field(default_factory=RagTraceRetrieval)
    rerank: RagTraceRerank = Field(default_factory=RagTraceRerank)

    citations: List[RagTraceCitation] = Field(default_factory=list)
    citations_count: int = 0

    steps: List[RagTraceStep] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class RagTraceListResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    returned: int
    items: List[RagTrace] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

