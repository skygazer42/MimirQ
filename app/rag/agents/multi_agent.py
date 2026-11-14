import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.agents.rag_agent import AgenticStreamRequest, build_agentic_rag_state, resolve_agentic_stream_request
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.logging import get_logger
from app.rag.core.text import heuristic_decompose_query, parse_json_from_text
from app.rag.pipelines.langgraph import _build_context, _build_history_text
from app.rag.retrieval.orchestrator import run_retrieval
from app.services.rag_runtime_limiter import run_blocking_retrieval_call_with_managed_session

if TYPE_CHECKING:
    from app.rag.engine import RAGEngine

logger = get_logger(__name__)

_UNABLE_TO_ANSWER_MESSAGE = "Unable to answer this question based on the available materials."


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
    def __init__(self, engine: "RAGEngine") -> None:
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
            plan_chain = (
                self._engine.decompose_prompt
                | planner_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
                | StrOutputParser()
            )
            raw = await plan_chain.ainvoke({"query": question, "n": max_sub_questions})
            data, _meta = parse_json_from_text(raw, expected="array")
            if isinstance(data, list):
                steps: list[MultiAgentPlanStep] = []
                seen: set[str] = set()
                for item in data:
                    if not isinstance(item, str):
                        continue
                    query = " ".join(item.split()).strip()
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
    def _citation_key(citation: dict[str, Any]) -> tuple[str | None, ...]:
        page_number = citation.get("page_number")
        if page_number is None:
            page_number = citation.get("page")
        snippet = citation.get("snippet")
        if snippet is not None:
            snippet = " ".join(str(snippet).split())
        values = (citation.get("document_id"), citation.get("chunk_id"), page_number, citation.get("source"), snippet)
        return tuple((str(value) or None) if value is not None else None for value in values)

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
        result = await run_blocking_retrieval_call_with_managed_session(
            lambda worker_db: run_retrieval({**state, "db": worker_db}),
            request_db=None,
        )
        elapsed = time.time() - started
        return _SubAgentResult(index=index, query=query, result=result, elapsed_sec=elapsed)

    @staticmethod
    def _stream_route_event(
        *,
        llm: Any,
        complexity_score: float,
        threshold: float,
        routing_reason: str,
        model_route: str,
        base_state: dict[str, Any],
    ) -> dict[str, Any]:
        return {
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

    @staticmethod
    def _normalized_plan_query(step: MultiAgentPlanStep, *, fallback_question: str) -> str:
        return " ".join(step.query.split()).strip() or fallback_question

    @staticmethod
    def _retrieval_started_event(*, index: int, query: str, rationale: str | None) -> dict[str, Any]:
        return {
            "type": "agentic_step",
            "data": {
                "step": "retrieving",
                "status": "started",
                "round": index,
                "query": query,
                "rationale": rationale,
            },
        }

    @staticmethod
    def _retrieval_completed_event(sub_result: _SubAgentResult) -> dict[str, Any]:
        sub_metrics = sub_result.result.get("metrics") or {}
        return {
            "type": "agentic_step",
            "data": {
                "step": "retrieving",
                "status": "completed",
                "round": sub_result.index,
                "query": sub_result.query,
                "docs_count": len(sub_result.result.get("docs") or []),
                "citations_count": len(sub_result.result.get("citations") or []),
                "top_relevance_score": float(sub_metrics.get("top_relevance_score") or 0.0),
            },
        }

    async def _cleanup_retrieval_tasks(self, tasks: list[asyncio.Task[_SubAgentResult]]) -> None:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _stream_retrieval_rounds(
        self,
        *,
        plan_steps: list[MultiAgentPlanStep],
        max_sub_questions: int,
        question: str,
        base_state: dict[str, Any],
        results: list[_SubAgentResult],
    ) -> AsyncIterator[dict[str, Any]]:
        tasks: list[asyncio.Task[_SubAgentResult]] = []
        try:
            for idx, step in enumerate(plan_steps[:max_sub_questions], 1):
                query = self._normalized_plan_query(step, fallback_question=question)
                yield self._retrieval_started_event(index=idx, query=query, rationale=step.rationale)
                sub_agent = self._run_sub_agent(index=idx, query=query, base_state=base_state)
                try:
                    tasks.append(asyncio.create_task(sub_agent))
                except BaseException:
                    sub_agent.close()
                    raise

            for task in asyncio.as_completed(tasks):
                sub_result = await task
                results.append(sub_result)
                yield self._retrieval_completed_event(sub_result)
        finally:
            await self._cleanup_retrieval_tasks(tasks)

    def _collect_retrieval_outputs(
        self,
        *,
        results: list[_SubAgentResult],
        retrieval_mode: str | None,
        question: str,
    ) -> tuple[list[Document], list[dict[str, Any]], str | None, float]:
        results.sort(key=lambda item: item.index)
        retrieval_elapsed_total = float(sum(item.elapsed_sec for item in results))
        docs_by_key: dict[str, Document] = {}
        citations_by_key: dict[tuple[str | None, ...], dict[str, Any]] = {}
        final_retrieval_mode = retrieval_mode

        for item in results:
            result = item.result
            metrics = result.get("metrics") or {}
            final_retrieval_mode = str(metrics.get("retrieval_mode") or final_retrieval_mode)
            for doc in result.get("docs") or []:
                key = self._engine._doc_key(doc)
                existing = docs_by_key.get(key)
                docs_by_key[key] = doc if existing is None else self._engine._prefer_doc(existing, doc)
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
        return collected_docs, citations, final_retrieval_mode, retrieval_elapsed_total

    async def _stream_answer(
        self,
        *,
        collected_docs: list[Document],
        question: str,
        history: list[dict[str, Any]],
        base_state: dict[str, Any],
        llm: Any,
        structured_output: bool,
        answer_state: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        if not collected_docs:
            full_response = _UNABLE_TO_ANSWER_MESSAGE
            answer_state.update(
                {
                    "full_response": full_response,
                    "generation_elapsed": 0.0,
                    "answer_tokens": num_tokens_from_string(full_response),
                    "answer_chars": len(full_response),
                    "structured_data": None,
                }
            )
            yield {"type": "token", "data": {"content": full_response}}
            return

        yield {"type": "agentic_step", "data": {"step": "answering"}}
        prompt_template_content = base_state.get("prompt_template_content")
        prompt_template = (
            ChatPromptTemplate.from_template(str(prompt_template_content))
            if prompt_template_content
            else self._engine.prompt_template
        )
        generation_inputs = {
            "context": _build_context(collected_docs, query=question),
            "history": _build_history_text(history),
            "question": question,
            "format_instructions": base_state["format_instructions"],
        }
        full_response = ""
        gen_start = time.time()
        chain = prompt_template | llm | StrOutputParser()
        async with aclosing(chain.astream(generation_inputs)) as stream_events:
            async for token in stream_events:
                if not token:
                    continue
                token_text = token if isinstance(token, str) else str(token)
                full_response += token_text
                yield {"type": "token", "data": {"content": token_text}}

        structured_data = None
        if structured_output:
            structured_data, _meta = parse_json_from_text(full_response, expected="object")
        answer_state.update(
            {
                "full_response": full_response,
                "generation_elapsed": time.time() - gen_start,
                "answer_tokens": num_tokens_from_string(full_response),
                "answer_chars": len(full_response),
                "structured_data": structured_data,
            }
        )

    @staticmethod
    def _build_done_metrics(
        *,
        t_start: float,
        retrieval_elapsed_total: float,
        generation_elapsed: float,
        final_retrieval_mode: str | None,
        complexity_score: float,
        plan_steps: list[MultiAgentPlanStep],
        max_sub_questions: int,
        threshold: float,
        model_route: str,
        collected_docs: list[Document],
        tasks_count: int,
    ) -> dict[str, Any]:
        return {
            "elapsed_sec": round(time.time() - t_start, 3),
            "retrieval_elapsed_sec": round(retrieval_elapsed_total, 3),
            "generation_elapsed_sec": round(float(generation_elapsed or 0.0), 3),
            "retrieval_mode": final_retrieval_mode,
            "complexity_score": round(float(complexity_score), 3),
            "agentic_used": True,
            "agentic_rounds": tasks_count,
            "agentic_planned_steps": len(plan_steps),
            "agentic_queries": [step.query for step in plan_steps[:max_sub_questions]],
            "agentic_route_reason": f"complexity {complexity_score:.1f} >= threshold {threshold}",
            "model_route": model_route,
            "abstain_triggered": bool(not collected_docs),
            "abstain_reason": "no_docs" if not collected_docs else None,
            "docs_returned": len(collected_docs),
            "multi_agent_parallel_tasks": tasks_count,
        }

    async def stream(
        self,
        *,
        request: AgenticStreamRequest | None = None,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        stream_request = resolve_agentic_stream_request(
            request=request,
            legacy_overrides=_kwargs,
        )
        t_start = time.time()
        question = stream_request.question
        history = list(stream_request.history or [])
        conversation_id = stream_request.conversation_id
        retrieval_mode = stream_request.retrieval_mode
        structured_output = stream_request.structured_output
        complexity_score = self._engine._score_question_complexity(question, history)
        threshold = settings.RAG_AGENTIC_COMPLEXITY_THRESHOLD
        llm, model_route, routing_reason = self._engine._select_llm(question, history)
        max_sub_questions = max(1, settings.RAG_MULTI_AGENT_MAX_SUB_AGENTS)
        base_state = build_agentic_rag_state(stream_request, history=history)

        yield self._stream_route_event(
            llm=llm,
            complexity_score=complexity_score,
            threshold=threshold,
            routing_reason=routing_reason,
            model_route=model_route,
            base_state=base_state,
        )

        yield {"type": "agentic_step", "data": {"step": "planning"}}
        plan_steps = await self._decompose(question=question, llm=llm, max_sub_questions=max_sub_questions)
        if stream_request.db is not None:
            stream_request.db.rollback()

        results: list[_SubAgentResult] = []
        async with aclosing(
            self._stream_retrieval_rounds(
                plan_steps=plan_steps,
                max_sub_questions=max_sub_questions,
                question=question,
                base_state=base_state,
                results=results,
            )
        ) as events:
            async for event in events:
                yield event

        collected_docs, citations, final_retrieval_mode, retrieval_elapsed_total = self._collect_retrieval_outputs(
            results=results,
            retrieval_mode=retrieval_mode,
            question=question,
        )
        yield {"type": "citations", "data": citations}

        answer_state: dict[str, Any] = {}
        async with aclosing(
            self._stream_answer(
                collected_docs=collected_docs,
                question=question,
                history=history,
                base_state=base_state,
                llm=llm,
                structured_output=structured_output,
                answer_state=answer_state,
            )
        ) as events:
            async for event in events:
                yield event

        metrics = self._build_done_metrics(
            t_start=t_start,
            retrieval_elapsed_total=retrieval_elapsed_total,
            generation_elapsed=answer_state["generation_elapsed"],
            final_retrieval_mode=final_retrieval_mode,
            complexity_score=complexity_score,
            plan_steps=plan_steps,
            max_sub_questions=max_sub_questions,
            threshold=threshold,
            model_route=model_route,
            collected_docs=collected_docs,
            tasks_count=len(results),
        )

        yield {
            "type": "done",
            "data": {
                "conversation_id": str(conversation_id) if conversation_id else None,
                "total_tokens": answer_state["answer_tokens"],
                "total_chars": answer_state["answer_chars"],
                "citations_count": len(citations),
                "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                "route": "multi_agent",
                "retrieval_mode": metrics["retrieval_mode"],
                "vector_backend": settings.VECTOR_BACKEND,
                "metrics": metrics,
                "structured": bool(answer_state["structured_data"]),
                "structured_data": answer_state["structured_data"],
            },
        }


_MULTI_AGENT_RUNNER: MultiAgentRAGRunner | None = None
_MULTI_AGENT_LOCK = threading.Lock()


def get_multi_agent_runner(*, engine: "RAGEngine | None" = None) -> MultiAgentRAGRunner:
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
