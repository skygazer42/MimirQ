"""
Chat-related Pydantic schemas.
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from app.rag.core.text import normalize_retrieval_mode

from .base import OrmModel

class Citation(BaseModel):
    """Citation information."""
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_content: str
    matched_terms: Optional[List[str]] = None
    page_number: Optional[int] = None
    header_path: Optional[str] = None
    chunk_strategy: Optional[str] = None
    chunk_role: Optional[str] = None
    retrieval_role: Optional[str] = None
    neighbor_of: Optional[str] = None
    relevance_score: float = 0.0
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
    # Image-related fields.
    has_image: bool = Field(default=False, description="Whether this citation contains an image")
    img_id: Optional[str] = Field(default=None, description="Image ID (MinIO format: {tenant_id}:{dataset_id}:{document_id}:{chunk_index})")
    img_url: Optional[str] = Field(default=None, description="Image access URL")


class MessageSchema(OrmModel):
    """Message."""
    id: UUID
    role: str  # user | assistant
    content: str
    citations: List[Citation] = []
    message_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime


class ConversationCreate(BaseModel):
    """Create conversation."""
    title: Optional[str] = None
    document_ids: List[UUID] = Field(default_factory=list)


class ConversationSchema(OrmModel):
    """Conversation session."""
    id: UUID
    title: Optional[str] = None
    last_message: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    """Conversation detail."""
    conversation_id: UUID
    returned: int = 0
    has_more: bool = False
    messages: List[MessageSchema]


class ConversationList(BaseModel):
    """Conversation list."""
    total: int
    returned: int = 0
    has_more: bool = False
    items: List[ConversationSchema]


class HistoryMessage(BaseModel):
    """History message."""
    role: str  # user | assistant
    content: str


class ChatRAGConfig(BaseModel):
    """RAG parameters specific to the chat endpoint."""

    top_k: int = Field(default=5, ge=1, le=100)
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2000, ge=1, le=200_000)

    retrieval_mode: str = Field(default="hybrid")  # hybrid | vector | keyword | mmr | auto
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)  # hybrid merge weight: vector vs keyword

    enable_weight_rerank: bool = True
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)

    enable_reranker: bool = False  # optional: LLM/API rerank
    reranker_provider: str = "llm"  # llm | pc | none
    reranker_top_n: int = Field(default=20, ge=1, le=200)

    # LangGraph path toggles
    use_graph: bool = False

    # Optional: metadata filter for vector search / retrieval scoping
    metadata_filter: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v: Any) -> str:
        return normalize_retrieval_mode(str(v) if v is not None else None)

class ChatRequest(BaseModel):
    """Chat request."""
    conversation_id: Optional[UUID] = None
    message: str
    history: List[HistoryMessage] = Field(default_factory=list)  # Conversation history.
    document_ids: List[UUID] = Field(default_factory=list)
    stream: bool = True
    structured_output: bool = False  # Require structured (JSON) output.
    structured_preset: Optional[str] = None  # faq | summary | action_items | custom
    enable_long_term_memory: bool = False  # Enable long-term memory retrieval.
    prompt_template_id: Optional[UUID] = None  # Custom prompt template ID.
    prompt_template_key: Optional[str] = None  # Select latest version by key (optional).
    prompt_ab_experiment_key: Optional[str] = None  # A/B experiment key (optional, stable per-user split).
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)


class ChatResponse(BaseModel):
    """Non-streaming chat response payload."""

    conversation_id: UUID
    assistant_message_id: UUID
    request_id: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    total_tokens: int = 0
    total_chars: int = 0
    retrieval_mode: Optional[str] = None
    vector_backend: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    structured: bool = False
    structured_data: Any = None

    model_config = ConfigDict(extra="ignore")


class StreamEvent(BaseModel):
    """Stream event."""
    type: str  # citations | token | done | error
    data: Any


class CheckpointItem(BaseModel):
    checkpoint_id: Optional[str] = None
    checkpoint_ns: str = ""
    created_at: Optional[datetime] = None
    next: Any = None
    metadata: Optional[Dict[str, Any]] = None
    values: Optional[Dict[str, Any]] = None


class CheckpointListResponse(BaseModel):
    thread_id: str
    items: List[CheckpointItem] = Field(default_factory=list)


class CheckpointDetailResponse(BaseModel):
    thread_id: str
    checkpoint_id: Optional[str] = None
    checkpoint_ns: str = ""
    created_at: Optional[datetime] = None
    next: Any = None
    metadata: Optional[Dict[str, Any]] = None
    values: Optional[Dict[str, Any]] = None
