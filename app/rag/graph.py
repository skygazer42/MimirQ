"""
Backward-compatible import path for the LangGraph pipeline.

The canonical implementation lives in `app.rag.pipelines.langgraph`.
"""

from app.rag.pipelines.langgraph import build_rag_graph, run_rag_graph

__all__ = ["build_rag_graph", "run_rag_graph"]

