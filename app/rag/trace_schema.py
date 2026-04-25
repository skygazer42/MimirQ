"""
RAG trace schema for UI visualization (History / Graph).

Design constraints:
- Stable: frontend relies on a consistent shape.
- PII-safe: never return raw user question/query or chunk text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RagTraceCitation(BaseModel):
    # Identifiers
    document_id: str | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None
    page_number: int | None = None

    # Positions (when available)
    start_char: int | None = None
    end_char: int | None = None

    # Retrieval provenance (PII-safe identifiers only).
    retrieval_role: str | None = None
    neighbor_of: str | None = None

    # Provenance
    doc_pipeline_key: str | None = None
    pipeline_hash: str | None = None

    # Scores / timing
    relevance_score: float | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    lexical_score: float | None = None
    sparse_score: float | None = None
    colbert_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    retrieval_score: float | None = None

    reranker_provider: str | None = None
    rerank_elapsed_sec: float | None = None
    rerank_model_used: str | None = None

    retrieval_mode: str | None = None
    vector_backend: str | None = None
    retrieval_elapsed_sec: float | None = None
    hit_type: str | None = None  # vector | keyword | mmr | hybrid

    # Image-related fields (no URLs here; only flags/ids)
    has_image: bool = False
    # Optional KG path provenance for KG-injected citations (bounded, PII-safe).
    kg_path: list[dict[str, Any]] | None = None
    # Optional KG shortest-path provenance (nodes/edges + source doc/chunk ids; bounded, PII-safe).
    kg_path_provenance: dict[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")


class RagTraceRetrievalQuery(BaseModel):
    kind: str | None = None  # main|mq|subq|hyde
    query_chars: int | None = None
    elapsed_sec: float | None = None
    ok: bool | None = None
    # Sanitized retriever-side debug counters (no text; no tenant/dataset ids).
    retriever_debug: dict[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")


class RagTraceRetrieval(BaseModel):
    mode: str | None = None
    requested_mode: str | None = None
    auto_routed: bool | None = None
    router_layers: dict[str, Any] | None = None

    # Stable, PII-safe fingerprint for cross-run comparisons.
    retrieval_config_hash: str | None = None

    top_k: int | None = None
    query_parallelism: int | None = None
    query_count: int | None = None

    per_query: list[RagTraceRetrievalQuery] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    enable_reranker: bool | None = None
    reranker_provider: str | None = None
    reranker_top_n: int | None = None

    elapsed_sec: float | None = None

    model_config = ConfigDict(extra="ignore")


class RagTraceRerank(BaseModel):
    enabled: bool = False
    provider: str | None = None
    top_n: int | None = None
    elapsed_sec: float | None = None
    model_used: str | None = None

    model_config = ConfigDict(extra="ignore")


class RagTraceStep(BaseModel):
    key: str
    label: str
    elapsed_sec: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class RagTrace(BaseModel):
    schema_version: int = 1

    ts_ms: int = 0
    request_id: str | None = None
    conversation_id: str | None = None

    retrieval: RagTraceRetrieval = Field(default_factory=RagTraceRetrieval)
    rerank: RagTraceRerank = Field(default_factory=RagTraceRerank)

    citations: list[RagTraceCitation] = Field(default_factory=list)
    citations_count: int = 0

    steps: list[RagTraceStep] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class RagTraceListResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    returned: int
    items: list[RagTrace] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")
