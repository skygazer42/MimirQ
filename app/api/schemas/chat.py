"""
Chat-related Pydantic schemas.
"""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides
from app.rag.core.text import normalize_retrieval_mode
from app.rag.retrieval.contract import (
    VALID_RETRIEVAL_CONTRACT_MODES,
    normalize_retrieval_contract_mode,
)

from .base import OrmModel

HIERARCHY_FAMILY_AGGREGATION_VALUES = ("frequency", "score", "combined")


class Citation(BaseModel):
    """Citation information."""
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_content: str
    matched_terms: list[str] | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    start_char: int | None = None
    end_char: int | None = None
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
    img_id: str | None = Field(default=None, description="Image ID (MinIO format: {tenant_id}:{dataset_id}:{document_id}:{chunk_index})")
    img_url: str | None = Field(default=None, description="Image access URL")
    clean_docx_url: str | None = Field(default=None, description="Optional URL for cleaned DOCX preview/download")

    model_config = ConfigDict(extra="ignore")


class MessageSchema(OrmModel):
    """Message."""
    id: UUID
    role: str  # user | assistant
    content: str
    citations: list[Citation] = []
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
    items: list[ConversationSchema]


class HistoryMessage(BaseModel):
    """History message."""
    role: str  # user | assistant
    content: str


class ChatRAGConfig(BaseModel):
    """RAG parameters specific to the chat endpoint."""

    # Product-facing retrieval tier alias.
    # - basic: production baseline (hybrid_ce)
    # - contextual: long-context synthesis preset (long_context)
    # - expanded: recall-first + context expansion preset (expanded)
    #
    # When both `mode` and `retrieval_profile` are provided, explicit `retrieval_profile` wins.
    mode: Literal["basic", "contextual", "expanded"] | None = None

    # Optional retrieval preset (applies internal recall-first overrides).
    # Supported:
    # - "recall20": maximize chunk-level Hit@20 (top_k>=20, score_threshold=0.0)
    # - "recall50": recall-first for larger corpora (top_k>=50, score_threshold=0.0)
    # - "coverage80": aggressive recall/coverage preset (top_k>=80, score_threshold=0.0)
    # - "expanded": recall-first expansion preset (hierarchy recall + parent/sibling context expansion)
    # - "hybrid_ce": explicit production baseline (hybrid recall; cross-encoder only when reranker stays enabled)
    retrieval_profile: str | None = None
    # Optional retrieval contract override.
    # - None: use server default RETRIEVAL_CONTRACT_MODE
    # - "": disable contract for this request
    # - deterministic_recall | must_recall_strict | evidence_strict | audit_trace
    retrieval_contract_mode: str | None = None
    # Request-level must-recall switch. None = use server/runtime defaults.
    must_recall: bool | None = None
    # Optional contract keys that must be represented by citations (e.g. table_id/source_table/doc_name).
    must_recall_expected_source_keys: list[str] | None = None
    # Optional citation anchor fields that must be present for must-recall.
    must_recall_required_anchor_fields: list[str] | None = None
    # Optional intent router: when enabled, the system may override retrieval knobs based on
    # query intent (faq/howto/api/log). This is deterministic and PII-safe (no raw query in outputs).
    #
    # None means "use server default" (settings.RAG_INTENT_ROUTER_ENABLED).
    intent_router: bool | None = None
    # Optional tenant/dataset policy overlay for the deterministic intent router.
    # This is transport-only here; runtime validation stays inside app.rag.policy.intent_router.
    intent_router_policy: dict[str, Any] | None = None

    # Controlled query expansion for recall (optional).
    # - query_aliases: dataset-scoped alias/synonym dictionary.
    # - enable_query_alias_expansion:
    #     - True  -> apply aliases when present
    #     - False -> disable even if aliases exist
    #     - None  -> default to enabled iff query_aliases is non-empty (dataset defaults can set this)
    enable_query_alias_expansion: bool | None = None
    query_aliases: dict[str, list[str]] | None = None
    query_alias_max_queries: int | None = Field(default=None, ge=0, le=20)

    # Optional: per-request overrides for LLM multi-query generation (inherits global settings when None).
    enable_multi_query: bool | None = None
    multi_query_count: int | None = Field(default=None, ge=1, le=8)
    multi_query_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: int | None = Field(default=None, ge=0, le=2000)
    enable_hyde: bool | None = None
    enable_query_decomposition: bool | None = None

    # Optional hierarchy-aware recall overlay.
    enable_hierarchy_recall: bool | None = None
    hierarchy_family_collapse: bool | None = None
    hierarchy_family_aggregation: Literal["frequency", "score", "combined"] | None = None
    hierarchy_tree_dedup: bool | None = None
    hierarchy_parent_depth: int | None = Field(default=None, ge=0, le=8)
    hierarchy_sibling_window: int | None = Field(default=None, ge=0, le=16)
    hierarchy_overfetch_factor: int | None = Field(default=None, ge=1, le=32)

    # Optional KG-assisted retrieval controls. None means use server settings.
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = Field(default=None, ge=0, le=50)
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    kg_chunk_boost_max_promoted: int | None = Field(default=None, ge=0, le=20)

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

    retrieval_mode: str = Field(default="hybrid")  # hybrid | vector | keyword | mmr | auto
    alpha: float = Field(default_factory=lambda: settings.RETRIEVAL_DEFAULT_ALPHA, ge=0.0, le=1.0)
    # hybrid merge weight: vector vs keyword
    # Retrieval channel fusion strategy override. When None, uses settings.RETRIEVAL_FUSION_STRATEGY.
    # Supported:
    # - linear: min-max normalize each channel then alpha-blend
    # - rrf: reciprocal-rank fusion (score normalized for UI)
    # - budgeted_rrf: RRF scoring but enforce per-channel quotas in the visible top-k prefix
    # - weighted: weighted sum across normalized channel scores (requires fusion_weights for effect)
    fusion_strategy: str | None = None
    # Only used by fusion_strategy=budgeted_rrf (ignored otherwise).
    # Example: {"vector": 25, "bm25": 10, "lexical": 10, "sparse": 5}
    fusion_budgets: dict[str, int] | None = None
    # Only used by fusion_strategy=budgeted_rrf (ignored otherwise).
    # Per-channel minimum rank score in [0,1], where rank_score is 1/rank (rank starts at 1).
    fusion_min_scores: dict[str, float] | None = None
    # Only used by fusion_strategy=weighted (ignored otherwise).
    # Per-channel weights over normalized scores.
    # Allowed keys: vector, bm25, lexical, sparse.
    fusion_weights: dict[str, float] | None = None

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
    metadata_filter: dict[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v: Any) -> str:
        return normalize_retrieval_mode(str(v) if v is not None else None)

    @field_validator("retrieval_contract_mode", mode="before")
    @classmethod
    def _normalize_retrieval_contract_mode(cls, v: Any) -> str | None:
        if v is None:
            return None
        mode = normalize_retrieval_contract_mode(v)
        if mode not in VALID_RETRIEVAL_CONTRACT_MODES:
            raise ValueError(
                "retrieval_contract_mode must be one of: "
                + ", ".join(sorted(VALID_RETRIEVAL_CONTRACT_MODES))
            )
        return mode

    @field_validator("must_recall_expected_source_keys", "must_recall_required_anchor_fields", mode="before")
    @classmethod
    def _normalize_optional_string_list(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        values: list[str] = []
        if isinstance(v, str):
            values = [p.strip() for p in v.split(",")]
        elif isinstance(v, (list, tuple, set)):
            values = [str(x).strip() for x in v]
        else:
            raise ValueError("must be a list of strings or a comma-separated string")

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            s = str(item or "").strip()
            if not s:
                continue
            key = s.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(s)
            if len(cleaned) >= 80:
                break
        return cleaned or None

    @field_validator("hierarchy_family_aggregation", mode="before")
    @classmethod
    def _normalize_hierarchy_family_aggregation(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(
                "hierarchy_family_aggregation must be one of: "
                + ", ".join(HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        raw = v.strip().lower()
        if not raw:
            return None
        if raw not in HIERARCHY_FAMILY_AGGREGATION_VALUES:
            raise ValueError(
                "hierarchy_family_aggregation must be one of: "
                + ", ".join(HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        return raw

    @field_validator("fusion_strategy", mode="before")
    @classmethod
    def _normalize_fusion_strategy(cls, v: Any) -> str | None:
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
            cleaned: dict[str, int] = {}
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
            cleaned2: dict[str, float] = {}
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

        cleaned: dict[str, float] = {}
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
        mode = str(self.mode or "").strip().lower()
        default_profile_applied = False

        if not p and mode:
            mode_to_profile = {
                "basic": "hybrid_ce",
                "contextual": "long_context",
                "expanded": "expanded",
            }
            p = mode_to_profile.get(mode, "")

        # Request-level default retrieval profile:
        # apply only when caller omitted retrieval_profile and did not provide explicit retrieval knobs.
        if not p:
            default_top_k = int(getattr(settings, "RETRIEVAL_TOP_K", 10) or 10)
            default_score_threshold = float(getattr(settings, "SIMILARITY_THRESHOLD", 0.0) or 0.0)
            default_retrieval_mode = "hybrid"
            default_enable_reranker = bool(getattr(settings, "ENABLE_RERANKER", False))
            default_reranker_provider = str(getattr(settings, "RERANKER_PROVIDER", "") or "").strip().lower()
            default_reranker_top_n = int(getattr(settings, "RERANKER_TOP_N", 20) or 20)
            default_enable_weight_rerank = True

            knobs_appear_omitted = (
                int(self.top_k or 0) == int(default_top_k)
                and abs(float(self.score_threshold or 0.0) - float(default_score_threshold)) <= 1e-9
                and str(self.retrieval_mode or "").strip().lower() == default_retrieval_mode
                and bool(self.enable_reranker) is default_enable_reranker
                and str(self.reranker_provider or "").strip().lower() == default_reranker_provider
                and int(self.reranker_top_n or 0) == int(default_reranker_top_n)
                and bool(self.enable_weight_rerank) is default_enable_weight_rerank
            )
            if knobs_appear_omitted:
                p = str(getattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "") or "").strip().lower()
                default_profile_applied = bool(p)

        if not p:
            self.retrieval_profile = None
            return self

        applied = apply_retrieval_profile_overrides(
            profile=p,
            top_k=int(self.top_k or 0),
            score_threshold=float(self.score_threshold or 0.0),
            retrieval_mode=self.retrieval_mode,
            enable_reranker=self.enable_reranker,
            reranker_provider=self.reranker_provider,
            reranker_top_n=int(self.reranker_top_n or 0),
            enable_weight_rerank=self.enable_weight_rerank,
            retrieval_contract_mode=self.retrieval_contract_mode,
            visible_evidence_only=self.visible_evidence_only,
        )
        self.retrieval_profile = applied["retrieval_profile"]
        self.top_k = int(applied["top_k"])
        self.score_threshold = float(applied["score_threshold"])
        if applied.get("retrieval_mode"):
            self.retrieval_mode = str(applied["retrieval_mode"])
        if applied.get("enable_reranker") is not None:
            self.enable_reranker = bool(applied["enable_reranker"])
        if applied.get("reranker_provider"):
            self.reranker_provider = str(applied["reranker_provider"])
        if applied.get("reranker_top_n") is not None:
            self.reranker_top_n = int(applied["reranker_top_n"])
        if applied.get("enable_weight_rerank") is not None:
            self.enable_weight_rerank = bool(applied["enable_weight_rerank"])
        if applied.get("retrieval_contract_mode") is not None:
            self.retrieval_contract_mode = normalize_retrieval_contract_mode(applied["retrieval_contract_mode"])
        if applied.get("visible_evidence_only") is not None:
            self.visible_evidence_only = bool(applied["visible_evidence_only"])
        if applied.get("enable_hierarchy_recall") is not None:
            self.enable_hierarchy_recall = bool(applied["enable_hierarchy_recall"])
        if applied.get("hierarchy_family_collapse") is not None:
            self.hierarchy_family_collapse = bool(applied["hierarchy_family_collapse"])
        if applied.get("hierarchy_family_aggregation") is not None:
            self.hierarchy_family_aggregation = str(applied["hierarchy_family_aggregation"])
        if applied.get("hierarchy_tree_dedup") is not None:
            self.hierarchy_tree_dedup = bool(applied["hierarchy_tree_dedup"])
        if applied.get("hierarchy_parent_depth") is not None:
            self.hierarchy_parent_depth = int(applied["hierarchy_parent_depth"])
        if applied.get("hierarchy_sibling_window") is not None:
            self.hierarchy_sibling_window = int(applied["hierarchy_sibling_window"])
        if applied.get("hierarchy_overfetch_factor") is not None:
            self.hierarchy_overfetch_factor = int(applied["hierarchy_overfetch_factor"])
        if default_profile_applied and bool(getattr(settings, "CHAT_DEFAULT_VISIBLE_EVIDENCE_ONLY", False)):
            self.visible_evidence_only = True
        return self

class ChatRequest(BaseModel):
    """Chat request."""
    conversation_id: UUID | None = None
    message: str
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

    model_config = ConfigDict(extra="ignore")


class StreamEvent(BaseModel):
    """Stream event."""
    type: str  # citations | token | done | error
    data: Any


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
