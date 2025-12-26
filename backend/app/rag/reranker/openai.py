"""
OpenAI 风格 Reranker

支持 OpenAI、SiliconFlow、VLLM 等兼容 API。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.rag.reranker.base import BaseReranker


class OpenAIReranker(BaseReranker):
    """OpenAI 风格 API Reranker"""

    def _build_payload(
        self,
        query: str,
        documents: List[str],
        max_length: int,
    ) -> Dict[str, Any]:
        return {
            "model": self.model,
            "query": query,
            "documents": documents,
            "max_chunks_per_doc": max_length,
        }

    def _extract_results(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(result.get("results", []))
