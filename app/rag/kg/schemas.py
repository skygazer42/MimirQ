from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KGBaseModel(BaseModel):
    """BaseModel with orm_mode enabled for compatibility."""

    model_config = ConfigDict(from_attributes=True)


class KGExtractResponse(BaseModel):
    """Response after triggering KG extraction for a document."""

    document_id: UUID
    chunk_count: int
    event_count: int
    message: str = "KG extraction completed"


class KGSearchRequest(BaseModel):
    """KG search request."""

    query: str = Field(..., min_length=1, max_length=2048, description="Natural language query")
    tenant_id: UUID | None = None
    dataset_id: UUID | None = None
    # Note: document_ids limit is enforced server-side via settings.KG_API_MAX_DOCUMENT_IDS.
    document_ids: list[UUID] | None = Field(default=None)


class KGSearchResponse(BaseModel):
    """KG search raw result passthrough."""

    result: dict[str, Any]
    query: str


class KGGraphNode(BaseModel):
    """Graph node for frontend visualization."""

    id: str
    label: str
    group: int = 0
    val: int = 1
    meta: dict[str, Any] = Field(default_factory=dict)


class KGGraphLink(BaseModel):
    """Graph link for frontend visualization."""

    source: str
    target: str
    label: str = ""
    weight: float = 1.0
    meta: dict[str, Any] = Field(default_factory=dict)


class KGGraphResponse(BaseModel):
    """KG graph response."""

    nodes: list[KGGraphNode]
    links: list[KGGraphLink]
    stats: dict[str, Any] = Field(default_factory=dict)


class KGEntityItem(KGBaseModel):
    """Entity details for API responses."""

    id: UUID
    name: str
    type: str
    normalized_name: str
    description: str | None = None
    extra_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("extra_data", mode="before")
    @classmethod
    def _coerce_extra_data(cls, v: Any) -> dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGEventItem(KGBaseModel):
    """Event details for API responses."""

    id: UUID
    title: str
    summary: str
    content: str
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    references: dict[str, Any] = Field(default_factory=dict)
    extra_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("references", "extra_data", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, v: Any) -> dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGEventEntityItem(KGBaseModel):
    """Event-entity relation details."""

    entity: KGEntityItem
    weight: float = 1.0
    role: str | None = None
    extra_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra_data", mode="before")
    @classmethod
    def _coerce_extra_data(cls, v: Any) -> dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGEventDetailResponse(BaseModel):
    event: KGEventItem
    entities: list[KGEventEntityItem] = Field(default_factory=list)


class KGEntityNeighbor(BaseModel):
    entity_id: UUID
    name: str
    type: str
    count: int


class KGEntityDetailResponse(BaseModel):
    entity: KGEntityItem
    events: list[KGEventItem] = Field(default_factory=list)
    neighbors: list[KGEntityNeighbor] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class KGEntityTypeCount(BaseModel):
    type: str
    count: int


class KGStatsResponse(BaseModel):
    events: int
    entities: int
    links: int
    entity_types: list[KGEntityTypeCount] = Field(default_factory=list)
    updated_at: datetime | None = None


class KGDeleteResponse(BaseModel):
    document_id: UUID
    events_deleted: int = 0
    entities_pruned: int = 0


class KGManualEntityInput(BaseModel):
    """Curated external KG entity row for manual import."""

    key: str | None = Field(default=None, max_length=255, description="Stable external id within this import")
    name: str = Field(..., min_length=1, max_length=4000)
    type: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    extra_data: dict[str, Any] = Field(default_factory=dict)


class KGManualEntityRef(BaseModel):
    """Relation endpoint reference. Prefer key; name/type allows inline entities."""

    key: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=4000)
    type: str | None = Field(default=None, max_length=100)


class KGManualRelationInput(BaseModel):
    """Curated external KG relation row for manual import."""

    subject: str | KGManualEntityRef
    predicate: str = Field(..., min_length=1, max_length=200)
    object: str | KGManualEntityRef
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: str | None = Field(default=None, max_length=20000)
    source: str | None = Field(default=None, max_length=1000)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    references: dict[str, Any] = Field(default_factory=dict)
    extra_data: dict[str, Any] = Field(default_factory=dict)


class KGManualImportRequest(BaseModel):
    """Manual KG import payload.

    The payload is intentionally domain-neutral. Business-specific extraction
    should happen outside MimirQ; this endpoint only imports governed graph rows.
    """

    name: str = Field(default="手动知识图谱导入", min_length=1, max_length=255)
    import_id: str | None = Field(default=None, max_length=120)
    dataset_id: UUID | None = None
    dataset_name: str | None = Field(default=None, max_length=255)
    pipeline_hash: str | None = Field(default=None, max_length=200)
    replace_existing: bool = Field(
        default=False, description="Replace an existing manual import with the same import_id"
    )
    upsert_entities: bool = Field(default=True, description="Reuse existing same tenant/type/normalized-name entities")
    allow_label_truncation: bool = Field(default=True, description="Compact labels longer than KG schema limits")
    index_vectors: bool = Field(
        default=True, description="Embed and index imported KG events/entities for vector recall"
    )
    entities: list[KGManualEntityInput] = Field(default_factory=list)
    relations: list[KGManualRelationInput] = Field(default_factory=list)


class KGManualImportStats(BaseModel):
    entities: int = 0
    relations: int = 0
    events: int = 0
    chunks: int = 0
    aliases: int = 0
    warnings: int = 0


class KGManualImportIssue(BaseModel):
    level: str
    message: str
    row: int | None = None
    field: str | None = None


class KGManualImportPreviewResponse(BaseModel):
    import_id: str
    pipeline_hash: str
    name: str
    valid: bool
    stats: KGManualImportStats
    issues: list[KGManualImportIssue] = Field(default_factory=list)


class KGManualImportResponse(KGManualImportPreviewResponse):
    dataset_id: UUID | None = None
    document_id: UUID | None = None
    inserted: dict[str, int] = Field(default_factory=dict)
    vector_index: dict[str, Any] = Field(default_factory=dict)
    message: str = "Manual KG import completed"


class KGManualImportListItem(BaseModel):
    import_id: str
    name: str
    pipeline_hash: str
    dataset_id: UUID | None = None
    document_id: UUID
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KGManualImportListResponse(BaseModel):
    items: list[KGManualImportListItem] = Field(default_factory=list)


class KGManualImportDeleteResponse(BaseModel):
    import_id: str
    document_id: UUID
    events_deleted: int = 0
    relations_deleted: int = 0
    chunks_deleted: int = 0
    entities_pruned: int = 0
    message: str = "Manual KG import deleted"


class KGEntityMergeRequest(BaseModel):
    """Request body to merge one entity into another."""

    source_entity_id: UUID
    target_entity_id: UUID


class KGEntityMergeResponse(BaseModel):
    """Response after an entity merge action."""

    action_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    stats: dict[str, Any] = Field(default_factory=dict)


class KGEntityMergePreviewResponse(BaseModel):
    source_entity_id: UUID
    target_entity_id: UUID
    stats: dict[str, Any] = Field(default_factory=dict)


class KGEntityResolutionUndoResponse(BaseModel):
    """Response after undoing a resolution action."""

    action_id: UUID
    status: str
    stats: dict[str, Any] = Field(default_factory=dict)


class KGEntitySplitRequest(BaseModel):
    """Request body to split an entity into a new entity by moving selected event edges."""

    entity_id: UUID
    new_entity_name: str = Field(..., min_length=1, max_length=500)
    event_ids: list[UUID] = Field(default_factory=list, description="Event ids whose entity edges should be moved")


class KGEntitySplitResponse(BaseModel):
    """Response after splitting an entity."""

    action_id: UUID
    original_entity_id: UUID
    new_entity_id: UUID
    stats: dict[str, Any] = Field(default_factory=dict)


class KGEntityAliasCreateRequest(BaseModel):
    alias: str = Field(..., min_length=1, max_length=500)


class KGEntityAliasItem(KGBaseModel):
    id: UUID
    canonical_entity_id: UUID
    alias: str
    normalized_alias: str
    created_by: str | None = None
    extra_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("extra_data", mode="before")
    @classmethod
    def _coerce_alias_extra_data(cls, v: Any) -> dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGEntityAliasesResponse(BaseModel):
    entity_id: UUID
    resolved_entity_id: UUID
    aliases: list[KGEntityAliasItem] = Field(default_factory=list)


class KGEntityAliasSuggestionItem(BaseModel):
    entity_id: UUID
    name: str
    type: str
    similarity: float
    reason: str = ""


class KGEntityAliasSuggestionsResponse(BaseModel):
    entity_id: UUID
    suggestions: list[KGEntityAliasSuggestionItem] = Field(default_factory=list)
    mode: str = "offline"
    stats: dict[str, Any] = Field(default_factory=dict)


class KGPredicateOntologyItem(KGBaseModel):
    id: UUID
    tenant_id: UUID
    predicate: str
    display_name: str | None = None
    description: str | None = None
    is_enabled: bool = True
    extra_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("extra_data", mode="before")
    @classmethod
    def _coerce_onto_extra(cls, v: Any) -> dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGPredicateOntologyCreateRequest(BaseModel):
    predicate: str = Field(..., min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    is_enabled: bool = True


class KGPredicateOntologyUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    is_enabled: bool | None = None


class KGPredicateOntologyListResponse(BaseModel):
    predicates: list[KGPredicateOntologyItem] = Field(default_factory=list)
