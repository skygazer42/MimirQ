"""Request/query parameter models and dataclass containers for the KG API routes.

Split out of ``app.rag.kg.api.routes`` (see ``app.rag.kg.api.routes_support``).
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.rag.kg.schemas import KGGraphResponse


class KGGraphProjectionParams(BaseModel):
    document_ids: list[UUID] | None = None
    dataset_id: UUID | None = None
    pipeline_hash: str | None = None
    max_events: int | None = None
    max_entities: int | None = None
    max_links: int | None = None
    include_entity_links: bool = False
    include_relation_links: bool = False
    min_shared_events: int | None = None
    max_entity_links: int | None = None


class KGGraphExportFlags(BaseModel):
    download: bool = True
    gzip_output: bool = False


class KGExtractionOptions(BaseModel):
    async_mode: bool = False
    pipeline_hash: str | None = None
    replace_existing: bool | None = None
    prune_orphan_entities: bool | None = None
    extract_relations: bool | None = None
    extract_skills: bool | None = None
    extraction_backend: str | None = None
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None


@dataclass
class KGGraphProjectionLimits:
    max_events: int
    max_entities: int
    max_links: int
    include_entity_links: bool
    include_relation_links: bool
    min_shared_events: int
    max_entity_links: int


@dataclass
class KGGraphBuildResult:
    response: KGGraphResponse
    event_entity_links: int
    relation_links_added: int
    entity_links_added: int


@dataclass
class KGSnapshotCounts:
    docs: int
    events: int
    entities: int
    links: int
    relations: int
    updated_at: Any
    entity_types: list[dict[str, Any]]


@dataclass
class KGSnapshotDetailRows:
    events: list[Any]
    entities: list[Any]
    links: list[Any]
    relations: list[Any]


@dataclass
class KGMergeTargets:
    source_id: UUID
    target_id: UUID
    source_entity: Any
    target_entity: Any


@dataclass
class KGMergeAffectedRows:
    source_assocs: list[Any]
    source_assoc_ids: set[str]
    assoc_snapshot_by_id: dict[str, dict[str, Any]]
    impacted_event_ids: set[UUID]
    source_relations: list[Any]
    source_relation_ids: set[str]
    relation_snapshot_by_id: dict[str, dict[str, Any]]


@dataclass
class KGMergeSideEffects:
    deleted_assoc_rows: list[dict[str, Any]]
    relation_deleted_rows: list[dict[str, Any]]
    redirect_created: bool
    vector_deleted: bool


@dataclass
class KGUndoStats:
    source_id: UUID | None
    target_id: UUID | None
    restored_edges: int = 0
    restored_relations: int = 0
    redirect_removed: bool = False
    deleted_new_entity: bool = False


@dataclass
class KGExtractionEffectiveOptions:
    pipeline_hash: str | None
    prompt_template_id: UUID | None
    prompt_template_key: str | None
    prompt_ab_experiment_key: str | None
    kg_python_plugin: str | None
    kg_python_params: dict[str, Any]
    replace_existing: bool
    prune_orphan_entities: bool
    extract_relations: bool | None
    extract_skills: bool | None
    extraction_backend: str | None
