"""Run retrieval through its ordered business stages."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.rag.llm.prompts.templates import format_history_text
from app.rag.policy.intent_router import route_intent
from app.rag.retrieval.stages.abstention import _run_retrieval_abstain_hardcase_phase
from app.rag.retrieval.stages.diagnostics import (
    _run_retrieval_channel_health_phase,
    _run_retrieval_metrics_core_phase,
    _run_retrieval_metrics_features_phase,
    _run_retrieval_parse_quality_phase,
)
from app.rag.retrieval.stages.followup import (
    _run_retrieval_citations_hard_fallback_phase,
    _run_retrieval_contextual_followup_phase,
)
from app.rag.retrieval.stages.fusion import _run_retrieval_fusion_phase
from app.rag.retrieval.stages.knowledge_graph import (
    _run_retrieval_kg_injection_phase,
    _run_retrieval_tag_kg_boost_phase,
)
from app.rag.retrieval.stages.preparation import (
    _build_no_retrieval_response,
    _run_retrieval_alias_dictionary_phase,
    _run_retrieval_bootstrap_phase,
    _run_retrieval_decomposition_variants_phase,
    _run_retrieval_hyde_phase,
    _run_retrieval_kg_query_expansion_phase,
    _run_retrieval_multi_query_phase,
    _run_retrieval_step_back_phase,
)
from app.rag.retrieval.stages.refinement import _run_retrieval_post_rerank_hierarchy_setup_phase
from app.rag.retrieval.stages.requirements import _run_retrieval_must_recall_phase
from app.rag.retrieval.stages.result import _run_retrieval_config_and_result_phase
from app.rag.retrieval.stages.search import _run_retrieval_retrieval_execution_phase
from app.rag.retrieval.stages.state import RetrievalRuntimeState, run_retrieval_runtime
from app.rag.retrieval.stages.tracing import _run_retrieval_query_debug_phase, _run_retrieval_retrieval_trace_phase

_RETRIEVAL_RUNTIME_PHASES = (
    _run_retrieval_bootstrap_phase,
    _run_retrieval_alias_dictionary_phase,
    _run_retrieval_kg_query_expansion_phase,
    _run_retrieval_multi_query_phase,
    _run_retrieval_hyde_phase,
    _run_retrieval_step_back_phase,
    _run_retrieval_decomposition_variants_phase,
    _run_retrieval_retrieval_execution_phase,
    _run_retrieval_fusion_phase,
    _run_retrieval_kg_injection_phase,
    _run_retrieval_tag_kg_boost_phase,
    _run_retrieval_post_rerank_hierarchy_setup_phase,
    _run_retrieval_contextual_followup_phase,
    _run_retrieval_citations_hard_fallback_phase,
    _run_retrieval_must_recall_phase,
    _run_retrieval_parse_quality_phase,
    _run_retrieval_metrics_core_phase,
    _run_retrieval_channel_health_phase,
    _run_retrieval_metrics_features_phase,
    _run_retrieval_abstain_hardcase_phase,
    _run_retrieval_query_debug_phase,
    _run_retrieval_retrieval_trace_phase,
    _run_retrieval_config_and_result_phase,
)


def run_retrieval(state: dict[str, Any]) -> dict[str, Any]:
    """Execute retrieval only and return an updated RAG-like state dict."""
    question = state["question"]
    history_text = format_history_text(state.get("history"), window=settings.CHAT_HISTORY_WINDOW)
    no_retrieval_intent = route_intent(question)
    if no_retrieval_intent["skip_retrieval"]:
        return _build_no_retrieval_response(
            state,
            question=question,
            no_retrieval_intent=no_retrieval_intent,
        )
    state = dict(state)
    runtime = RetrievalRuntimeState(state=state, question=question, history_text=history_text)
    if state.get("ontology_enabled") and not state.get("ontology_prepared") and state.get("dataset_id") is not None:
        from app.services.chat.enterprise_ontology import attach_ontology_evidence, prepare_ontology_evidence

        def read_ontology():
            with SessionLocal() as ontology_db:
                return prepare_ontology_evidence(
                    ontology_db,
                    tenant_id=state["tenant_id"],
                    account_id=state["account_id"],
                    dataset_id=state["dataset_id"],
                    document_ids=state.get("document_ids"),
                    question=question,
                    history=state.get("history"),
                    conversation_id=state.get("conversation_id"),
                )

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-ontology") as pool:
            pending = pool.submit(copy_context().run, read_ontology)

            def join_ontology(ctx):
                ctx.state = attach_ontology_evidence(ctx.state, pending.result())

            phases = list(_RETRIEVAL_RUNTIME_PHASES)
            phases.insert(phases.index(_run_retrieval_citations_hard_fallback_phase), join_ontology)
            return run_retrieval_runtime(runtime, phases=phases)
    return run_retrieval_runtime(runtime, phases=_RETRIEVAL_RUNTIME_PHASES)


__all__ = ["run_retrieval"]
