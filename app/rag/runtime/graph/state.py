"""Persisted RAG state, runtime context and explicit state construction."""

from dataclasses import asdict, dataclass, replace
from typing import Any, TypedDict
from uuid import UUID

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.model_policy import reject_retired_retrieval_options
from app.rag.llm.structured_output import build_structured_output_instructions
from app.rag.retrieval.configuration.profiles import apply_retrieval_profile_overrides
from app.services.documents.pipeline_versions import (
    apply_active_pipeline_metadata_filter as _apply_active_pipeline_metadata_filter,
)
from app.services.prompts.resolver import resolve_prompt_template


@dataclass
class RAGRuntimeContext:
    """Runtime-only context passed to LangGraph nodes (not persisted in state)."""

    request_id: str | None = None
    conversation_id: str | None = None
    tenant_id: str | None = None
    account_id: str | None = None
    user_role: str | None = None
    cancel_event: Any | None = None


class RAGState(TypedDict, total=False):
    """Graph state: question, history, docs, citations, answer, meta.

    Using TypedDict for better type hints and IDE support.
    """

    question: str
    history: list[dict[str, str]]
    document_ids: list[UUID] | None
    dataset_ids: list[UUID] | None
    tenant_id: UUID | None
    account_id: str | None
    dataset_id: UUID | None
    request_id: str | None
    top_k: int
    score_threshold: float
    retrieval_mode: str
    retrieval_profile: str | None
    retrieval_contract_mode: str | None
    must_recall: bool | None
    must_recall_expected_source_keys: list[str] | None
    must_recall_required_anchor_fields: list[str] | None
    intent_router: bool | None
    intent_router_policy: dict[str, Any] | None
    industry_rules_enabled: bool | None
    industry_rules_rulesets: list[str] | str | None
    enable_query_alias_expansion: bool | None
    query_aliases: dict[str, list[str]] | None
    query_alias_max_queries: int | None
    enable_multi_query: bool | None
    multi_query_count: int | None
    multi_query_temperature: float | None
    multi_query_max_chars: int | None
    enable_hyde: bool | None
    enable_query_decomposition: bool | None
    enable_hierarchy_recall: bool | None
    hierarchy_family_collapse: bool | None
    hierarchy_family_aggregation: str | None
    hierarchy_tree_dedup: bool | None
    hierarchy_parent_depth: int | None
    hierarchy_sibling_window: int | None
    hierarchy_overfetch_factor: int | None
    enable_kg_query_expansion: bool | None
    enable_kg_chunk_injection: bool | None
    kg_chunk_injection_max_chunks: int | None
    enable_kg_chunk_boost: bool | None
    kg_chunk_boost_weight: float | None
    kg_chunk_boost_max_promoted: int | None
    enable_query_rewrite: bool | None
    query_rewrite_strategy: str | None
    query_rewrite_temperature: float | None
    query_rewrite_max_chars: int | None
    lexical_db_hybrid_fallback_only: bool | None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None
    metadata_exact_db_fallback_enabled: bool | None
    alpha: float
    enable_weight_rerank: bool
    fusion_strategy: str | None
    fusion_budgets: dict[str, int] | None
    fusion_min_scores: dict[str, float] | None
    fusion_weights: dict[str, float] | None
    retrieval_overfetch_multiplier: int | None
    retrieval_overfetch_max_k: int | None
    vector_weight: float
    keyword_weight: float
    mmr_lambda: float
    enable_reranker: bool
    reranker_provider: str | None
    reranker_top_n: int
    metadata_filter: dict[str, Any] | None
    max_tokens: int | None
    format_instructions: str
    structured_output: bool
    stream_answer: bool
    structured_preset: str | None
    visible_evidence_only: bool
    prompt_template_content: str | None
    prompt_template_id: str | None
    prompt_template_key: str | None
    prompt_ab_experiment_key: str | None
    prompt_ab_variant: str | None
    # Optional: TAG injection (table_store query results) passed in by API layer.
    tag_docs: list[Document] | None
    tag_meta: dict[str, Any] | None
    ontology_enabled: bool
    ontology_context: dict[str, Any]
    ontology_docs: list[Document]
    ontology_prepared: bool
    ontology_action: dict[str, Any]
    conversation_id: UUID | None
    # Output fields
    query_for_retrieval: str | None
    docs: list[Document] | None
    citations: list[dict[str, Any]] | None
    answer: str | None
    route: str | None
    model_used: str | None
    routing_reason: str | None
    metrics: dict[str, Any] | None
    abstain_triggered: bool | None
    abstain_reason: str | None
    followup_questions: list[str] | None
    # Optional: best-effort debug payload (query normalization/expansion provenance).
    query_debug: dict[str, Any] | None
    retrieval_trace: dict[str, Any] | None
    retrieval_degraded: bool | None
    fallback_reason: str | None
    channel_health: dict[str, Any] | None


@dataclass(frozen=True)
class RagStateBuildOptions:
    question: str
    history: list[dict[str, str]] | None = None
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    request_id: str | None = None
    account_id: str | None = None
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] | None = None
    top_k: int = 5
    score_threshold: float = 0.7
    retrieval_mode: str = "hybrid"
    retrieval_profile: str | None = None
    retrieval_contract_mode: str | None = None
    must_recall: bool | None = None
    must_recall_expected_source_keys: list[str] | None = None
    must_recall_required_anchor_fields: list[str] | None = None
    intent_router: bool | None = None
    intent_router_policy: dict[str, Any] | None = None
    industry_rules_enabled: bool | None = None
    industry_rules_rulesets: list[str] | str | None = None
    enable_query_alias_expansion: bool | None = None
    query_aliases: dict[str, list[str]] | None = None
    query_alias_max_queries: int | None = None
    enable_multi_query: bool | None = None
    multi_query_count: int | None = None
    multi_query_temperature: float | None = None
    multi_query_max_chars: int | None = None
    enable_hyde: bool | None = None
    enable_query_decomposition: bool | None = None
    enable_hierarchy_recall: bool | None = None
    hierarchy_family_collapse: bool | None = None
    hierarchy_family_aggregation: str | None = None
    hierarchy_tree_dedup: bool | None = None
    hierarchy_parent_depth: int | None = None
    hierarchy_sibling_window: int | None = None
    hierarchy_overfetch_factor: int | None = None
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = None
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = None
    kg_chunk_boost_max_promoted: int | None = None
    enable_query_rewrite: bool | None = None
    query_rewrite_strategy: str | None = None
    query_rewrite_temperature: float | None = None
    query_rewrite_max_chars: int | None = None
    lexical_db_hybrid_fallback_only: bool | None = None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None = None
    metadata_exact_db_fallback_enabled: bool | None = None
    alpha: float = settings.RETRIEVAL_DEFAULT_ALPHA
    fusion_strategy: str | None = None
    fusion_budgets: dict[str, int] | None = None
    fusion_min_scores: dict[str, float] | None = None
    fusion_weights: dict[str, float] | None = None
    retrieval_overfetch_multiplier: int | None = None
    retrieval_overfetch_max_k: int | None = None
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA
    enable_reranker: bool = settings.ENABLE_RERANKER
    reranker_provider: str | None = settings.RERANKER_PROVIDER
    reranker_top_n: int = settings.RERANKER_TOP_N
    metadata_filter: dict[str, Any] | None = None
    max_tokens: int | None = None
    structured_output: bool = False
    structured_preset: str | None = None
    visible_evidence_only: bool = False
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    ab_user_key: str | None = None
    db: Any | None = None


def build_rag_state(**state_fields: Any) -> dict[str, Any]:
    """Build initial RAG graph state shared by run/stream entrypoints."""

    reject_retired_retrieval_options(state_fields)
    resolved = RagStateBuildOptions(**state_fields)
    # ``db`` is a live SQLAlchemy session and can contain module objects that
    # ``dataclasses.asdict`` cannot deepcopy. Keep deep-copy semantics for the
    # serializable graph inputs while excluding this execution-only dependency.
    state = asdict(replace(resolved, db=None))
    state["history"] = resolved.history or []
    from app.rag.policy.intent_router import normalize_intent_router_policy

    state["intent_router_policy"] = normalize_intent_router_policy(resolved.intent_router_policy)
    state["format_instructions"] = (
        build_structured_output_instructions(resolved.structured_preset) if resolved.structured_output else ""
    )
    state.update(
        _resolve_prompt_template_fields(
            db=resolved.db,
            tenant_id=resolved.tenant_id,
            prompt_template_id=resolved.prompt_template_id,
            prompt_template_key=resolved.prompt_template_key,
            prompt_ab_experiment_key=resolved.prompt_ab_experiment_key,
            ab_user_key=resolved.ab_user_key,
        )
    )
    state["metadata_filter"] = _apply_active_pipeline_metadata_filter(
        db=resolved.db,
        tenant_id=resolved.tenant_id,
        document_ids=resolved.document_ids,
        metadata_filter=resolved.metadata_filter,
    )
    _apply_profile_overrides_to_state(state)
    state["structured_output"] = bool(resolved.structured_output)
    state["visible_evidence_only"] = bool(resolved.visible_evidence_only)
    state.pop("db", None)
    state.pop("ab_user_key", None)
    return state


def _resolve_prompt_template_fields(
    *,
    db: Any,
    tenant_id: UUID | None,
    prompt_template_id: UUID | None,
    prompt_template_key: str | None,
    prompt_ab_experiment_key: str | None,
    ab_user_key: str | None,
) -> dict[str, Any]:
    fields = {
        "prompt_template_content": None,
        "prompt_template_id": None,
        "prompt_template_key": None,
        "prompt_ab_experiment_key": None,
        "prompt_ab_variant": None,
    }
    if not (db and tenant_id and (prompt_template_id or prompt_template_key or prompt_ab_experiment_key)):
        return fields
    chosen = resolve_prompt_template(
        db=db,
        tenant_id=tenant_id,
        prompt_template_id=prompt_template_id,
        template_key=prompt_template_key,
        ab_experiment_key=prompt_ab_experiment_key,
        ab_user_key=ab_user_key,
    )
    if not chosen:
        return fields
    chosen.usage_count += 1
    db.commit()
    fields.update(
        {
            "prompt_template_content": chosen.content,
            "prompt_template_id": str(chosen.id),
            "prompt_template_key": chosen.template_key,
            "prompt_ab_experiment_key": chosen.ab_experiment_key,
            "prompt_ab_variant": chosen.ab_variant,
        }
    )
    return fields


def _apply_profile_overrides_to_state(state: dict[str, Any]) -> None:
    profile_applied = apply_retrieval_profile_overrides(
        profile=state.get("retrieval_profile"),
        top_k=state["top_k"],
        score_threshold=state["score_threshold"],
        retrieval_mode=state["retrieval_mode"],
        enable_reranker=state["enable_reranker"],
        reranker_provider=state["reranker_provider"],
        reranker_top_n=state["reranker_top_n"],
        enable_weight_rerank=state["enable_weight_rerank"],
    )
    state["retrieval_profile"] = profile_applied["retrieval_profile"]
    state["top_k"] = profile_applied["top_k"]
    state["score_threshold"] = profile_applied["score_threshold"]
    if profile_applied["retrieval_mode"] is not None:
        state["retrieval_mode"] = profile_applied["retrieval_mode"]
    for key in (
        "enable_reranker",
        "reranker_provider",
        "reranker_top_n",
        "enable_weight_rerank",
        "enable_hierarchy_recall",
        "hierarchy_family_collapse",
        "hierarchy_family_aggregation",
        "hierarchy_tree_dedup",
        "hierarchy_parent_depth",
        "hierarchy_sibling_window",
        "hierarchy_overfetch_factor",
    ):
        value = profile_applied.get(key)
        if value is not None and value != "":
            state[key] = value
