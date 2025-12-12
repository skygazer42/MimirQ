"""
RAG Agent (LangChain-only).

Historically this project used a LangGraph-based agent. For a clean LangChain
1.x setup, the default chat flow now uses `RAGEngine` which performs hybrid
retrieval and prompt-based answering.

This module is kept for backwards compatibility; it simply forwards calls to
`RAGEngine`.
"""

from __future__ import annotations

from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID

from app.services.rag_engine import get_rag_engine, RAGEngine


class RAGAgent:
    """Compatibility wrapper around `RAGEngine`."""

    def __init__(self):
        self._engine: RAGEngine = get_rag_engine()

    async def stream_chat(
        self,
        question: str,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
        top_k: int = 5,
        tenant_id: Optional[UUID] = None,
        history: Optional[List[Dict[str, str]]] = None,
        score_threshold: float = 0.7,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async for event in self._engine.stream_chat(
            question=question,
            history=history,
            conversation_id=conversation_id,
            document_ids=document_ids,
            top_k=top_k,
            score_threshold=score_threshold,
            tenant_id=tenant_id,
        ):
            yield event


_rag_agent_instance: Optional[RAGAgent] = None


def get_rag_agent() -> RAGAgent:
    """Lazily initialize the RAG agent."""
    global _rag_agent_instance
    if _rag_agent_instance is None:
        _rag_agent_instance = RAGAgent()
    return _rag_agent_instance

