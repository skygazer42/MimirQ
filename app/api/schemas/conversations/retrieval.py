"""Request and response contracts for retrieval preview and evidence APIs."""

from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.api.schemas.conversations.chat import ChatRAGConfig, HistoryMessage
from app.core.config import settings

RETRIEVAL_SCOPE_MAX_DATASET_IDS = 80
RETRIEVAL_SCOPE_MAX_DOCUMENT_IDS = 200


def _reject_retired_image_query(value: str | None) -> str | None:
    if value and value.strip():
        raise ValueError("query_image vector retrieval has been retired; use the regular text/OCR query")
    return value


class RetrievePreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    query_image: Annotated[str | None, AfterValidator(_reject_retired_image_query)] = Field(
        default=None,
        max_length=settings.RETRIEVAL_QUERY_MAX_CHARS,
        description="Retired image-vector query; nonempty values are rejected",
        deprecated=True,
    )
    history: list[HistoryMessage] = Field(default_factory=list)
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=RETRIEVAL_SCOPE_MAX_DATASET_IDS,
        description="Optional multi-dataset retrieval scope for Dify-style knowledge retrieval nodes.",
    )
    document_ids: list[UUID] = Field(default_factory=list, max_length=RETRIEVAL_SCOPE_MAX_DOCUMENT_IDS)
    rag_config_template_id: UUID | None = None  # Optional: explicit RAG config template selection.
    rag_config_template_key: str | None = None  # Optional: select latest active template by key.
    rag_config_ab_experiment_key: str | None = None  # Optional: stable A/B split for templates.
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    include_structure_trace: bool = Field(
        default=False,
        description=(
            "Attach bounded document-structure trace for visual tree debugging. Disabled by default "
            "to keep retrieval preview latency predictable."
        ),
    )


class RetrievePreviewResponse(BaseModel):
    query_for_retrieval: str
    citations: list[dict[str, Any]]
    metrics: dict[str, Any] = Field(default_factory=dict)


class DocumentStructureRequest(BaseModel):
    dataset_id: UUID
    document_id: UUID
    max_nodes: int = Field(default=200, ge=1, le=1000)


class TreeSearchPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=lambda: ChatRAGConfig(retrieval_profile="recall20"))
    max_structure_docs: int = Field(default=5, ge=1, le=20)
    max_nodes_per_doc: int = Field(default=120, ge=1, le=500)


class TreeSearchPreviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(
        default="mimirq.tree_search_preview.v1",
        alias="schema",
        serialization_alias="schema",
    )
    query: str
    query_for_retrieval: str
    citations: list[dict[str, Any]]
    document_structures: list[dict[str, Any]] = Field(default_factory=list)
    selected_sections: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str:
        return self.schema_


class EvidenceRetrieveRequest(BaseModel):
    """
    Production retrieval-only endpoint request.

    This is intentionally a small, stable contract for downstream systems that want to
    answer the question: "Do we have evidence for this query in the corpus?"
    """

    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    query_image: Annotated[str | None, AfterValidator(_reject_retired_image_query)] = Field(
        default=None,
        max_length=settings.RETRIEVAL_QUERY_MAX_CHARS,
        description="Retired image-vector query; nonempty values are rejected",
        deprecated=True,
    )
    history: list[HistoryMessage] = Field(default_factory=list)
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=RETRIEVAL_SCOPE_MAX_DATASET_IDS,
        description="Optional multi-dataset retrieval scope for Dify-style knowledge retrieval nodes.",
    )
    document_ids: list[UUID] = Field(default_factory=list, max_length=RETRIEVAL_SCOPE_MAX_DOCUMENT_IDS)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    # Optional deterministic seed for offline replay/regression.
    # PII-safe by construction (numeric only) and ignored by default.
    seed: int | None = None


class EvidenceRetrieveResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(
        default="mimirq.evidence.v1",
        alias="schema",
        serialization_alias="schema",
        description="Response schema identifier",
    )
    query_for_retrieval: str
    citations: list[dict[str, Any]]
    metrics: dict[str, Any] = Field(default_factory=dict)
    has_evidence: bool = False
    abstain_triggered: bool = False
    abstain_reason: str | None = None
    # Stable, versioned trace for downstream provenance parsing (separate from metrics/query_debug).
    retrieval_trace: dict[str, Any] | None = None
    # Immutable replay capsule (best-effort, optional).
    evidence_capsule: dict[str, Any] | None = None
    # Optional: debug payload for query normalization/expansion (best-effort).
    query_debug: dict[str, Any] | None = None

    @property
    def schema(self) -> str:
        return self.schema_


class PromptPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    history: list[HistoryMessage] = Field(default_factory=list)
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    structured_output: bool = False
    structured_preset: str | None = None
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None


class PromptPreviewResponse(BaseModel):
    query_for_retrieval: str
    prompt_messages: list[dict[str, Any]]
    prompt_text: str
    variables: dict[str, Any]
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    prompt_template_id: str | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    prompt_ab_variant: str | None = None
