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


# Alias for compatibility with upstream SAG
ExtractBaseConfig = ExtractConfig
