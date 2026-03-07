"""
Chat-related Pydantic schemas.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
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
    chunk_index: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    evidence_start_char: Optional[int] = None
    evidence_end_char: Optional[int] = None
    header_path: Optional[str] = None
    chunk_strategy: Optional[str] = None
    chunk_role: Optional[str] = None
    retrieval_role: Optional[str] = None
    neighbor_of: Optional[str] = None
    doc_pipeline_key: Optional[str] = None
    pipeline_hash: Optional[str] = None
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

    model_config = ConfigDict(extra="ignore")


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
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    """Update conversation fields."""

    title: Optional[str] = Field(default=None, max_length=500)


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

    # Optional retrieval preset (applies internal recall-first overrides).
    # Supported:
    # - "recall20": maximize chunk-level Hit@20 (top_k>=20, score_threshold=0.0)
    # - "recall50": recall-first for larger corpora (top_k>=50, score_threshold=0.0)
    # - "coverage80": aggressive recall/coverage preset (top_k>=80, score_threshold=0.0)
    retrieval_profile: Optional[str] = None
    # Optional intent router: when enabled, the system may override retrieval knobs based on
    # query intent (faq/howto/api/log). This is deterministic and PII-safe (no raw query in outputs).
    #
    # None means "use server default" (settings.RAG_INTENT_ROUTER_ENABLED).
    intent_router: Optional[bool] = None
    # Optional tenant/dataset policy overlay for the deterministic intent router.
    # This is transport-only here; runtime validation stays inside app.rag.policy.intent_router.
    intent_router_policy: Optional[Dict[str, Any]] = None

    # Controlled query expansion for recall (optional).
    # - query_aliases: dataset-scoped alias/synonym dictionary.
    # - enable_query_alias_expansion:
    #     - True  -> apply aliases when present
    #     - False -> disable even if aliases exist
    #     - None  -> default to enabled iff query_aliases is non-empty (dataset defaults can set this)
    enable_query_alias_expansion: Optional[bool] = None
    query_aliases: Optional[Dict[str, List[str]]] = None
    query_alias_max_queries: Optional[int] = Field(default=None, ge=0, le=20)

    # Optional: per-request overrides for LLM multi-query generation (inherits global settings when None).
    enable_multi_query: Optional[bool] = None
    multi_query_count: Optional[int] = Field(default=None, ge=1, le=8)
    multi_query_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: Optional[int] = Field(default=None, ge=0, le=2000)

    top_k: int = Field(default_factory=lambda: settings.RETRIEVAL_TOP_K, ge=1, le=100)
    score_threshold: float = Field(default_factory=lambda: settings.SIMILARITY_THRESHOLD, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2000, ge=1, le=200_000)

    retrieval_mode: str = Field(default="hybrid")  # hybrid | vector | keyword | mmr | auto
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)  # hybrid merge weight: vector vs keyword
    # Retrieval channel fusion strategy override. When None, uses settings.RETRIEVAL_FUSION_STRATEGY.
    # Supported:
    # - linear: min-max normalize each channel then alpha-blend
    # - rrf: reciprocal-rank fusion (score normalized for UI)
    # - budgeted_rrf: RRF scoring but enforce per-channel quotas in the visible top-k prefix
    # - weighted: weighted sum across normalized channel scores (requires fusion_weights for effect)
    fusion_strategy: Optional[str] = None
    # Only used by fusion_strategy=budgeted_rrf (ignored otherwise).
    # Example: {"vector": 25, "bm25": 10, "lexical": 10, "sparse": 5}
    fusion_budgets: Optional[Dict[str, int]] = None
    # Only used by fusion_strategy=budgeted_rrf (ignored otherwise).
    # Per-channel minimum rank score in [0,1], where rank_score is 1/rank (rank starts at 1).
    fusion_min_scores: Optional[Dict[str, float]] = None
    # Only used by fusion_strategy=weighted (ignored otherwise).
    # Per-channel weights over normalized scores.
    # Allowed keys: vector, bm25, lexical, sparse.
    fusion_weights: Optional[Dict[str, float]] = None

    enable_weight_rerank: bool = True
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default_factory=lambda: settings.RETRIEVAL_MMR_LAMBDA, ge=0.0, le=1.0)

    enable_reranker: bool = Field(default_factory=lambda: settings.ENABLE_RERANKER)  # optional: LLM/API rerank
    reranker_provider: str = Field(default_factory=lambda: settings.RERANKER_PROVIDER)  # llm | pc | none
    reranker_top_n: int = Field(default_factory=lambda: settings.RERANKER_TOP_N, ge=1, le=200)

    # LangGraph path toggles
    use_graph: bool = False

    # Grounding/anti-hallucination guardrails (best-effort, optional).
    # When enabled, the system will:
    # - Treat missing evidence as "non-existent" and abstain early.
    # - Force post-generation claim-check (may buffer streaming).
    #
    # This is equivalent to enabling settings.RAG_VISIBLE_EVIDENCE_ONLY_ENABLED,
    # but scoped to this request (and can be set via dataset rag_defaults).
    visible_evidence_only: bool = False

    # Optional: metadata filter for vector search / retrieval scoping
    metadata_filter: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v: Any) -> str:
        return normalize_retrieval_mode(str(v) if v is not None else None)

    @field_validator("fusion_strategy", mode="before")
    @classmethod
    def _normalize_fusion_strategy(cls, v: Any) -> Optional[str]:
        raw = str(v or "").strip().lower()
        if not raw:
            return None
        if raw in {"reciprocal_rank_fusion", "rrf"}:
            return "rrf"
        if raw in {"budget_rrf", "budgeted_rrf"}:
            return "budgeted_rrf"
        if raw in {"weighted", "weighted_linear", "weighted_sum"}:
            return "weighted"
        if raw == "linear":
            return "linear"
        raise ValueError("fusion_strategy must be one of: linear, rrf, budgeted_rrf, weighted")

    @model_validator(mode="after")
    def _validate_fusion_budgets(self) -> "ChatRAGConfig":
        allowed = {"vector", "bm25", "lexical", "sparse"}

        fb = getattr(self, "fusion_budgets", None)
        if fb is not None:
            if not isinstance(fb, dict):
                raise ValueError("fusion_budgets must be an object/dict when provided")
            cleaned: Dict[str, int] = {}
            for k, v in fb.items():
                key = str(k or "").strip().lower()
                if not key:
                    continue
                if key not in allowed:
                    raise ValueError("fusion_budgets keys must be in: vector, bm25, lexical, sparse")
                try:
                    iv = int(v) if v is not None else 0
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"fusion_budgets[{key}] must be an int") from exc
                if iv < 0 or iv > 200:
                    raise ValueError("fusion_budgets values must be between 0 and 200")
                cleaned[key] = iv
            self.fusion_budgets = cleaned or None

        fms = getattr(self, "fusion_min_scores", None)
        if fms is not None:
            if not isinstance(fms, dict):
                raise ValueError("fusion_min_scores must be an object/dict when provided")
            cleaned2: Dict[str, float] = {}
            for k, v in fms.items():
                key = str(k or "").strip().lower()
                if not key:
                    continue
                if key not in allowed:
                    raise ValueError("fusion_min_scores keys must be in: vector, bm25, lexical, sparse")
                try:
                    fv = float(v) if v is not None else 0.0
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"fusion_min_scores[{key}] must be a float") from exc
                if fv < 0.0 or fv > 1.0:
                    raise ValueError("fusion_min_scores values must be between 0.0 and 1.0")
                cleaned2[key] = fv
            self.fusion_min_scores = cleaned2 or None

        return self

    @model_validator(mode="after")
    def _validate_fusion_weights(self) -> "ChatRAGConfig":
        allowed = {"vector", "bm25", "lexical", "sparse"}

        fw = getattr(self, "fusion_weights", None)
        if fw is None:
            return self
        if not isinstance(fw, dict):
            raise ValueError("fusion_weights must be an object/dict when provided")

        cleaned: Dict[str, float] = {}
        for k, v in fw.items():
            key = str(k or "").strip().lower()
            if not key:
                continue
            if key not in allowed:
                raise ValueError("fusion_weights keys must be one of: vector, bm25, lexical, sparse")
            try:
                w = float(v)
            except Exception as exc:
                raise ValueError("fusion_weights values must be numbers") from exc
            if w < 0.0 or w > 1.0:
                raise ValueError("fusion_weights values must be in [0,1]")
            cleaned[key] = float(w)

        if not cleaned:
            raise ValueError("fusion_weights must have at least one non-empty key")

        self.fusion_weights = cleaned
        return self

    @model_validator(mode="after")
    def _normalize_channel_weights(self) -> "ChatRAGConfig":
        """
        Normalize (vector_weight, keyword_weight) to sum to 1 when enabled.

        This prevents accidental mis-weighting like 0.7/0.7 and makes behavior
        stable across callers.
        """
        if not bool(self.enable_weight_rerank):
            return self
        v = float(self.vector_weight or 0.0)
        k = float(self.keyword_weight or 0.0)
        total = v + k
        if total <= 0.0:
            raise ValueError("vector_weight + keyword_weight must be > 0 when enable_weight_rerank=true")
        self.vector_weight = v / total
        self.keyword_weight = k / total
        return self

    @model_validator(mode="after")
    def _apply_retrieval_profile(self) -> "ChatRAGConfig":
        """
        Apply retrieval presets by mutating the effective config.

        Note: presets are allowed to override user-provided values. This is intentional: a preset
        is a contract about retrieval behavior, not just a suggestion.
        """
        p = (self.retrieval_profile or "").strip().lower()
        if not p:
            self.retrieval_profile = None
            return self

        if p == "recall20":
            # Guarantee: at least 20 candidates returned and no similarity threshold filtering.
            self.top_k = max(int(self.top_k or 0), 20)
            self.score_threshold = 0.0
            self.retrieval_profile = "recall20"
            return self

        if p == "recall50":
            self.top_k = max(int(self.top_k or 0), 50)
            self.score_threshold = 0.0
            self.retrieval_profile = "recall50"
            return self

        if p == "coverage80":
            self.top_k = max(int(self.top_k or 0), 80)
            self.score_threshold = 0.0
            self.retrieval_profile = "coverage80"
            return self

        raise ValueError("retrieval_profile must be one of: recall20, recall50, coverage80")

class ChatRequest(BaseModel):
    """Chat request."""
    conversation_id: Optional[UUID] = None
    message: str
    history: List[HistoryMessage] = Field(default_factory=list)  # Conversation history.
    # Optional dataset scope. When set and document_ids is empty, retrieval is restricted to this dataset.
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)
    stream: bool = True
    structured_output: bool = False  # Require structured (JSON) output.
    structured_preset: Optional[str] = None  # faq | summary | action_items | custom
    enable_long_term_memory: bool = False  # Enable long-term memory retrieval.
    enable_summary_memory: bool = False  # Enable persistent summary memory injection (when available).
    prompt_template_id: Optional[UUID] = None  # Custom prompt template ID.
    prompt_template_key: Optional[str] = None  # Select latest version by key (optional).
    prompt_ab_experiment_key: Optional[str] = None  # A/B experiment key (optional, stable per-user split).
    rag_config_template_id: Optional[UUID] = None  # RAG config template ID (optional; retrieval/rerank knobs).
    rag_config_template_key: Optional[str] = None  # Select latest RAG config template by key (optional).
    rag_config_ab_experiment_key: Optional[str] = None  # A/B experiment key for RAG config templates (optional).
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)


class TokenUsage(BaseModel):
    """Token usage metadata for a single response."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    source: Literal["provider", "mock", "estimate"] = "estimate"

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def _normalize_total_tokens(self) -> "TokenUsage":
        """
        Normalize usage invariants so `total_tokens == prompt_tokens + completion_tokens`.

        For estimate-only usage, callers may provide only `total_tokens`; in that case treat it
        as completion-only (prompt=0, completion=total).
        """
        fields_set = getattr(self, "model_fields_set", set())
        prompt_set = "prompt_tokens" in fields_set
        completion_set = "completion_tokens" in fields_set
        total_set = "total_tokens" in fields_set

        prompt_tokens = int(self.prompt_tokens or 0)
        completion_tokens = int(self.completion_tokens or 0)
        total_tokens = int(self.total_tokens or 0)

        if total_set and not prompt_set and not completion_set:
            self.prompt_tokens = 0
            self.completion_tokens = total_tokens
            return self

        if total_set and prompt_set and not completion_set:
            inferred_completion = total_tokens - prompt_tokens
            if inferred_completion >= 0:
                self.completion_tokens = inferred_completion
                return self

        if total_set and completion_set and not prompt_set:
            inferred_prompt = total_tokens - completion_tokens
            if inferred_prompt >= 0:
                self.prompt_tokens = inferred_prompt
                return self

        self.total_tokens = int(self.prompt_tokens or 0) + int(self.completion_tokens or 0)
        return self


class ChatResponse(BaseModel):
    """Non-streaming chat response payload."""

    conversation_id: UUID
    assistant_message_id: UUID
    request_id: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    total_tokens: int = 0
    usage: Optional[TokenUsage] = Field(
        default=None,
        description="Best-effort token usage metadata; currently may be an assistant-only estimate.",
    )
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
