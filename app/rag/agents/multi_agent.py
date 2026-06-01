from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.agents.rag_agent import AgenticStreamRequest, resolve_agentic_stream_request
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.logging import get_logger
from app.rag.core.text import heuristic_decompose_query, parse_json_from_text
from app.rag.pipelines.langgraph import _build_context, _build_history_text, build_rag_state
from app.rag.retrieval.orchestrator import run_retrieval

if TYPE_CHECKING:
    from app.rag.engine import RAGEngine

logger = get_logger(__name__)

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
    "enable_hyde",
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
    "request_id",
}


@dataclass(frozen=True)
class MultiAgentPlanStep:
    query: str
    rationale: str | None = None


@dataclass(frozen=True)
class _SubAgentResult:
    index: int
    query: str
    result: dict[str, Any]
    elapsed_sec: float


class MultiAgentRAGRunner:
    def __init__(self, engine: RAGEngine) -> None:
        self._engine = engine

    async def _decompose(
        self,
        *,
        question: str,
        llm: Any,
        max_sub_questions: int,
    ) -> list[MultiAgentPlanStep]:
        max_sub_questions = max(1, int(max_sub_questions or 1))
        planner_llm = self._engine.models.get("fast") or llm
        try:
            plan_chain = self._engine.decompose_prompt | planner_llm.bind(
                temperature=float(getattr(settings, "QUERY_DECOMPOSITION_TEMPERATURE", 0.2) or 0.2)
            ) | StrOutputParser()
            raw = await plan_chain.ainvoke({"query": question, "n": max_sub_questions})
            data, _meta = parse_json_from_text(raw, expected="array")
            if isinstance(data, list):
                steps: list[MultiAgentPlanStep] = []
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
                    steps.append(MultiAgentPlanStep(query=query, rationale="llm_decomposition"))
                    if len(steps) >= max_sub_questions:
                        break
                if steps:
                    return steps
        except Exception as exc:
            logger.debug("Ignoring multi-agent LLM decomposition failure: %s", exc)

        heuristic_steps = heuristic_decompose_query(question, max_subquestions=max_sub_questions)
        if heuristic_steps:
            return [MultiAgentPlanStep(query=item, rationale="heuristic_decomposition") for item in heuristic_steps]
        return [MultiAgentPlanStep(query=question, rationale="fallback_single_query")]

    @staticmethod
    def _citation_key(citation: dict[str, Any]) -> str:
        document_id = str(citation.get("document_id") or "")
        chunk_id = str(citation.get("chunk_id") or "")
        page_number = str(citation.get("page_number") or citation.get("page") or "")
        source = str(citation.get("source") or "")
        snippet = " ".join(str(citation.get("snippet") or "").split())
        return "|".join([document_id, chunk_id, page_number, source, snippet])

    @staticmethod
    def _citation_score(citation: dict[str, Any]) -> float:
        try:
            return float(citation.get("relevance_score") or citation.get("retrieval_score") or 0.0)
        except Exception:
            return 0.0

    async def _run_sub_agent(self, *, index: int, query: str, base_state: dict[str, Any]) -> _SubAgentResult:
        state = dict(base_state)
        state["question"] = query
        started = time.time()
        result = await asyncio.to_thread(run_retrieval, state)
        elapsed = time.time() - started
        return _SubAgentResult(index=index, query=query, result=result, elapsed_sec=float(elapsed or 0.0))

    async def stream(
        self,
        *,
        request: AgenticStreamRequest | None = None,
        **_kwargs: Any,
    ):
        stream_request = resolve_agentic_stream_request(
            request=request,
            legacy_overrides=_kwargs,
        )
        t_start = time.time()
        question = stream_request.question
        history = list(stream_request.history or [])
        conversation_id = stream_request.conversation_id
        document_ids = stream_request.document_ids
        tenant_id = stream_request.tenant_id
        account_id = stream_request.account_id
        dataset_id = stream_request.dataset_id
        top_k = stream_request.top_k
        score_threshold = stream_request.score_threshold
        retrieval_mode = stream_request.retrieval_mode
        retrieval_profile = stream_request.retrieval_profile
        structured_output = stream_request.structured_output
        structured_preset = stream_request.structured_preset
        prompt_template_id = stream_request.prompt_template_id
        prompt_template_key = stream_request.prompt_template_key
        prompt_ab_experiment_key = stream_request.prompt_ab_experiment_key
        ab_user_key = stream_request.ab_user_key
        request_id = stream_request.request_id
        db = stream_request.db
        complexity_score = self._engine._score_question_complexity(question, history)
        threshold = float(getattr(settings, "RAG_AGENTIC_COMPLEXITY_THRESHOLD", 250.0) or 250.0)
        llm, model_route, routing_reason = self._engine._select_llm(question, history)
        max_sub_questions = max(1, int(getattr(settings, "RAG_MULTI_AGENT_MAX_SUB_AGENTS", 4) or 4))

        base_state_kwargs = {
            key: value
            for key, value in (stream_request.state_overrides or {}).items()
            if key in _RAG_STATE_BUILD_KEYS
        }
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
                "request_id": request_id,
            }
        )
        base_state = build_rag_state(**base_state_kwargs)

        yield {
            "type": "route",
            "data": {
                "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                "route": "multi_agent",
                "reason": f"complexity {complexity_score:.1f} >= threshold {threshold}; {routing_reason}",
                "model_route": model_route,
                "prompt_template_id": base_state.get("prompt_template_id"),
                "prompt_template_key": base_state.get("prompt_template_key"),
                "prompt_ab_experiment_key": base_state.get("prompt_ab_experiment_key"),
                "prompt_ab_variant": base_state.get("prompt_ab_variant"),
            },
        }

        yield {"type": "agentic_step", "data": {"step": "planning"}}
        plan_steps = await self._decompose(question=question, llm=llm, max_sub_questions=max_sub_questions)

        tasks: list[asyncio.Task[_SubAgentResult]] = []
        for idx, step in enumerate(plan_steps[:max_sub_questions], 1):
            query = " ".join(str(step.query or "").split()).strip() or question
            yield {
                "type": "agentic_step",
                "data": {
                    "step": "retrieving",
                    "status": "started",
                    "round": int(idx),
                    "query": query,
                    "rationale": step.rationale,
                },
            }
            tasks.append(asyncio.create_task(self._run_sub_agent(index=idx, query=query, base_state=base_state)))

        results: list[_SubAgentResult] = []
        for task in asyncio.as_completed(tasks):
            sub_result = await task
            results.append(sub_result)
            sub_metrics = sub_result.result.get("metrics") or {}
            yield {
                "type": "agentic_step",
                "data": {
                    "step": "retrieving",
                    "status": "completed",
                    "round": int(sub_result.index),
                    "query": sub_result.query,
                    "docs_count": int(len(sub_result.result.get("docs") or [])),
                    "citations_count": int(len(sub_result.result.get("citations") or [])),
                    "top_relevance_score": float(sub_metrics.get("top_relevance_score") or 0.0),
                },
            }

        results.sort(key=lambda item: item.index)
        retrieval_elapsed_total = float(sum(item.elapsed_sec for item in results))

        docs_by_key: dict[str, Document] = {}
        citations_by_key: dict[str, dict[str, Any]] = {}
        final_retrieval_mode = retrieval_mode
        for item in results:
            result = item.result
            metrics = result.get("metrics") or {}
            final_retrieval_mode = str(metrics.get("retrieval_mode") or final_retrieval_mode)
            for doc in result.get("docs") or []:
                key = self._engine._doc_key(doc)
                existing = docs_by_key.get(key)
                if existing is None:
                    docs_by_key[key] = doc
                else:
                    docs_by_key[key] = self._engine._prefer_doc(existing, doc)
            for citation in result.get("citations") or []:
                if not isinstance(citation, dict):
                    continue
                key = self._citation_key(citation)
                existing = citations_by_key.get(key)
                if existing is None or self._citation_score(citation) > self._citation_score(existing):
                    citations_by_key[key] = citation

        collected_docs = list(docs_by_key.values())
        citations = list(citations_by_key.values())
        if not citations and collected_docs:
            citations = build_citations_from_docs(
                collected_docs,
                retrieval_elapsed_sec=retrieval_elapsed_total,
                retrieval_mode=final_retrieval_mode,
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
            "retrieval_elapsed_sec": round(retrieval_elapsed_total, 3),
            "generation_elapsed_sec": round(float(generation_elapsed or 0.0), 3),
            "retrieval_mode": final_retrieval_mode,
            "complexity_score": round(float(complexity_score), 3),
            "agentic_used": True,
            "agentic_rounds": int(len(results)),
            "agentic_planned_steps": int(len(plan_steps)),
            "agentic_queries": [step.query for step in plan_steps[:max_sub_questions]],
            "agentic_route_reason": f"complexity {complexity_score:.1f} >= threshold {threshold}",
            "model_route": model_route,
            "abstain_triggered": bool(not collected_docs),
            "abstain_reason": "no_docs" if not collected_docs else None,
            "docs_returned": int(len(collected_docs)),
            "multi_agent_parallel_tasks": int(len(tasks)),
        }

        yield {
            "type": "done",
            "data": {
                "conversation_id": str(conversation_id) if conversation_id else None,
                "total_tokens": int(answer_tokens),
                "total_chars": int(answer_chars),
                "citations_count": len(citations),
                "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                "route": "multi_agent",
                "retrieval_mode": metrics["retrieval_mode"],
                "vector_backend": settings.VECTOR_BACKEND,
                "metrics": metrics,
                "structured": bool(structured_data),
                "structured_data": structured_data,
            },
        }


_MULTI_AGENT_RUNNER: MultiAgentRAGRunner | None = None
_MULTI_AGENT_LOCK = threading.Lock()


def get_multi_agent_runner(*, engine: RAGEngine | None = None) -> MultiAgentRAGRunner:
    global _MULTI_AGENT_RUNNER
    if engine is not None:
        return MultiAgentRAGRunner(engine=engine)
    if _MULTI_AGENT_RUNNER is None:
        with _MULTI_AGENT_LOCK:
            if _MULTI_AGENT_RUNNER is None:
                from app.rag.engine import get_rag_engine

                _MULTI_AGENT_RUNNER = MultiAgentRAGRunner(engine=get_rag_engine())
    return _MULTI_AGENT_RUNNER


def reset_multi_agent_runner() -> None:
    global _MULTI_AGENT_RUNNER
    with _MULTI_AGENT_LOCK:
        _MULTI_AGENT_RUNNER = None


__all__ = ["MultiAgentPlanStep", "MultiAgentRAGRunner", "get_multi_agent_runner", "reset_multi_agent_runner"]
