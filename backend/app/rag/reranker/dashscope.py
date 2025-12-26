"""
阿里云 DashScope Reranker
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.rag.reranker.base import BaseReranker


class DashScopeReranker(BaseReranker):
    """阿里云 DashScope Reranker"""

    def _build_payload(
        self,
        query: str,
        documents: List[str],
        max_length: int,
    ) -> Dict[str, Any]:
        params = {"top_n": len(documents), "return_documents": False}
        instruct = self.parameters.get("instruct")
        if instruct:
            params["instruct"] = instruct
        return {
            "model": self.model,
            "input": {"query": query, "documents": documents},
            "parameters": params,
        }

    def _extract_results(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(result.get("output", {}).get("results", []))
