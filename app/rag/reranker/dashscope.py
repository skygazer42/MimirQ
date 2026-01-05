"""
阿里云 DashScope Reranker

支持阿里云 DashScope 的 reranker API。
"""
from __future__ import annotations

from typing import Any

from app.rag.reranker.base import APIReranker


class DashScopeReranker(APIReranker):
    """阿里云 DashScope Reranker"""

    def _build_payload(
        self,
        query: str,
        documents: list[str],
        max_length: int,
    ) -> dict[str, Any]:
        params = {"top_n": len(documents), "return_documents": False}
        instruct = self.parameters.get("instruct")
        if instruct:
            params["instruct"] = instruct
        return {
            "model": self.model,
            "input": {"query": query, "documents": documents},
            "parameters": params,
        }

    def _extract_results(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        return list(result.get("output", {}).get("results", []))
