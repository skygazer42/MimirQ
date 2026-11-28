"""HTTP contracts for enterprise ontology authoring and previews."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.api.schemas.conversations import Citation
from app.rag.kg.enterprise_ontology.consumption import OntologyAnswer
from app.rag.kg.enterprise_ontology.definition import ObjectDefinition, OntologyDefinition, RelationDefinition
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, PreviewEntity, PreviewRelation


class OntologyKnowledgeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    dataset_ids: list[UUID] = Field(min_length=1, max_length=20)
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=500)
    observed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class OntologyKnowledgeAnswer(BaseModel):
    ontology: OntologyAnswer
    answer: str
    citations: list[Citation]
    metrics: dict[str, Any]


class OntologyImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, StringConstraints(min_length=1, max_length=262144)]
    format: Literal["yaml", "json"]


class SamplePreviewSource(BaseModel):
    kind: Literal["sample"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30000)]


class DocumentPreviewSource(BaseModel):
    kind: Literal["document"]
    document_id: UUID
    pipeline_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    limit: int = Field(default=4, ge=1, le=12)


class OntologyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: OntologyDefinition
    source: Annotated[SamplePreviewSource | DocumentPreviewSource, Field(discriminator="kind")]


class OntologyDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    definition: OntologyDefinition


class OntologyPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class OntologyDraftView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    draft_revision: int
    draft: OntologyDefinition


class OntologyVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ontology_id: UUID
    number: int
    draft_revision: int
    definition: OntologyDefinition
    created_at: datetime
    created_by: str


class OntologyDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    pipeline_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None


class OntologyDocumentView(BaseModel):
    document_id: UUID
    version_id: UUID
    pipeline_hash: str
    chunk_count: int


class DatasetOntologyView(BaseModel):
    dataset_id: UUID
    version_id: UUID | None


class OntologyGraphChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[PreviewEntity]
    relations: list[PreviewRelation]


class OntologyGraphEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    graph: OntologyGraphChanges | None


class OntologyGraphChunk(BaseModel):
    id: UUID
    page: int | None
    index: int


class OntologyDocumentGraph(BaseModel):
    version_id: UUID
    version_number: int
    pipeline_hash: str
    revision: str
    can_edit: bool
    corrected: bool
    chunks: list[OntologyGraphChunk]
    chunk: ChunkPreview
    source_text: str
    object_types: dict[str, ObjectDefinition]
    relations: dict[str, RelationDefinition]
