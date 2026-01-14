from typing import List, Optional
from uuid import UUID

from pydantic import Field

from app.rag.kg.schemas import KGBaseModel


class ExtractConfig(KGBaseModel):
    """Configuration for event extraction from document chunks."""

    chunk_ids: List[UUID] = Field(default_factory=list, description="DocumentChunk IDs to process")
    tenant_id: Optional[UUID] = None
    max_concurrency: int = 3
    source_config_id: Optional[str] = None
    replace_existing: bool = Field(default=True, description="Replace previously extracted events for these chunks")
    prune_orphan_entities: bool = Field(default=True, description="Prune entities with no remaining event links")
    # Optional PromptTemplate selectors (tenant-scoped).
    prompt_template_id: Optional[UUID] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None
    ab_user_key: Optional[str] = None


# Legacy compatibility alias
ExtractBaseConfig = ExtractConfig
