"""
Agents module for LangGraph-based AI agents.

Provides:
- Prebuilt agents: create_rag_agent, RAGAgent, ToolNode
- Integration with LangGraph's official prebuilt components
"""


import langchain

if not hasattr(langchain, "debug"):
    langchain.debug = False
if not hasattr(langchain, "verbose"):
    langchain.verbose = False
if not hasattr(langchain, "llm_cache"):
    langchain.llm_cache = None

from app.rag.agents.multi_agent import MultiAgentPlanStep, MultiAgentRAGRunner, get_multi_agent_runner
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
from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner, get_agentic_runner

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
