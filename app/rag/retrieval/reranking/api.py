"""Wire formats for OpenAI-compatible and DashScope reranker APIs."""

from typing import Any

from app.rag.retrieval.reranking.base import APIReranker


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


class DashScopeReranker(APIReranker):
    """Alibaba Cloud DashScope reranker."""

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
