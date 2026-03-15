from enum import Enum
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
    tenant_id: UUID | None = None
    dataset_id: UUID | None = None
    # Dataset-scoped searches require account_id to enforce document-level ACL (security trimming).
    account_id: str | None = None
    document_ids: list[UUID] | None = None
    return_type: ReturnType = ReturnType.EVENT
    # Per-call overrides (thread-safe) for diagnostics/experimentation.
    # - None means "use settings + existing default behavior".
    # - True/False forces the behavior for this call.
    relation_expansion_enabled: bool | None = None
    # Vector recall (embeddings + Milvus) override. Useful for diagnostics ablations.
    vector_recall_enabled: bool | None = None
    # Graph embeddings (node2vec-like) recall override. Useful for diagnostics ablations.
    graph_embeddings_enabled: bool | None = None
    # Query-mode routing: auto | local | global | drift.
    query_mode: str = "auto"
    query_mode_reason_codes: list[str] = []
    query_mode_confidence: str | None = None
    # When false, filter Skill-like entities from recall/expand (useful for ablations).
    include_skill_entities: bool = True
    recall: RecallConfig = RecallConfig()
    expand: ExpandConfig = ExpandConfig()
    rerank: RerankConfig = RerankConfig()
    original_query: str | None = None

    def get_source_config_ids(self) -> list[str]:
        return []


# Legacy compatibility alias
SearchBaseConfig = SearchConfig
