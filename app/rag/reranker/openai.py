"""
OpenAI-style reranker.

Supports OpenAI, SiliconFlow, VLLM, and compatible APIs.
"""

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
        payload: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": documents,
        }
        if self.parameters.get("include_max_chunks_per_doc"):
            payload["max_chunks_per_doc"] = max_length
        return payload

    def _extract_results(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        return list(result.get("results", []))
