"""
OpenAI-style reranker.

Supports OpenAI, SiliconFlow, VLLM, and compatible APIs.
"""
from __future__ import annotations

from typing import Any

from app.rag.reranker.base import APIReranker


class OpenAIReranker(APIReranker):
    """OpenAI-style API reranker."""

    def _build_payload(
        self,
        query: str,
        documents: list[str],
        max_length: int,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "query": query,
            "documents": documents,
            "max_chunks_per_doc": max_length,
        }

    def _extract_results(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        return list(result.get("results", []))
