"""
Base rerank runner interface.
Integrated from third_party/dify/rerank/rerank_base.py
"""
from abc import ABC, abstractmethod

from app.models.dify import Document


class BaseRerankRunner(ABC):
    """Base class for reranking runners."""

    @abstractmethod
    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        """Run rerank model.

        Args:
            query: Search query
            documents: Documents for reranking
            score_threshold: Score threshold for filtering
            top_n: Maximum number of results to return
            user: Unique user id if needed

        Returns:
            List of reranked documents
        """
        raise NotImplementedError
