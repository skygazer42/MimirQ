from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.text import heuristic_decompose_query, parse_json_from_text
from app.rag.pipelines.langgraph import _build_context, _build_history_text, build_rag_state
from app.rag.retrieval.decomposition_chain import build_chained_query, summarize_chain_step
from app.rag.retrieval.orchestrator import run_retrieval

if TYPE_CHECKING:
    from app.rag.engine import RAGEngine

_UNABLE_TO_ANSWER_MESSAGE = "Unable to answer this question based on the available materials."
_RAG_STATE_BUILD_KEYS = {
    "question",
    "history",
    "document_ids",
    "tenant_id",
    "account_id",
    "dataset_id",
    "top_k",
    "score_threshold",
    "retrieval_mode",
    "retrieval_profile",
    "retrieval_contract_mode",
    "must_recall",
    "must_recall_expected_source_keys",
    "must_recall_required_anchor_fields",
    "intent_router",
    "intent_router_policy",
    "enable_query_alias_expansion",
    "query_aliases",
    "query_alias_max_queries",
    "enable_multi_query",
    "multi_query_count",
    "multi_query_temperature",
    "multi_query_max_chars",
    "enable_hierarchy_recall",
    "hierarchy_family_collapse",
    "hierarchy_family_aggregation",
    "hierarchy_tree_dedup",
    "hierarchy_parent_depth",
    "hierarchy_sibling_window",
    "hierarchy_overfetch_factor",
    "enable_query_rewrite",
    "query_rewrite_strategy",
    "query_rewrite_temperature",
    "query_rewrite_max_chars",
    "sparse_retrieval_enabled",
    "sparse_retrieval_provider",
    "alpha",
    "fusion_strategy",
    "fusion_budgets",
    "fusion_min_scores",
    "fusion_weights",
    "enable_weight_rerank",
    "vector_weight",
    "keyword_weight",
    "mmr_lambda",
    "enable_reranker",
    "reranker_provider",
    "reranker_top_n",
    "metadata_filter",
    "structured_output",
    "structured_preset",
    "visible_evidence_only",
    "prompt_template_id",
    "prompt_template_key",
    "prompt_ab_experiment_key",
    "ab_user_key",
    "db",
}


@dataclass(frozen=True)
class AgenticPlanStep:
    query: str
    rationale: str | None = None


class AgenticRAGRunner:
    def __init__(self, engine: RAGEngine) -> None:
        self._engine = engine

    async def _plan(
        self,
        *,
        question: str,
        history: list[dict[str, str]] | None,
        llm: Any,
        max_steps: int,
    ) -> list[AgenticPlanStep]:
        max_steps = max(1, int(max_steps or 1))
        planner_llm = self._engine.models.get("fast") or llm
        try:
            plan_chain = self._engine.decompose_prompt | planner_llm.bind(
                temperature=float(getattr(settings, "QUERY_DECOMPOSITION_TEMPERATURE", 0.2) or 0.2)
            ) | StrOutputParser()
            raw = await plan_chain.ainvoke({"query": question, "n": max_steps})
            data, _meta = parse_json_from_text(raw, expected="array")
            if isinstance(data, list):
                steps: list[AgenticPlanStep] = []
                seen: set[str] = set()
                for item in data:
                    if not isinstance(item, str):
                        continue
                    query = " ".join(str(item or "").split()).strip()
                    if not query:
                        continue
                    key = query.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    steps.append(AgenticPlanStep(query=query, rationale="llm_decomposition"))
                    if len(steps) >= max_steps:
                        break
                if steps:
                    return steps
        except Exception:
            pass

        heuristic_steps = heuristic_decompose_query(question, max_subquestions=max_steps)
        if heuristic_steps:
            return [AgenticPlanStep(query=item, rationale="heuristic_decomposition") for item in heuristic_steps]
        return [AgenticPlanStep(query=question, rationale="fallback_single_query")]

    def _merge_docs(self, docs: list[Document], new_docs: list[Document]) -> list[Document]:
        merged: list[Document] = []
        seen: set[str] = set()
        for doc in list(docs or []) + list(new_docs or []):
            key = self._engine._doc_key(doc)
            if key in seen:
                continue
            seen.add(key)
            merged.append(doc)
        return merged

    @staticmethod
    def _is_sufficient(result: dict[str, Any]) -> bool:
        if bool(result.get("abstain_triggered")):
            return False
        citations = result.get("citations") or []
        metrics = result.get("metrics") or {}
        min_citations = max(1, int(getattr(settings, "RAG_AGENTIC_REFLECT_TOP_CITATIONS_MIN", 1) or 1))
        min_top_score = float(getattr(settings, "RAG_AGENTIC_REFLECT_TOP_SCORE_MIN", 0.35) or 0.35)
        if len(citations) >= min_citations:
            return True
        try:
            return float(metrics.get("top_relevance_score") or 0.0) >= min_top_score
        except Exception:
            return False

    async def stream(
        self,
        *,
        question: str,
        history: list[dict[str, str]] | None = None,
        conversation_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        account_id: str | None = None,
        dataset_id: UUID | None = None,
        top_k: int = 5,
        score_threshold: float = 0.7,
        retrieval_mode: str = "hybrid",
        retrieval_profile: str | None = None,
        structured_output: bool = False,
        structured_preset: str | None = None,
        prompt_template_id: UUID | None = None,
        prompt_template_key: str | None = None,
        prompt_ab_experiment_key: str | None = None,
        ab_user_key: str | None = None,
        request_id: str | None = None,
        db: Any | None = None,
        **_kwargs: Any,
    ):
        t_start = time.time()
        history = history or []
        complexity_score = self._engine._score_question_complexity(question, history)
        threshold = float(getattr(settings, "RAG_AGENTIC_COMPLEXITY_THRESHOLD", 250.0) or 250.0)
        llm, model_route, routing_reason = self._engine._select_llm(question, history)

        base_state_kwargs = {key: value for key, value in _kwargs.items() if key in _RAG_STATE_BUILD_KEYS}
        base_state_kwargs.update(
            {
                "question": question,
                "history": history,
                "document_ids": document_ids,
                "tenant_id": tenant_id,
                "account_id": account_id,
                "dataset_id": dataset_id,
                "top_k": top_k,
                "score_threshold": score_threshold,
                "retrieval_mode": retrieval_mode,
                "retrieval_profile": retrieval_profile,
                "structured_output": structured_output,
                "structured_preset": structured_preset,
                "prompt_template_id": prompt_template_id,
                "prompt_template_key": prompt_template_key,
                "prompt_ab_experiment_key": prompt_ab_experiment_key,
                "ab_user_key": ab_user_key,
                "db": db,
            }
        )
        base_state = build_rag_state(**base_state_kwargs)

        yield {
            "type": "route",
            "data": {
                "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                "route": "agentic",
                "reason": f"complexity {complexity_score:.1f} >= threshold {threshold}; {routing_reason}",
                "model_route": model_route,
                "prompt_template_id": base_state.get("prompt_template_id"),
                "prompt_template_key": base_state.get("prompt_template_key"),
                "prompt_ab_experiment_key": base_state.get("prompt_ab_experiment_key"),
                "prompt_ab_variant": base_state.get("prompt_ab_variant"),
            },
        }

        max_rounds = max(1, int(getattr(settings, "RAG_AGENTIC_MAX_RETRIEVE_ROUNDS", 3) or 3))
        yield {"type": "agentic_step", "data": {"step": "planning"}}
        plan_steps = await self._plan(question=question, history=history, llm=llm, max_steps=max_rounds)

        collected_docs: list[Document] = []
        prior_findings: list[str] = []
        retrieval_elapsed_total = 0.0
        rounds_executed = 0
        final_result: dict[str, Any] = {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": retrieval_mode},
            "abstain_triggered": True,
            "abstain_reason": "no_rounds",
        }

        for round_idx, step in enumerate(plan_steps[:max_rounds], 1):
            retrieval_query = build_chained_query(step.query, prior_findings) or step.query
            yield {
                "type": "agentic_step",
                "data": {
                    "step": "retrieving",
                    "round": int(round_idx),
                    "query": retrieval_query,
                    "rationale": step.rationale,
                },
            }
            round_state = dict(base_state)
            round_state["question"] = retrieval_query
            round_started = time.time()
            result = run_retrieval(round_state)
            retrieval_elapsed_total += time.time() - round_started
            rounds_executed = round_idx
            final_result = result
            collected_docs = self._merge_docs(collected_docs, list(result.get("docs") or []))
            step_summary = summarize_chain_step(list(result.get("citations") or []))
            if step_summary:
                prior_findings.append(step_summary)
            if self._is_sufficient(result):
                break

        citations = build_citations_from_docs(
            collected_docs,
            retrieval_elapsed_sec=float(retrieval_elapsed_total or 0.0),
            retrieval_mode=str((final_result.get("metrics") or {}).get("retrieval_mode") or retrieval_mode),
            query=question,
        )
        yield {"type": "citations", "data": citations}

        if not collected_docs:
            full_response = _UNABLE_TO_ANSWER_MESSAGE
            yield {"type": "token", "data": {"content": full_response}}
            generation_elapsed = 0.0
            answer_tokens = num_tokens_from_string(full_response)
            answer_chars = len(full_response)
            structured_data = None
        else:
            yield {"type": "agentic_step", "data": {"step": "answering"}}
            prompt_template_content = base_state.get("prompt_template_content")
            prompt_template = (
                ChatPromptTemplate.from_template(str(prompt_template_content))
                if prompt_template_content
                else self._engine.prompt_template
            )
            history_text = _build_history_text(history)
            context = _build_context(collected_docs, query=question)
            format_instructions = str(base_state.get("format_instructions") or "")
            generation_inputs = {
                "context": context,
                "history": history_text,
                "question": question,
                "format_instructions": format_instructions,
            }
            full_response = ""
            gen_start = time.time()
            chain = prompt_template | llm | StrOutputParser()
            async for token in chain.astream(generation_inputs):
                if not token:
                    continue
                token_text = token if isinstance(token, str) else str(token)
                full_response += token_text
                yield {"type": "token", "data": {"content": token_text}}
            generation_elapsed = time.time() - gen_start
            answer_tokens = num_tokens_from_string(full_response)
            answer_chars = len(full_response)
            structured_data = None
            if structured_output:
                structured_data, _meta = parse_json_from_text(full_response, expected="object")

        metrics = {
            "elapsed_sec": round(time.time() - t_start, 3),
            "retrieval_elapsed_sec": round(float(retrieval_elapsed_total or 0.0), 3),
            "generation_elapsed_sec": round(float(generation_elapsed or 0.0), 3),
            "retrieval_mode": str((final_result.get("metrics") or {}).get("retrieval_mode") or retrieval_mode),
            "complexity_score": round(float(complexity_score), 3),
            "agentic_used": True,
            "agentic_rounds": int(rounds_executed),
            "agentic_planned_steps": int(len(plan_steps)),
            "agentic_queries": [step.query for step in plan_steps[:max_rounds]],
            "agentic_route_reason": f"complexity {complexity_score:.1f} >= threshold {threshold}",
            "model_route": model_route,
            "abstain_triggered": bool(final_result.get("abstain_triggered")),
            "abstain_reason": final_result.get("abstain_reason"),
            "docs_returned": int(len(collected_docs)),
        }

        yield {
            "type": "done",
            "data": {
                "conversation_id": str(conversation_id) if conversation_id else None,
                "total_tokens": int(answer_tokens),
                "total_chars": int(answer_chars),
                "citations_count": len(citations),
                "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                "route": "agentic",
                "retrieval_mode": metrics["retrieval_mode"],
                "vector_backend": settings.VECTOR_BACKEND,
                "metrics": metrics,
                "structured": bool(structured_data),
                "structured_data": structured_data,
            },
        }


_AGENTIC_RUNNER: AgenticRAGRunner | None = None
_AGENTIC_LOCK = threading.Lock()


def get_agentic_runner(*, engine: RAGEngine | None = None) -> AgenticRAGRunner:
    global _AGENTIC_RUNNER
    if engine is not None:
        return AgenticRAGRunner(engine=engine)
    if _AGENTIC_RUNNER is None:
        with _AGENTIC_LOCK:
            if _AGENTIC_RUNNER is None:
                from app.rag.engine import get_rag_engine

                _AGENTIC_RUNNER = AgenticRAGRunner(engine=get_rag_engine())
    return _AGENTIC_RUNNER


__all__ = ["AgenticPlanStep", "AgenticRAGRunner", "get_agentic_runner"]
