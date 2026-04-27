"""
Agents module for LangGraph-based AI agents.

Provides:
- Prebuilt agents: create_rag_agent, RAGAgent, ToolNode
- Integration with LangGraph's official prebuilt components
"""

from __future__ import annotations

import logging

import langchain

if not hasattr(langchain, "debug"):
    langchain.debug = False
if not hasattr(langchain, "verbose"):
    langchain.verbose = False
if not hasattr(langchain, "llm_cache"):
    langchain.llm_cache = None

from app.rag.agents.multi_agent import MultiAgentPlanStep, MultiAgentRAGRunner, get_multi_agent_runner
from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner, get_agentic_runner

logger = logging.getLogger(__name__)

_PREBUILT_IMPORT_ERROR: Exception | None = None

try:
    from app.rag.agents.prebuilt import (
        RAGAgent,
        RAGAgentConfig,
        ToolNode,
        create_rag_agent,
        create_rag_tool_node,
        create_retriever_tool,
        create_search_tool,
        tools_condition,
    )
except Exception as exc:  # noqa: BLE001
    _PREBUILT_IMPORT_ERROR = exc
    logger.warning("LangGraph prebuilt agents unavailable: %s", str(exc)[:200])
    RAGAgent = None  # type: ignore[assignment]
    RAGAgentConfig = None  # type: ignore[assignment]
    ToolNode = None  # type: ignore[assignment]

    def _raise_prebuilt_unavailable(*_args, **_kwargs):  # noqa: ANN202, ANN001
        raise RuntimeError(
            "LangGraph prebuilt agent integration is unavailable in this environment"
        ) from _PREBUILT_IMPORT_ERROR

    create_rag_agent = _raise_prebuilt_unavailable  # type: ignore[assignment]
    create_rag_tool_node = _raise_prebuilt_unavailable  # type: ignore[assignment]
    create_retriever_tool = _raise_prebuilt_unavailable  # type: ignore[assignment]
    create_search_tool = _raise_prebuilt_unavailable  # type: ignore[assignment]
    tools_condition = _raise_prebuilt_unavailable  # type: ignore[assignment]

__all__ = [
    "AgenticPlanStep",
    "AgenticRAGRunner",
    "get_agentic_runner",
    "MultiAgentPlanStep",
    "MultiAgentRAGRunner",
    "get_multi_agent_runner",
    "create_rag_agent",
    "create_rag_tool_node",
    "create_retriever_tool",
    "create_search_tool",
    "RAGAgent",
    "RAGAgentConfig",
    "ToolNode",
    "tools_condition",
]
