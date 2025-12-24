"""
Weight entity models for reranking.
Integrated from third_party/dify/rerank/entity/weight.py
"""
from pydantic import BaseModel


class VectorSetting(BaseModel):
    """Vector weight settings."""
    vector_weight: float
    embedding_provider_name: str
    embedding_model_name: str


class KeywordSetting(BaseModel):
    """Keyword weight settings."""
    keyword_weight: float


class Weights(BaseModel):
    """Model for weighted rerank combining vector and keyword scores."""
    vector_setting: VectorSetting
    keyword_setting: KeywordSetting
