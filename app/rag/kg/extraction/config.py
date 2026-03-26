from uuid import UUID

from pydantic import Field

from app.rag.kg.schemas import KGBaseModel


class ExtractConfig(KGBaseModel):
    """Configuration for event extraction from document chunks."""

    chunk_ids: list[UUID] = Field(default_factory=list, description="DocumentChunk IDs to process")
    tenant_id: UUID | None = None
    max_concurrency: int = 3
    source_config_id: str | None = None
    replace_existing: bool = Field(default=True, description="Replace previously extracted events for these chunks")
    prune_orphan_entities: bool = Field(default=True, description="Prune entities with no remaining event links")
    # Optional toggles (default to settings when None).
    extract_relations: bool | None = Field(default=None, description="Extract entity relations (triples) if enabled")
    extract_skills: bool | None = Field(default=None, description="Extract Skill/SOP entities if enabled")
    # Optional PromptTemplate selectors (tenant-scoped).
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    ab_user_key: str | None = None
    extraction_backend: str | None = Field(default=None, description="Extraction backend override: llm|gliner|hybrid")


# Legacy compatibility alias
ExtractBaseConfig = ExtractConfig
