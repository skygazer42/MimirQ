import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.logging import get_logger
from app.rag.core.text import heuristic_decompose_query, parse_json_from_text
from app.rag.pipelines.langgraph import _build_context, _build_history_text, build_rag_state
from app.rag.retrieval.decomposition_chain import build_chained_query, summarize_chain_step
from app.rag.retrieval.orchestrator import run_retrieval
from app.rag.workflows.crag_streaming import run_crag_streaming
from app.rag.workflows.critic import run_critic_review
from app.rag.workflows.self_rag import run_self_rag_reflection
from app.services.rag_runtime_limiter import run_blocking_retrieval_call_with_managed_session

if TYPE_CHECKING:
    from app.rag.engine import RAGEngine

logger = get_logger(__name__)

_UNABLE_TO_ANSWER_MESSAGE = "Unable to answer this question based on the available materials."
_RAG_STATE_BUILD_KEYS = {
    "question",
    "history",
    "document_ids",
    "dataset_ids",
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
}


@dataclass(frozen=True)
class AgenticPlanStep:
    query: str
    rationale: str | None = None


@dataclass(frozen=True)
class AgenticToolInvocation:
    name: str
    arguments: dict[str, Any]
    rationale: str | None = None


@dataclass(frozen=True)
class AgenticStreamRequest:
    question: str
    history: list[dict[str, Any]] | None = None
    conversation_id: UUID | None = None
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    account_id: str | None = None
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] | None = None
    top_k: int = 5
    score_threshold: float = 0.7
    retrieval_mode: str = "hybrid"
    retrieval_profile: str | None = None
    structured_output: bool = False
    structured_preset: str | None = None
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    ab_user_key: str | None = None
    request_id: str | None = None
    db: Any | None = None
    state_overrides: dict[str, Any] | None = None


@dataclass
class _AgenticRetrievalState:
    collected_docs: list[Document] = field(default_factory=list)
    prior_findings: list[str] = field(default_factory=list)
    retrieval_elapsed_total: float = 0.0
    rounds_executed: int = 0
    tool_context_blocks: list[str] = field(default_factory=list)
    tool_metrics: list[dict[str, Any]] = field(default_factory=list)
    final_result: dict[str, Any] = field(
        default_factory=lambda: {
            "docs": [],
            "citations": [],
            "metrics": {},
            "abstain_triggered": True,
            "abstain_reason": "no_rounds",
        }
    )
    crag_used: bool = False
    crag_provider: str | None = None
    crag_web_results: int = 0


@dataclass
class _AgenticGenerationState:
    full_response: str = ""
    generation_elapsed: float = 0.0
    answer_tokens: int = 0
    answer_chars: int = 0
    structured_data: dict[str, Any] | None = None
    self_rag_reflection: dict[str, Any] | None = None
    critic_review: dict[str, Any] | None = None


_AGENTIC_STREAM_REQUEST_KEYS = {
    "question",
    "history",
    "conversation_id",
    "document_ids",
    "dataset_ids",
    "tenant_id",
    "account_id",
    "dataset_id",
    "top_k",
    "score_threshold",
    "retrieval_mode",
    "retrieval_profile",
    "structured_output",
    "structured_preset",
    "prompt_template_id",
    "prompt_template_key",
    "prompt_ab_experiment_key",
    "ab_user_key",
    "request_id",
    "db",
    "state_overrides",
}


def resolve_agentic_stream_request(
    *,
    request: AgenticStreamRequest | None,
    legacy_overrides: dict[str, Any],
) -> AgenticStreamRequest:
    if request is None:
        state_overrides = {
            key: value for key, value in legacy_overrides.items() if key not in _AGENTIC_STREAM_REQUEST_KEYS
        }
        return AgenticStreamRequest(
            question=str(legacy_overrides.get("question") or ""),
            history=legacy_overrides.get("history"),
            conversation_id=legacy_overrides.get("conversation_id"),
            document_ids=legacy_overrides.get("document_ids"),
            dataset_ids=legacy_overrides.get("dataset_ids"),
            tenant_id=legacy_overrides.get("tenant_id"),
            account_id=legacy_overrides.get("account_id"),
            dataset_id=legacy_overrides.get("dataset_id"),
            top_k=int(legacy_overrides.get("top_k", 5) or 5),
            score_threshold=float(legacy_overrides.get("score_threshold", 0.7) or 0.7),
            retrieval_mode=str(legacy_overrides.get("retrieval_mode") or "hybrid"),
            retrieval_profile=legacy_overrides.get("retrieval_profile"),
            structured_output=bool(legacy_overrides.get("structured_output", False)),
            structured_preset=legacy_overrides.get("structured_preset"),
            prompt_template_id=legacy_overrides.get("prompt_template_id"),
            prompt_template_key=legacy_overrides.get("prompt_template_key"),
            prompt_ab_experiment_key=legacy_overrides.get("prompt_ab_experiment_key"),
            ab_user_key=legacy_overrides.get("ab_user_key"),
            request_id=legacy_overrides.get("request_id"),
            db=legacy_overrides.get("db"),
            state_overrides=state_overrides or None,
        )
    if not legacy_overrides:
        return request
    updated_fields: dict[str, Any] = {}
    state_overrides = dict(request.state_overrides or {})
    for key, value in legacy_overrides.items():
        if key in _AGENTIC_STREAM_REQUEST_KEYS:
            updated_fields[key] = value
        else:
            state_overrides[key] = value
    if state_overrides != dict(request.state_overrides or {}):
        updated_fields["state_overrides"] = state_overrides
    if not updated_fields:
        return request
    return cast(AgenticStreamRequest, replace(request, **updated_fields))


def get_agentic_tool_registry() -> Any:
    from app.rag.tools.mcp_client import get_mcp_registry
    from app.rag.tools.mcp_tools import register_default_tools

    registry = get_mcp_registry()
    return register_default_tools(registry)


def get_multi_agent_runner(*, engine: "RAGEngine | None" = None) -> Any:
    from app.rag.agents.multi_agent import get_multi_agent_runner as _get_multi_agent_runner

    return _get_multi_agent_runner(engine=engine)


class AgenticRAGRunner:
    def __init__(self, engine: "RAGEngine") -> None:
        self._engine = engine

    async def _plan(
        self,
        *,
        question: str,
        llm: Any,
        max_steps: int,
    ) -> list[AgenticPlanStep]:
        max_steps = max(1, int(max_steps or 1))
        planner_llm = self._engine.models.get("fast") or llm
        try:
            plan_chain = (
                self._engine.decompose_prompt
                | planner_llm.bind(temperature=float(getattr(settings, "QUERY_DECOMPOSITION_TEMPERATURE", 0.2) or 0.2))
                | StrOutputParser()
            )
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
        except Exception as exc:
            logger.debug("Ignoring agentic LLM decomposition failure: %s", exc)

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

    @staticmethod
    def _extract_math_expression(question: str) -> str | None:
        candidates = re.findall(r"[-+/*().\d\s]{5,}", question or "")
        for candidate in candidates:
            expr = " ".join(candidate.split()).strip(" =?")
            if not expr:
                continue
            if not any(op in expr for op in ("+", "-", "*", "/")):
                continue
            if not any(ch.isdigit() for ch in expr):
                continue
            return expr
        return None

    def _plan_tool_invocations(
        self,
        *,
        question: str,
        document_ids: list[UUID] | None,
        dataset_id: UUID | None,
        account_id: str | None,
    ) -> list[AgenticToolInvocation]:
        if not bool(getattr(settings, "RAG_AGENTIC_TOOLS_ENABLED", False)):
            return []

        question_norm = " ".join((question or "").split())
        question_lower = question_norm.casefold()
        invocations: list[AgenticToolInvocation] = []

        math_expr = self._extract_math_expression(question_norm)
        if math_expr:
            invocations.append(
                AgenticToolInvocation(
                    name="calculate",
                    arguments={"expression": math_expr},
                    rationale="math_expression_detected",
                )
            )

        if any(phrase in question_lower for phrase in ("current time", "what time", "current date", "today date")):
            invocations.append(
                AgenticToolInvocation(
                    name="get_current_time",
                    arguments={},
                    rationale="temporal_tool_detected",
                )
            )

        if (
            dataset_id
            and len(document_ids or []) == 1
            and any(
                phrase in question_lower
                for phrase in (
                    "full document",
                    "whole document",
                    "entire document",
                    "document content",
                    "read the document",
                )
            )
        ):
            page_match = re.search(r"\bpage\s+(\d+)\b", question_lower)
            args: dict[str, Any] = {
                "document_id": str(document_ids[0]),
                "dataset_id": str(dataset_id),
                "account_id": account_id,
            }
            if page_match:
                args["page"] = int(page_match.group(1))
            invocations.append(
                AgenticToolInvocation(
                    name="get_document_content",
                    arguments=args,
                    rationale="single_document_read_detected",
                )
            )

        deduped: list[AgenticToolInvocation] = []
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        for invocation in invocations:
            key = (
                invocation.name,
                tuple(sorted((str(k), str(v)) for k, v in invocation.arguments.items())),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(invocation)
        return deduped

    @staticmethod
    def _format_tool_context(tool_name: str, data: Any) -> str:
        if isinstance(data, dict):
            if tool_name == "calculate":
                if data.get("success"):
                    return f"[Tool: calculate]\nExpression: {data.get('expression')}\nResult: {data.get('result')}"
                return f"[Tool: calculate]\nError: {data.get('error')}"
            if tool_name == "get_current_time":
                return f"[Tool: get_current_time]\nCurrent datetime: {data.get('datetime') or data.get('date') or data}"
            if tool_name == "get_document_content":
                content = str(data.get("content") or "").strip()
                if not content:
                    return f"[Tool: get_document_content]\nError: {data.get('error') or 'No content returned'}"
                return f"[Tool: get_document_content]\n{content}"
        text = str(data or "").strip()
        if not text:
            return ""
        return f"[Tool: {tool_name}]\n{text}"

    @staticmethod
    def _build_base_state(
        stream_request: AgenticStreamRequest,
        *,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base_state_kwargs = {
            key: value for key, value in (stream_request.state_overrides or {}).items() if key in _RAG_STATE_BUILD_KEYS
        }
        base_state_kwargs.update(
            {
                "question": stream_request.question,
                "history": history,
                "document_ids": stream_request.document_ids,
                "dataset_ids": stream_request.dataset_ids,
                "tenant_id": stream_request.tenant_id,
                "account_id": stream_request.account_id,
                "dataset_id": stream_request.dataset_id,
                "top_k": stream_request.top_k,
                "score_threshold": stream_request.score_threshold,
                "retrieval_mode": stream_request.retrieval_mode,
                "retrieval_profile": stream_request.retrieval_profile,
                "structured_output": stream_request.structured_output,
                "structured_preset": stream_request.structured_preset,
                "prompt_template_id": stream_request.prompt_template_id,
                "prompt_template_key": stream_request.prompt_template_key,
                "prompt_ab_experiment_key": stream_request.prompt_ab_experiment_key,
                "ab_user_key": stream_request.ab_user_key,
                "db": stream_request.db,
            }
        )
        return build_rag_state(**base_state_kwargs)

    @staticmethod
    def _build_route_event(
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
                "route": "agentic",
                "reason": f"complexity {complexity_score:.1f} >= threshold {threshold}; {routing_reason}",
                "model_route": model_route,
                "prompt_template_id": base_state.get("prompt_template_id"),
                "prompt_template_key": base_state.get("prompt_template_key"),
                "prompt_ab_experiment_key": base_state.get("prompt_ab_experiment_key"),
                "prompt_ab_variant": base_state.get("prompt_ab_variant"),
            },
        }

    async def _stream_tool_phase(
        self,
        *,
        question: str,
        document_ids: list[UUID] | None,
        dataset_id: UUID | None,
        account_id: str | None,
        state: _AgenticRetrievalState,
    ) -> AsyncIterator[dict[str, Any]]:
        tool_invocations = self._plan_tool_invocations(
            question=question,
            document_ids=document_ids,
            dataset_id=dataset_id,
            account_id=account_id,
        )
        if not tool_invocations:
            return
        try:
            registry = get_agentic_tool_registry()
            for invocation in tool_invocations:
                yield {
                    "type": "agentic_step",
                    "data": {
                        "step": "tool_call",
                        "tool": invocation.name,
                        "rationale": invocation.rationale,
                    },
                }
                result = await registry.call_tool(invocation.name, invocation.arguments)
                success = bool(getattr(result, "success", False))
                data = getattr(result, "data", None)
                error = getattr(result, "error", None)
                metadata = dict(getattr(result, "metadata", None) or {})
                state.tool_metrics.append(
                    {
                        "name": invocation.name,
                        "success": success,
                        "backend": metadata.get("backend"),
                        "error": str(error)[:200] if error else None,
                    }
                )
                if success:
                    context_block = self._format_tool_context(invocation.name, data)
                    if context_block:
                        state.tool_context_blocks.append(context_block)
                yield {
                    "type": "agentic_step",
                    "data": {
                        "step": "tool_result",
                        "tool": invocation.name,
                        "success": success,
                        "error": str(error)[:200] if error else None,
                    },
                }
        except Exception:
            state.tool_metrics.append(
                {"name": "registry_init", "success": False, "backend": None, "error": "tool_registry_failed"}
            )

    async def _stream_retrieval_phase(
        self,
        *,
        question: str,
        plan_steps: list[AgenticPlanStep],
        max_rounds: int,
        base_state: dict[str, Any],
        request_db: Any,
        state: _AgenticRetrievalState,
    ) -> AsyncIterator[dict[str, Any]]:
        for round_idx, step in enumerate(plan_steps[:max_rounds], 1):
            retrieval_query = build_chained_query(step.query, state.prior_findings) or step.query
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
            result = await run_blocking_retrieval_call_with_managed_session(
                lambda worker_db: run_retrieval({**round_state, "db": worker_db}),
                request_db=request_db,
            )
            state.retrieval_elapsed_total += time.time() - round_started
            state.rounds_executed = round_idx
            state.final_result = result
            state.collected_docs = self._merge_docs(state.collected_docs, list(result.get("docs") or []))
            step_summary = summarize_chain_step(list(result.get("citations") or []))
            if step_summary:
                state.prior_findings.append(step_summary)
            if self._is_sufficient(result):
                break
            crag_phase = await self._maybe_run_crag(
                question=question,
                retrieval_query=retrieval_query,
                retrieval_result=result,
                state=state,
            )
            if crag_phase:
                crag_event, context_block = crag_phase
                yield crag_event
                state.tool_context_blocks.append(context_block)
                break

    async def _maybe_run_crag(
        self,
        *,
        question: str,
        retrieval_query: str,
        retrieval_result: dict[str, Any],
        state: _AgenticRetrievalState,
    ) -> tuple[dict[str, Any], str] | None:
        if not bool(getattr(settings, "RAG_CRAG_STREAMING_ENABLED", False)):
            return None
        crag_result = await run_crag_streaming(
            question=question,
            query_for_retrieval=retrieval_query,
            retrieval_result=retrieval_result,
        )
        context_block = str(crag_result.get("context_block") or "")
        if not bool(crag_result.get("used")) or not context_block.strip():
            return None
        state.crag_used = True
        state.crag_provider = str(crag_result.get("provider") or "").strip() or None
        state.crag_web_results = int(crag_result.get("web_result_count") or 0)
        return (
            {
                "type": "agentic_step",
                "data": {
                    "step": "web_search",
                    "provider": state.crag_provider,
                    "result_count": state.crag_web_results,
                },
            },
            context_block,
        )

    @staticmethod
    def _build_citations(
        *,
        question: str,
        retrieval_mode: str,
        retrieval_state: _AgenticRetrievalState,
    ) -> list[Any]:
        citations = build_citations_from_docs(
            retrieval_state.collected_docs,
            retrieval_elapsed_sec=float(retrieval_state.retrieval_elapsed_total or 0.0),
            retrieval_mode=str(
                (retrieval_state.final_result.get("metrics") or {}).get("retrieval_mode") or retrieval_mode
            ),
            query=question,
        )
        if citations:
            return citations
        return list(retrieval_state.final_result.get("citations") or [])

    async def _stream_generation_phase(
        self,
        *,
        base_state: dict[str, Any],
        history: list[dict[str, Any]],
        question: str,
        llm: Any,
        citations: list[Any],
        retrieval_state: _AgenticRetrievalState,
        structured_output: bool,
        state: _AgenticGenerationState,
    ) -> AsyncIterator[dict[str, Any]]:
        if not retrieval_state.collected_docs and not retrieval_state.tool_context_blocks:
            self._apply_abstain_generation(state)
            yield {"type": "token", "data": {"content": state.full_response}}
            state.answer_tokens = num_tokens_from_string(state.full_response)
            state.answer_chars = len(state.full_response)
            return

        yield {"type": "agentic_step", "data": {"step": "answering"}}
        prompt_template_content = base_state.get("prompt_template_content")
        prompt_template = (
            ChatPromptTemplate.from_template(str(prompt_template_content))
            if prompt_template_content
            else self._engine.prompt_template
        )
        history_text = _build_history_text(history)
        context = self._build_generation_context(
            docs=retrieval_state.collected_docs,
            question=question,
            tool_context_blocks=retrieval_state.tool_context_blocks,
        )
        generation_inputs = {
            "context": context,
            "history": history_text,
            "question": question,
            "format_instructions": str(base_state.get("format_instructions") or ""),
        }
        gen_start = time.time()
        chain = prompt_template | llm | StrOutputParser()
        async for token in chain.astream(generation_inputs):
            if not token:
                continue
            token_text = token if isinstance(token, str) else str(token)
            state.full_response += token_text
            yield {"type": "token", "data": {"content": token_text}}
        state.generation_elapsed = time.time() - gen_start
        state.answer_tokens = num_tokens_from_string(state.full_response)
        state.answer_chars = len(state.full_response)
        state.structured_data = self._parse_structured_data(
            full_response=state.full_response,
            structured_output=structured_output,
        )
        async for event in self._stream_review_phase(
            question=question,
            citations=citations,
            collected_docs=retrieval_state.collected_docs,
            generation_state=state,
        ):
            yield event

    @staticmethod
    def _apply_abstain_generation(state: _AgenticGenerationState) -> None:
        state.full_response = _UNABLE_TO_ANSWER_MESSAGE
        state.generation_elapsed = 0.0

    @staticmethod
    def _build_generation_context(
        *,
        docs: list[Document],
        question: str,
        tool_context_blocks: list[str],
    ) -> str:
        context = _build_context(docs, query=question)
        if not tool_context_blocks:
            return context
        tool_context = "\n\n".join(tool_context_blocks)
        if context and context != "No relevant reference materials found.":
            return f"{tool_context}\n\n[Retrieved Materials]\n{context}"
        return tool_context

    @staticmethod
    def _parse_structured_data(*, full_response: str, structured_output: bool) -> dict[str, Any] | None:
        if not structured_output:
            return None
        structured_data, _meta = parse_json_from_text(full_response, expected="object")
        return structured_data

    async def _stream_review_phase(
        self,
        *,
        question: str,
        citations: list[Any],
        collected_docs: list[Document],
        generation_state: _AgenticGenerationState,
    ) -> AsyncIterator[dict[str, Any]]:
        if not (
            bool(getattr(settings, "RAG_SELF_RAG_ENABLED", False))
            or bool(getattr(settings, "RAG_CRITIC_ENABLED", False))
        ):
            return
        evidence_text = "\n".join(
            [
                str(getattr(doc, "page_content", "") or "").strip()
                for doc in (collected_docs or [])
                if str(getattr(doc, "page_content", "") or "").strip()
            ]
        )
        generation_state.self_rag_reflection = run_self_rag_reflection(
            question=question,
            answer=generation_state.full_response,
            evidence_text=evidence_text,
            citations=citations,
        )
        yield {
            "type": "agentic_step",
            "data": {
                "step": "self_reflect",
                "verdict": generation_state.self_rag_reflection.get("verdict"),
                "need_retrieval": generation_state.self_rag_reflection.get("need_retrieval"),
            },
        }
        if not bool(getattr(settings, "RAG_CRITIC_ENABLED", False)):
            return
        generation_state.critic_review = run_critic_review(
            question=question,
            answer=generation_state.full_response,
            evidence_text=evidence_text,
            citations=citations,
        )
        yield {
            "type": "agentic_step",
            "data": {
                "step": "critic_review",
                "verdict": generation_state.critic_review.get("verdict"),
                "citation_missing": generation_state.critic_review.get("citation_missing"),
            },
        }

    @staticmethod
    def _build_metrics(
        *,
        t_start: float,
        retrieval_mode: str,
        complexity_score: float,
        threshold: float,
        model_route: str,
        plan_steps: list[AgenticPlanStep],
        max_rounds: int,
        retrieval_state: _AgenticRetrievalState,
        generation_state: _AgenticGenerationState,
    ) -> dict[str, Any]:
        critic_review = generation_state.critic_review or {}
        self_rag_reflection = generation_state.self_rag_reflection or {}
        return {
            "elapsed_sec": round(time.time() - t_start, 3),
            "retrieval_elapsed_sec": round(float(retrieval_state.retrieval_elapsed_total or 0.0), 3),
            "generation_elapsed_sec": round(float(generation_state.generation_elapsed or 0.0), 3),
            "retrieval_mode": str(
                (retrieval_state.final_result.get("metrics") or {}).get("retrieval_mode") or retrieval_mode
            ),
            "complexity_score": round(float(complexity_score), 3),
            "agentic_used": True,
            "agentic_rounds": int(retrieval_state.rounds_executed),
            "agentic_planned_steps": int(len(plan_steps)),
            "agentic_queries": [step.query for step in plan_steps[:max_rounds]],
            "agentic_route_reason": f"complexity {complexity_score:.1f} >= threshold {threshold}",
            "model_route": model_route,
            "abstain_triggered": bool(retrieval_state.final_result.get("abstain_triggered")),
            "abstain_reason": retrieval_state.final_result.get("abstain_reason"),
            "docs_returned": int(len(retrieval_state.collected_docs)),
            "agentic_tools_used": int(sum(1 for item in retrieval_state.tool_metrics if item.get("success"))),
            "agentic_tool_calls": retrieval_state.tool_metrics,
            "agentic_crag_used": bool(retrieval_state.crag_used),
            "agentic_crag_provider": retrieval_state.crag_provider,
            "agentic_crag_web_results": int(retrieval_state.crag_web_results),
            "agentic_self_rag_used": bool(generation_state.self_rag_reflection is not None),
            "agentic_self_rag_verdict": self_rag_reflection.get("verdict")
            if generation_state.self_rag_reflection
            else None,
            "agentic_self_rag_need_retrieval": (
                bool(self_rag_reflection.get("need_retrieval"))
                if generation_state.self_rag_reflection is not None
                else None
            ),
            "agentic_critic_used": bool(generation_state.critic_review is not None),
            "agentic_critic_verdict": critic_review.get("verdict") if generation_state.critic_review else None,
            "agentic_critic_citation_missing": (
                bool(critic_review.get("citation_missing")) if generation_state.critic_review is not None else None
            ),
            "agentic_critic_supported_claims": (
                int(critic_review.get("supported_claims") or 0) if generation_state.critic_review is not None else None
            ),
            "agentic_critic_total_claims": (
                int(critic_review.get("total_claims") or 0) if generation_state.critic_review is not None else None
            ),
            "agentic_critic_style_issue_count": (
                len(critic_review.get("style_issues") or []) if generation_state.critic_review is not None else None
            ),
            "agentic_critic_reason_codes": (
                list(critic_review.get("reason_codes") or []) if generation_state.critic_review is not None else []
            ),
        }

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
        account_id = stream_request.account_id
        dataset_id = stream_request.dataset_id
        retrieval_mode = stream_request.retrieval_mode
        structured_output = stream_request.structured_output
        complexity_score = self._engine._score_question_complexity(question, history)
        threshold = float(getattr(settings, "RAG_AGENTIC_COMPLEXITY_THRESHOLD", 250.0) or 250.0)
        llm, model_route, routing_reason = self._engine._select_llm(question, history)
        max_rounds = max(1, int(getattr(settings, "RAG_AGENTIC_MAX_RETRIEVE_ROUNDS", 3) or 3))
        plan_steps = await self._plan(question=question, llm=llm, max_steps=max_rounds)

        if bool(getattr(settings, "RAG_MULTI_AGENT_ENABLED", False)) and len(plan_steps) > 1:
            runner = get_multi_agent_runner(engine=self._engine)
            async for event in runner.stream(request=stream_request):
                yield event
            return

        base_state = self._build_base_state(stream_request, history=history)
        yield self._build_route_event(
            llm=llm,
            complexity_score=complexity_score,
            threshold=threshold,
            routing_reason=routing_reason,
            model_route=model_route,
            base_state=base_state,
        )
        yield {"type": "agentic_step", "data": {"step": "planning"}}

        retrieval_state = _AgenticRetrievalState(
            final_result={
                "docs": [],
                "citations": [],
                "metrics": {"retrieval_mode": str(base_state.get("retrieval_mode") or "")},
                "abstain_triggered": True,
                "abstain_reason": "no_rounds",
            }
        )
        async for event in self._stream_tool_phase(
            question=question,
            document_ids=document_ids,
            dataset_id=dataset_id,
            account_id=account_id,
            state=retrieval_state,
        ):
            yield event

        async for event in self._stream_retrieval_phase(
            question=question,
            plan_steps=plan_steps,
            max_rounds=max_rounds,
            base_state=base_state,
            request_db=stream_request.db,
            state=retrieval_state,
        ):
            yield event

        citations = self._build_citations(
            question=question,
            retrieval_mode=retrieval_mode,
            retrieval_state=retrieval_state,
        )
        yield {"type": "citations", "data": citations}

        generation_state = _AgenticGenerationState()
        async for event in self._stream_generation_phase(
            base_state=base_state,
            history=history,
            question=question,
            llm=llm,
            citations=citations,
            retrieval_state=retrieval_state,
            structured_output=structured_output,
            state=generation_state,
        ):
            yield event

        metrics = self._build_metrics(
            t_start=t_start,
            retrieval_mode=retrieval_mode,
            complexity_score=complexity_score,
            threshold=threshold,
            model_route=model_route,
            plan_steps=plan_steps,
            max_rounds=max_rounds,
            retrieval_state=retrieval_state,
            generation_state=generation_state,
        )

        yield {
            "type": "done",
            "data": {
                "conversation_id": str(conversation_id) if conversation_id else None,
                "total_tokens": int(generation_state.answer_tokens),
                "total_chars": int(generation_state.answer_chars),
                "citations_count": len(citations),
                "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
                "route": "agentic",
                "retrieval_mode": metrics["retrieval_mode"],
                "vector_backend": settings.VECTOR_BACKEND,
                "metrics": metrics,
                "structured": bool(generation_state.structured_data),
                "structured_data": generation_state.structured_data,
            },
        }


_AGENTIC_RUNNER: AgenticRAGRunner | None = None
_AGENTIC_LOCK = threading.Lock()


def get_agentic_runner(*, engine: "RAGEngine | None" = None) -> AgenticRAGRunner:
    global _AGENTIC_RUNNER
    if engine is not None:
        return AgenticRAGRunner(engine=engine)
    if _AGENTIC_RUNNER is None:
        with _AGENTIC_LOCK:
            if _AGENTIC_RUNNER is None:
                from app.rag.engine import get_rag_engine

                _AGENTIC_RUNNER = AgenticRAGRunner(engine=get_rag_engine())
    return _AGENTIC_RUNNER


def reset_agentic_runner() -> None:
    global _AGENTIC_RUNNER
    with _AGENTIC_LOCK:
        _AGENTIC_RUNNER = None


__all__ = [
    "AgenticPlanStep",
    "AgenticToolInvocation",
    "AgenticRAGRunner",
    "get_agentic_runner",
    "get_agentic_tool_registry",
    "get_multi_agent_runner",
    "reset_agentic_runner",
]
