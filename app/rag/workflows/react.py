"""
ReAct Workflow Pattern.

Reasoning and Acting loop for complex queries.
Alternates between thinking about the problem and taking actions.

Pattern: Think -> Act -> Observe -> Think -> ... -> Answer
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.middleware import ToolMiddlewareChain
from app.rag.tools.hierarchical_retrieval_tools import chunk_read, keyword_search, semantic_search
from app.rag.tools.retrieval_config_tool import configure_retrieval
from app.rag.tools.web_search import web_search
from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowResult,
)

logger = get_logger("rag.workflows.react")


class Tool:
    """A tool that can be invoked by the ReAct agent."""

    def __init__(
        self,
        name: str,
        func: Callable[[str], Awaitable[str]],
        description: str = "",
    ):
        self.name = name
        self.func = func
        self.description = description

    async def invoke(self, input_text: str) -> str:
        """Invoke the tool."""
        return await self.func(input_text)


class ReActWorkflow(BaseWorkflow):
    """
    ReAct workflow implements reasoning and acting loop.

    The agent reasons about the problem, decides on actions,
    observes results, and continues until reaching an answer.

    Usage:
        workflow = ReActWorkflow(llm=my_llm)
        workflow.add_tool("search", search_func, "Search documents")
        workflow.add_tool("calculate", calc_func, "Do calculations")
        result = await workflow.run({"question": "..."})
    """

    def __init__(
        self,
        llm: Any | None = None,
        max_steps: int = 10,
        **kwargs,
    ):
        """
        Initialize the ReAct workflow.

        Args:
            llm: Language model for reasoning
            max_steps: Maximum reasoning steps
            **kwargs: Additional configuration
        """
        super().__init__(**kwargs)
        self._llm = llm
        self._tools: dict[str, Tool] = {}
        self.max_steps = max_steps

    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.REACT

    def add_tool(
        self,
        name: str,
        func: Callable[[str], Awaitable[str]],
        description: str = "",
    ) -> "ReActWorkflow":
        """
        Add a tool for the agent to use.

        Args:
            name: Tool name
            func: Tool function (input -> output)
            description: Tool description

        Returns:
            Self for chaining
        """
        self._tools[name] = Tool(name, func, description)
        return self

    def set_llm(self, llm: Any) -> "ReActWorkflow":
        """Set the language model."""
        self._llm = llm
        return self

    def register_hierarchical_retrieval_tools(
        self,
        *,
        dataset_id: str,
        account_id: str | None = None,
    ) -> "ReActWorkflow":
        async def _keyword(input_text: str) -> str:
            result = await keyword_search(str(input_text or ""), dataset_id=dataset_id)
            return str(result)

        async def _semantic(input_text: str) -> str:
            result = await semantic_search(str(input_text or ""), dataset_id=dataset_id)
            return str(result)

        async def _chunk(input_text: str) -> str:
            result = await chunk_read(document_id=str(input_text or ""), dataset_id=dataset_id, account_id=account_id)
            return str(result)

        self.add_tool("keyword_search", _keyword, "Keyword-first retrieval for exact terms, IDs, and entity names.")
        self.add_tool(
            "semantic_search", _semantic, "Semantic retrieval for natural language questions over the dataset."
        )
        self.add_tool("chunk_read", _chunk, "Read the full document/chunk content for a selected document id.")
        return self

    def register_retrieval_config_tool(self) -> "ReActWorkflow":
        async def _configure(input_text: str) -> str:
            await asyncio.sleep(0)
            payload: dict[str, Any] = {}
            raw = str(input_text or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        payload = dict(parsed)
                except Exception:
                    payload = {}
                    for part in raw.replace(",", " ").split():
                        if "=" not in part:
                            continue
                        key, value = part.split("=", 1)
                        payload[str(key).strip()] = str(value).strip()

            result = configure_retrieval(
                top_k=payload.get("top_k", 20),
                reranker_top_n=payload.get("reranker_top_n", payload.get("rerank_n", 20)),
                retrieval_profile=payload.get("retrieval_profile"),
                retrieval_mode=payload.get("retrieval_mode"),
                score_threshold=payload.get("score_threshold", 0.0),
            )
            return str(result)

        self.add_tool(
            "configure_retrieval",
            _configure,
            "Adjust retrieval knobs such as top_k, reranker_top_n, retrieval_profile, and retrieval_mode.",
        )
        return self

    def register_web_search_tool(
        self,
        *,
        provider_order: list[str] | tuple[str, ...] | None = None,
        max_results: int = 5,
        site_filter: list[str] | None = None,
        freshness: str | None = None,
        lang: str | None = None,
        region: str | None = None,
    ) -> "ReActWorkflow":
        async def _web_search(input_text: str) -> str:
            result = await web_search(
                str(input_text or ""),
                provider_order=list(provider_order) if provider_order is not None else None,
                max_results=max_results,
                site_filter=site_filter,
                freshness=freshness,
                lang=lang,
                region=region,
            )
            return str(result)

        self.add_tool(
            "web_search",
            _web_search,
            "Search the public web with provider fallback for recent or out-of-corpus information.",
        )
        return self

    def _get_tools_prompt(self) -> str:
        """Generate tools description for prompt."""
        if not self._tools:
            return "No tools available."

        lines = ["Available tools:"]
        for name, tool in self._tools.items():
            lines.append(f"- {name}: {tool.description}")
        return "\n".join(lines)

    async def _reason(self, state: dict[str, Any]) -> dict[str, str]:
        """
        Generate next thought and action.

        Returns:
            Dict with 'thought', 'action', and 'action_input' keys
        """
        if self._llm is None:
            raise ValueError("LLM not configured")

        question = self.get_question(state)
        trace = state.get("reasoning_trace", [])
        tools_prompt = self._get_tools_prompt()

        history_text = "\n".join(trace) if trace else "None yet."

        prompt = f"""You are a reasoning agent. Your goal is to answer the question by thinking \
step by step and using tools when needed.

{tools_prompt}

Question: {question}

Previous reasoning steps:
{history_text}

Based on the above, provide your next step. You must respond in one of these formats:

1. If you need to use a tool:
Thought: [your reasoning about what to do next]
Action: [tool name]
Action Input: [input to the tool]

2. If you have the final answer:
Thought: [your final reasoning]
Answer: [your final answer to the question]

Your response:"""

        response = await self._llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Parse response
        result = {"thought": "", "action": "", "action_input": "", "answer": ""}

        lines = content.strip().split("\n")
        current_key = None

        for line in lines:
            line = line.strip()
            if line.startswith("Thought:"):
                current_key = "thought"
                result["thought"] = line[8:].strip()
            elif line.startswith("Action:"):
                current_key = "action"
                result["action"] = line[7:].strip()
            elif line.startswith("Action Input:"):
                current_key = "action_input"
                result["action_input"] = line[13:].strip()
            elif line.startswith("Answer:"):
                current_key = "answer"
                result["answer"] = line[7:].strip()
            elif current_key:
                result[current_key] += " " + line

        return result

    async def _act(self, workflow_state: dict[str, Any], action: str, action_input: str) -> str:
        """Execute an action using a tool (with tool-call middlewares)."""
        chain = ToolMiddlewareChain()
        tool_state: dict[str, Any] = {
            "tool_name": action,
            "arguments": {"input_text": action_input},
            "result": None,
            "error": None,
            "success": None,
            "metadata": {
                "workflow": self.name,
                "mode": self.mode.value,
            },
        }
        tool_state = chain.run_before(tool_state)

        async def _execute(state: dict[str, Any]) -> dict[str, Any]:
            name = str(state.get("tool_name") or "")
            args = state.get("arguments") or {}
            input_text = str(args.get("input_text") or "")

            target = self._tools.get(name)
            if target is None:
                state["success"] = False
                state["error"] = f"Tool '{name}' not found"
                return state

            try:
                state["result"] = await target.invoke(input_text)
                state["success"] = True
                return state
            except Exception as exc:  # noqa: BLE001
                state["success"] = False
                state["error"] = str(exc)[:500]
                return state

        wrapped = chain.wrap_call(_execute)
        result = wrapped(tool_state)
        tool_state = await result if asyncio.iscoroutine(result) else result
        tool_state = chain.run_after(tool_state)

        workflow_state.setdefault("tool_calls", []).append(
            {
                "tool_name": tool_state.get("tool_name"),
                "arguments": {
                    "input_text_preview": str((tool_state.get("arguments") or {}).get("input_text") or "")[:500]
                },
                "success": tool_state.get("success"),
                "error": tool_state.get("error"),
                "metadata": tool_state.get("metadata"),
            }
        )

        if not bool(tool_state.get("success")):
            return f"Error: {tool_state.get('error') or 'Tool call failed'}"

        return str(tool_state.get("result") or "")

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        """
        Execute the ReAct workflow.

        Args:
            state: Initial state

        Returns:
            WorkflowResult with final state
        """
        if not self.validate_state(state):
            return self.create_result(
                state,
                success=False,
                error="Invalid state: missing question/query",
            )

        if self._llm is None:
            return self.create_result(
                state,
                success=False,
                error="LLM not configured",
            )

        current_state = dict(state)
        current_state["reasoning_trace"] = []
        execution_path: list[str] = []
        iterations = 0

        for step in range(self.max_steps):
            iterations = step + 1

            # Reason
            try:
                reasoning = await self._reason(current_state)
            except Exception as e:
                logger.exception("Reasoning failed: %s", e)
                return self.create_result(
                    current_state,
                    success=False,
                    error=f"Reasoning failed: {e}",
                    execution_path=execution_path,
                    iterations=iterations,
                )

            thought = reasoning.get("thought", "")
            action = reasoning.get("action", "")
            action_input = reasoning.get("action_input", "")
            answer = reasoning.get("answer", "")

            # Add thought to trace
            if thought:
                current_state["reasoning_trace"].append(f"Thought: {thought}")
                execution_path.append(f"think:{step}")

            # Check if we have a final answer
            if answer:
                current_state["answer"] = answer
                current_state["reasoning_trace"].append(f"Answer: {answer}")
                execution_path.append("answer")

                return self.create_result(
                    current_state,
                    success=True,
                    execution_path=execution_path,
                    iterations=iterations,
                    metadata={"reasoning_steps": len(current_state["reasoning_trace"])},
                )

            # Execute action
            if action:
                observation = await self._act(current_state, action, action_input)
                current_state["reasoning_trace"].append(f"Action: {action}")
                current_state["reasoning_trace"].append(f"Action Input: {action_input}")
                current_state["reasoning_trace"].append(f"Observation: {observation}")
                execution_path.append(f"act:{action}")

        # Max steps reached
        current_state["answer"] = "I could not find a complete answer within the allowed steps."
        return self.create_result(
            current_state,
            success=False,
            error="Max reasoning steps reached",
            execution_path=execution_path,
            iterations=iterations,
        )


def create_search_tool(
    search_func: Callable[[str], Awaitable[list[dict[str, Any]]]],
) -> Tool:
    """Create a search tool wrapper."""

    async def search_wrapper(query: str) -> str:
        results = await search_func(query)
        if not results:
            return "No results found."

        output_parts = []
        for i, result in enumerate(results[:3], 1):
            content = result.get("content", "")[:500]
            source = result.get("metadata", {}).get("source", "Unknown")
            output_parts.append(f"[{i}] {source}: {content}")

        return "\n".join(output_parts)

    return Tool("search", search_wrapper, "Search documents for relevant information")
