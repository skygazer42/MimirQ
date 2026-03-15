"""
RAG Agent (LangChain-only).

Historically this project used a LangGraph-based agent. For a clean LangChain
1.x setup, the default chat flow now uses `RAGEngine` which performs hybrid
retrieval and prompt-based answering.

This module is kept for backwards compatibility; it simply forwards calls to
`RAGEngine`.
"""


import threading
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from app.rag.engine import RAGEngine, get_rag_engine


class RAGAgent:
    """Compatibility wrapper around `RAGEngine`."""

    def __init__(self) -> None:
        self._engine: RAGEngine = get_rag_engine()

    async def stream_chat(
        self,
        question: str,
        conversation_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        top_k: int = 5,
        tenant_id: UUID | None = None,
        account_id: str | None = None,
        dataset_id: UUID | None = None,
        history: list[dict[str, str]] | None = None,
        score_threshold: float = 0.7,
    ) -> AsyncGenerator[dict[str, Any], None]:
        async for event in self._engine.stream_chat(
            question=question,
            history=history,
            conversation_id=conversation_id,
            document_ids=document_ids,
            top_k=top_k,
            score_threshold=score_threshold,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
        ):
            yield event


_rag_agent_instance: RAGAgent | None = None
_rag_agent_lock: threading.Lock = threading.Lock()


def get_rag_agent() -> RAGAgent:
    """Lazily initialize the RAG agent (thread-safe)."""
    global _rag_agent_instance
    if _rag_agent_instance is None:
        with _rag_agent_lock:
            if _rag_agent_instance is None:
                _rag_agent_instance = RAGAgent()
    return _rag_agent_instance
