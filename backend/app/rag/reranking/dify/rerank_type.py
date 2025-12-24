"""
Rerank mode enumeration.
Integrated from third_party/dify/rerank/rerank_type.py
"""
from enum import StrEnum


class RerankMode(StrEnum):
    """Rerank mode enumeration."""
    RERANKING_MODEL = "reranking_model"
    WEIGHTED_SCORE = "weighted_score"
