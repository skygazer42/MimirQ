"""Chat, conversation and retrieval configuration models."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.base import OrmModel
from app.core.config import settings
from app.core.model_execution import reject_retired_provider, reject_retired_retrieval_profile
from app.rag.core.retrieval_modes import normalize_retrieval_mode
from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides
from app.rag.retrieval.contract import (
    VALID_RETRIEVAL_CONTRACT_MODES,
    normalize_retrieval_contract_mode,
)

_HIERARCHY_FAMILY_AGGREGATION_VALUES = ("frequency", "score", "combined")
_FUSION_CHANNELS = frozenset({"vector", "bm25", "lexical", "sparse"})
_RETRIEVAL_PROFILES_BY_MODE = {
    "basic": "hybrid_ce",
    "contextual": "long_context",
    "expanded": "expanded",
}


def _uses_default_retrieval_options(config: "ChatRAGConfig") -> bool:
    # Preserve the existing value comparison, including explicitly supplied defaults.
    return (
        config.top_k == settings.RETRIEVAL_TOP_K
        and abs(config.score_threshold - settings.SIMILARITY_THRESHOLD) <= 1e-9
        and config.retrieval_mode.strip().lower() == "hybrid"
        and config.enable_reranker == settings.ENABLE_RERANKER
        and config.reranker_provider.strip().lower() == settings.RERANKER_PROVIDER.strip().lower()
        and config.reranker_top_n == settings.RERANKER_TOP_N
        and config.enable_weight_rerank
    )


class CitationBbox(BaseModel):
    """PDF/page-space bounding box for precise citation highlighting."""

    x0: int
    y0: int
    x1: int
    y1: int


class Citation(BaseModel):
    """Citation information."""

    model_config = ConfigDict(extra="ignore")

    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_content: str
    matched_terms: list[str] | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    bbox: CitationBbox | None = None
    bbox_page_number: int | None = None
    evidence_start_char: int | None = None
    evidence_end_char: int | None = None
    header_path: str | None = None
    chunk_strategy: str | None = None
    chunk_role: str | None = None
    retrieval_role: str | None = None
    neighbor_of: str | None = None
    hierarchy_basis: str | None = None
    hierarchy_family_key: str | None = None
    family_collapse_key: str | None = None
    family_hit: bool | None = None
    doc_pipeline_key: str | None = None
    pipeline_hash: str | None = None
    relevance_score: float = 0.0
    vector_score: float | None = None
    bm25_score: float | None = None
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
    # Image-related fields.
    has_image: bool = Field(default=False, description="Whether this citation contains an image")
    img_id: str | None = Field(
        default=None, description="Image ID (MinIO format: {tenant_id}:{dataset_id}:{document_id}:{chunk_index})"
    )
    img_url: str | None = Field(default=None, description="Image access URL")
    clean_docx_url: str | None = Field(default=None, description="Optional URL for cleaned DOCX preview/download")


class MessageSchema(OrmModel):
    """Message."""

    id: UUID
    role: str  # user | assistant
    content: str
    citations: list[Citation] = Field(default_factory=list)
    message_metadata: dict[str, Any] | None = None
    created_at: datetime


class ConversationCreate(BaseModel):
    """Create conversation."""

    title: str | None = None
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    """Update conversation fields."""

    title: str | None = Field(default=None, max_length=500)


class ConversationSchema(OrmModel):
    """Conversation session."""

    id: UUID
    title: str | None = None
    last_message: str | None = None
    last_message_at: datetime | None = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    """Conversation detail."""

    conversation_id: UUID
    returned: int = 0
    has_more: bool = False
    messages: list[MessageSchema]


class ConversationList(BaseModel):
    """Conversation list."""

    total: int
    returned: int = 0
    has_more: bool = False
    next_skip: int | None = None
    items: list[ConversationSchema]


class HistoryMessage(BaseModel):
    """History message."""

    role: Literal["user", "assistant"]
    content: str


class ChatRAGConfig(BaseModel):
    """RAG parameters specific to the chat endpoint."""

    model_config = ConfigDict(extra="ignore")

    # An explicit profile takes precedence over the product-facing mode.
    mode: Literal["basic", "contextual", "expanded"] | None = None
    retrieval_profile: str | None = None
    # None inherits the server contract; an empty string disables it for this request.
    retrieval_contract_mode: str | None = None
    must_recall: bool | None = None
    # Citation requirements for must-recall contracts.
    must_recall_expected_source_keys: list[str] | None = None
    must_recall_required_anchor_fields: list[str] | None = None

    # Optional overrides inherit server settings when None.
    intent_router: bool | None = None
    # Policy validation belongs to the intent router at execution time.
    intent_router_policy: dict[str, Any] | None = None
    industry_rules_enabled: bool | None = None
    industry_rules_rulesets: list[str] | None = Field(default=None, max_length=8)

    # A missing alias switch follows whether the effective alias dictionary is nonempty.
    enable_query_alias_expansion: bool | None = None
    query_aliases: dict[str, list[str]] | None = None
    query_alias_max_queries: int | None = Field(default=None, ge=0, le=20)

    # Model-assisted query expansion.
    enable_multi_query: bool | None = None
    multi_query_count: int | None = Field(default=None, ge=1, le=8)
    multi_query_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: int | None = Field(default=None, ge=0, le=2000)
    enable_hyde: bool | None = None
    enable_query_decomposition: bool | None = None

    # Hierarchy recall and family aggregation.
    enable_hierarchy_recall: bool | None = None
    hierarchy_family_collapse: bool | None = None
    hierarchy_family_aggregation: Literal["frequency", "score", "combined"] | None = None
    hierarchy_tree_dedup: bool | None = None
    hierarchy_parent_depth: int | None = Field(default=None, ge=0, le=8)
    hierarchy_sibling_window: int | None = Field(default=None, ge=0, le=16)
    hierarchy_overfetch_factor: int | None = Field(default=None, ge=1, le=32)

    # Knowledge-graph recall and promotion.
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = Field(default=None, ge=0, le=50)
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    kg_chunk_boost_max_promoted: int | None = Field(default=None, ge=0, le=20)

    # Recall limits and answer generation.
    top_k: int = Field(default_factory=lambda: settings.RETRIEVAL_TOP_K, ge=1, le=100)
    score_threshold: float = Field(default_factory=lambda: settings.SIMILARITY_THRESHOLD, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2000, ge=1, le=200_000)
    answer_mode: Literal["llm", "extractive"] = Field(
        default="llm",
        description=(
            "Answer generation mode. 'llm' uses the configured model provider; "
            "'extractive' returns a citation-grounded retrieval summary without calling an LLM."
        ),
    )

    retrieval_mode: str = "hybrid"  # hybrid | vector | keyword | mmr | auto
    alpha: float = Field(default_factory=lambda: settings.RETRIEVAL_DEFAULT_ALPHA, ge=0.0, le=1.0)

    # Fusion strategy inherits server settings when None.
    fusion_strategy: str | None = None
    # budgeted_rrf uses channel quotas and minimum reciprocal-rank scores.
    fusion_budgets: dict[str, int] | None = None
    fusion_min_scores: dict[str, float] | None = None
    # weighted uses channel weights over normalized scores.
    fusion_weights: dict[str, float] | None = None
    # Optional per-request cap for candidate overfetch. None keeps global retrieval defaults.
    retrieval_overfetch_multiplier: int | None = Field(default=None, ge=1, le=20)
    retrieval_overfetch_max_k: int | None = Field(default=None, ge=1, le=500)
    sparse_retrieval_enabled: bool | None = None
    sparse_retrieval_provider: Literal["deterministic"] | None = None

    # Channel weighting and reranking.
    enable_weight_rerank: bool = True
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default_factory=lambda: settings.RETRIEVAL_MMR_LAMBDA, ge=0.0, le=1.0)

    enable_reranker: bool = Field(default_factory=lambda: settings.ENABLE_RERANKER)  # optional: LLM/API rerank
    reranker_provider: str = Field(default_factory=lambda: settings.RERANKER_PROVIDER)  # llm | pc | none

    reranker_top_n: int = Field(default_factory=lambda: settings.RERANKER_TOP_N, ge=1, le=200)

    # Execution path and grounding policy.
    use_graph: bool = False

    # Require visible evidence and post-generation claim checks; streaming may buffer.
    visible_evidence_only: bool = False

    # Optional: metadata filter for vector search / retrieval scoping
    metadata_filter: dict[str, Any] | None = None
    # Request-level budget controls for expensive hybrid fallback channels.
    # None keeps server defaults; False is used by low-latency external retrieval integrations.
    lexical_db_hybrid_fallback_only: bool | None = None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None = None
    metadata_exact_db_fallback_enabled: bool | None = None

    @field_validator("reranker_provider")
    @classmethod
    def _validate_reranker_execution(cls, value: str) -> str:
        reject_retired_provider(value, capability="reranker")
        return value

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, value: Any) -> str:
        return normalize_retrieval_mode(str(value) if value is not None else None)

    @field_validator("retrieval_contract_mode", mode="before")
    @classmethod
    def _normalize_retrieval_contract_mode(cls, value: Any) -> str | None:
        if value is None:
            return None
        mode = normalize_retrieval_contract_mode(value)
        if mode not in VALID_RETRIEVAL_CONTRACT_MODES:
            raise ValueError(
                "retrieval_contract_mode must be one of: " + ", ".join(sorted(VALID_RETRIEVAL_CONTRACT_MODES))
            )
        return mode

    @field_validator(
        "must_recall_expected_source_keys",
        "must_recall_required_anchor_fields",
        "industry_rules_rulesets",
        mode="before",
    )
    @classmethod
    def _normalize_optional_string_list(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            values = value.split(",")
        elif isinstance(value, (list, tuple, set)):
            values = [str(item) for item in value]
        else:
            raise ValueError("must be a list of strings or a comma-separated string")

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)
            if len(cleaned) >= 80:
                break
        return cleaned

    @field_validator("hierarchy_family_aggregation", mode="before")
    @classmethod
    def _normalize_hierarchy_family_aggregation(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(
                "hierarchy_family_aggregation must be one of: " + ", ".join(_HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        raw = value.strip().lower()
        if not raw:
            return None
        if raw not in _HIERARCHY_FAMILY_AGGREGATION_VALUES:
            raise ValueError(
                "hierarchy_family_aggregation must be one of: " + ", ".join(_HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        return raw

    @field_validator("fusion_strategy", mode="after")
    @classmethod
    def _normalize_fusion_strategy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        raw = value.strip().lower()
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

    @field_validator("retrieval_profile")
    @classmethod
    def _validate_profile_execution(cls, value: str | None) -> str | None:
        reject_retired_retrieval_profile(value)
        return value

    @model_validator(mode="after")
    def _validate_fusion_budgets(self) -> "ChatRAGConfig":
        budgets = self.fusion_budgets
        if budgets is not None:
            cleaned_budgets: dict[str, int] = {}
            for channel, budget in budgets.items():
                channel = channel.strip().lower()
                if not channel:
                    continue
                if channel not in _FUSION_CHANNELS:
                    raise ValueError("fusion_budgets keys must be in: vector, bm25, lexical, sparse")
                if budget < 0 or budget > 200:
                    raise ValueError("fusion_budgets values must be between 0 and 200")
                cleaned_budgets[channel] = budget
            budgets = cleaned_budgets
        self.fusion_budgets = budgets

        min_scores = self.fusion_min_scores
        if min_scores is not None:
            cleaned_scores: dict[str, float] = {}
            for channel, min_score in min_scores.items():
                channel = channel.strip().lower()
                if not channel:
                    continue
                if channel not in _FUSION_CHANNELS:
                    raise ValueError("fusion_min_scores keys must be in: vector, bm25, lexical, sparse")
                if min_score < 0.0 or min_score > 1.0:
                    raise ValueError("fusion_min_scores values must be between 0.0 and 1.0")
                cleaned_scores[channel] = min_score
            min_scores = cleaned_scores
        self.fusion_min_scores = min_scores
        return self

    @model_validator(mode="after")
    def _validate_fusion_weights(self) -> "ChatRAGConfig":
        weights = self.fusion_weights
        if weights is None:
            return self

        cleaned: dict[str, float] = {}
        for channel, weight in weights.items():
            channel = channel.strip().lower()
            if not channel:
                continue
            if channel not in _FUSION_CHANNELS:
                raise ValueError("fusion_weights keys must be one of: vector, bm25, lexical, sparse")
            if weight < 0.0 or weight > 1.0:
                raise ValueError("fusion_weights values must be in [0,1]")
            cleaned[channel] = weight

        if not cleaned:
            raise ValueError("fusion_weights must have at least one non-empty key")

        self.fusion_weights = cleaned
        return self

    @model_validator(mode="after")
    def _normalize_channel_weights(self) -> "ChatRAGConfig":
        """Normalize the two channel weights to sum to one when enabled."""
        if not self.enable_weight_rerank:
            return self
        vector_weight = self.vector_weight
        keyword_weight = self.keyword_weight
        total = vector_weight + keyword_weight
        if total <= 0.0:
            raise ValueError("vector_weight + keyword_weight must be > 0 when enable_weight_rerank=true")
        self.vector_weight = vector_weight / total
        self.keyword_weight = keyword_weight / total
        return self

    @model_validator(mode="after")
    def _apply_retrieval_profile(self) -> "ChatRAGConfig":
        """Apply the preset contract, including its overrides of explicit retrieval values."""
        profile = self.retrieval_profile.strip().lower() if self.retrieval_profile is not None else None
        default_profile_applied = False

        if not profile and self.mode is not None:
            profile = _RETRIEVAL_PROFILES_BY_MODE[self.mode]

        # The server default applies only to the existing default-value combination.
        if not profile and _uses_default_retrieval_options(self):
            profile = settings.CHAT_DEFAULT_RETRIEVAL_PROFILE.strip().lower()
            default_profile_applied = bool(profile)

        if not profile:
            self.retrieval_profile = None
            return self

        applied = apply_retrieval_profile_overrides(
            profile=profile,
            top_k=self.top_k,
            score_threshold=self.score_threshold,
            retrieval_mode=self.retrieval_mode,
            enable_reranker=self.enable_reranker,
            reranker_provider=self.reranker_provider,
            reranker_top_n=self.reranker_top_n,
            enable_weight_rerank=self.enable_weight_rerank,
            retrieval_contract_mode=self.retrieval_contract_mode,
            visible_evidence_only=self.visible_evidence_only,
        )
        self.retrieval_profile = applied["retrieval_profile"]
        self.top_k = applied["top_k"]
        self.score_threshold = applied["score_threshold"]
        if applied["retrieval_mode"] is not None:
            self.retrieval_mode = applied["retrieval_mode"]
        if applied["reranker_provider"] is not None:
            self.reranker_provider = applied["reranker_provider"]
        self.reranker_top_n = applied["reranker_top_n"]
        self.enable_reranker = applied["enable_reranker"]
        self.enable_weight_rerank = applied["enable_weight_rerank"]
        self.visible_evidence_only = applied["visible_evidence_only"]
        if applied["retrieval_contract_mode"] is not None:
            self.retrieval_contract_mode = normalize_retrieval_contract_mode(applied["retrieval_contract_mode"])

        # Hierarchy profiles produce this complete group together.
        if "enable_hierarchy_recall" in applied:
            self.enable_hierarchy_recall = applied["enable_hierarchy_recall"]
            self.hierarchy_family_collapse = applied["hierarchy_family_collapse"]
            self.hierarchy_family_aggregation = applied["hierarchy_family_aggregation"]
            self.hierarchy_tree_dedup = applied["hierarchy_tree_dedup"]
            self.hierarchy_parent_depth = applied["hierarchy_parent_depth"]
            self.hierarchy_sibling_window = applied["hierarchy_sibling_window"]
            self.hierarchy_overfetch_factor = applied["hierarchy_overfetch_factor"]
        if "sparse_retrieval_enabled" in applied:
            self.sparse_retrieval_enabled = applied["sparse_retrieval_enabled"]
        if default_profile_applied and settings.CHAT_DEFAULT_VISIBLE_EVIDENCE_ONLY:
            self.visible_evidence_only = True
        return self


class ChatRequest(BaseModel):
    """Chat request."""

    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    history: list[HistoryMessage] = Field(default_factory=list)  # Conversation history.
    # Optional dataset scope. When set and document_ids is empty, retrieval is restricted to this dataset.
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    stream: bool = True
    structured_output: bool = False  # Require structured (JSON) output.
    structured_preset: str | None = None  # faq | summary | action_items | custom
    enable_long_term_memory: bool = False  # Enable long-term memory retrieval.
    enable_summary_memory: bool = False  # Enable persistent summary memory injection (when available).
    enable_structured_memory: bool = False  # Enable structured memory (entities/facts) injection + persistence.
    prompt_template_id: UUID | None = None  # Custom prompt template ID.
    prompt_template_key: str | None = None  # Select latest version by key (optional).
    prompt_ab_experiment_key: str | None = None  # A/B experiment key (optional, stable per-user split).
    rag_config_template_id: UUID | None = None  # RAG config template ID (optional; retrieval/rerank knobs).
    rag_config_template_key: str | None = None  # Select latest RAG config template by key (optional).
    rag_config_ab_experiment_key: str | None = None  # A/B experiment key for RAG config templates (optional).
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)


class TokenUsage(BaseModel):
    """Token usage metadata for a single response."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    source: Literal["provider", "mock", "estimate"] = "estimate"

    @model_validator(mode="after")
    def _normalize_total_tokens(self) -> "TokenUsage":
        """
        Normalize usage invariants so `total_tokens == prompt_tokens + completion_tokens`.

        For estimate-only usage, callers may provide only `total_tokens`; in that case treat it
        as completion-only (prompt=0, completion=total).
        """
        fields_set = self.model_fields_set
        prompt_set = "prompt_tokens" in fields_set
        completion_set = "completion_tokens" in fields_set
        total_set = "total_tokens" in fields_set

        prompt_tokens = self.prompt_tokens
        completion_tokens = self.completion_tokens
        total_tokens = self.total_tokens

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

        self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self


class ChatResponse(BaseModel):
    """Non-streaming chat response payload."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: UUID
    assistant_message_id: UUID
    request_id: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    total_tokens: int = 0
    usage: TokenUsage | None = Field(
        default=None,
        description="Best-effort token usage metadata; currently may be an assistant-only estimate.",
    )
    total_chars: int = 0
    retrieval_mode: str | None = None
    vector_backend: str | None = None
    confidence_score: float | None = None
    followup_questions: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    structured: bool = False
    structured_data: Any = None


class ConversationSummaryResponse(BaseModel):
    available: bool
    summary: str | None = None


class ConversationSummaryUpdateResponse(BaseModel):
    summary: str


class CheckpointItem(BaseModel):
    checkpoint_id: str | None = None
    checkpoint_ns: str = ""
    created_at: datetime | None = None
    next: Any = None
    metadata: dict[str, Any] | None = None
    values: dict[str, Any] | None = None


class CheckpointListResponse(BaseModel):
    thread_id: str
    items: list[CheckpointItem] = Field(default_factory=list)


class CheckpointDetailResponse(BaseModel):
    thread_id: str
    checkpoint_id: str | None = None
    checkpoint_ns: str = ""
    created_at: datetime | None = None
    next: Any = None
    metadata: dict[str, Any] | None = None
    values: dict[str, Any] | None = None
