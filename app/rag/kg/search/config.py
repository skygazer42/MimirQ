from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import Field

from app.rag.kg.schemas import KGBaseModel


class RerankStrategy(str, Enum):
    PAGERANK = "pagerank"
    RRF = "rrf"

    def __str__(self) -> str:
        return self.value


class ReturnType(str, Enum):
    EVENT = "event"

    def __str__(self) -> str:
        return self.value


class RecallConfig(KGBaseModel):
    vector_top_k: int = Field(default=15, ge=1, le=200)
    vector_candidates: int = Field(default=30, ge=1, le=500)
    entity_similarity_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    event_similarity_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_entities: int = Field(default=30, ge=1, le=200)
    max_events: int = Field(default=80, ge=1, le=500)
    entity_weight_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    final_entity_count: int = Field(default=20, ge=1, le=200)


class ExpandConfig(KGBaseModel):
    enabled: bool = True
    max_hops: int = Field(default=2, ge=1, le=5)
    entities_per_hop: int = Field(default=10, ge=1, le=50)
    weight_change_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    event_similarity_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    min_events_per_hop: int = Field(default=3, ge=1, le=100)
    max_events_per_hop: int = Field(default=60, ge=1, le=200)


class RerankConfig(KGBaseModel):
    strategy: RerankStrategy = RerankStrategy.PAGERANK
    score_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    max_results: int = Field(default=10, ge=1, le=100)
    max_key_recall_results: int = Field(default=40, ge=1, le=500)
    max_query_recall_results: int = Field(default=40, ge=1, le=500)
    pagerank_damping_factor: float = Field(default=0.85, ge=0.0, le=1.0)
    pagerank_max_iterations: int = Field(default=50, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=500)


class SearchConfig(KGBaseModel):
    query: str
    tenant_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None
    return_type: ReturnType = ReturnType.EVENT
    recall: RecallConfig = RecallConfig()
    expand: ExpandConfig = ExpandConfig()
    rerank: RerankConfig = RerankConfig()
    original_query: Optional[str] = None

    def get_source_config_ids(self) -> List[str]:
        return []


# Legacy compatibility alias
SearchBaseConfig = SearchConfig
