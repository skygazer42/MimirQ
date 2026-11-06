"""Resolve retrieval identity, embedding shards, and filters with the caller's session."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.retrieval.corpus_index import CorpusScope
from app.rag.retrieval.hybrid.metadata_scope import collect_dataset_scope
from app.rag.retrieval.retriever_options import _dataset_scoped_runtime_lookup_error
from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig, resolve_dataset_embedding_runtime


@dataclass(frozen=True)
class RetrievalScope:
    tenant_id: UUID | None
    account_id: str | None
    dataset_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()
    metadata_filter: dict[str, Any] | None = None


@dataclass(frozen=True)
class RuntimeShard:
    runtime: DatasetEmbeddingRuntimeConfig
    dataset_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ResolvedRetrievalScope:
    scope: RetrievalScope
    runtime_dataset_ids: tuple[UUID, ...]
    runtime_shards: tuple[RuntimeShard, ...]
    runtime: DatasetEmbeddingRuntimeConfig
    metadata_filter: dict[str, Any] | None
    keyword_filter: dict[str, Any] | None
    vector_filter: dict[str, Any] | None
    has_unscoped_documents: bool

    @property
    def dataset_scope_ids(self) -> tuple[UUID, ...]:
        return normalize_dataset_scope_ids(self.scope.dataset_ids)

    @property
    def missing_dataset_ids(self) -> tuple[UUID, ...]:
        covered = {dataset_id for shard in self.runtime_shards for dataset_id in shard.dataset_ids}
        return tuple(dataset_id for dataset_id in self.runtime_dataset_ids if dataset_id not in covered)

    @property
    def corpus_scope(self) -> CorpusScope | None:
        if self.scope.tenant_id is None:
            return None
        return CorpusScope(
            tenant_id=self.scope.tenant_id,
            dataset_ids=self.runtime_dataset_ids,
            document_ids=self.scope.document_ids,
        )


def normalize_dataset_scope_ids(dataset_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(sorted(set(dataset_ids), key=str))


def default_embedding_runtime() -> DatasetEmbeddingRuntimeConfig:
    return replace(resolve_dataset_embedding_runtime(None), embedding_space_hash=current_embedding_space_hash())


def dataset_scope_filter_value(dataset_ids: tuple[UUID, ...]) -> str | dict[str, list[str]]:
    if len(dataset_ids) == 1:
        return str(dataset_ids[0])
    return {"$in": [str(dataset_id) for dataset_id in dataset_ids]}


def with_dataset_scope_filter(
    metadata_filter: dict[str, Any] | None, *, dataset_ids: tuple[UUID, ...]
) -> dict[str, Any] | None:
    if not dataset_ids:
        return metadata_filter
    scoped_filter = dict(metadata_filter or {})
    scoped_filter.setdefault("dataset_id", dataset_scope_filter_value(dataset_ids))
    return scoped_filter


def build_vector_filter(
    metadata_filter: dict[str, Any] | None,
    *,
    embedding_space: str,
    dataset_ids: tuple[UUID, ...] = (),
) -> dict[str, Any] | None:
    if not metadata_filter and not embedding_space and not dataset_ids:
        return None
    allowed = {
        "tenant_id",
        "dataset_id",
        "document_id",
        "embedding_space_hash",
        "chunk_id",
        "chunk_index",
        "pipeline_hash",
        "doc_pipeline_key",
        "source",
        "file_type",
        "img_id",
        "image_id",
        "image_url",
        "page_number",
        "partition_keys",
    }
    result: dict[str, Any] = {}
    for key, value in (metadata_filter or {}).items():
        if not isinstance(key, str) or "." in key:
            continue
        if key == "page":
            result["page_number"] = value
        elif key == "img_url":
            result["image_url"] = value
        elif key in allowed:
            result[key] = value
    if dataset_ids:
        result["dataset_id"] = dataset_scope_filter_value(dataset_ids)
    if embedding_space:
        result["embedding_space_hash"] = {"$in": [embedding_space, ""]}
    return result or None


def load_runtime_shards(db: Session, *, tenant_id: UUID, dataset_ids: tuple[UUID, ...]) -> tuple[RuntimeShard, ...]:
    rows = (
        db.query(DBDataset.id, DBDataset.dataset_metadata)
        .filter(
            DBDataset.tenant_id == tenant_id,
            DBDataset.id.in_(dataset_ids),
        )
        .all()
    )
    metadata_by_id: dict[UUID, dict[str, Any]] = {}
    for dataset_id, metadata in rows:
        if metadata is not None and not isinstance(metadata, dict):
            raise _dataset_scoped_runtime_lookup_error(tenant_id=tenant_id, dataset_ids=(dataset_id,), reason="invalid")
        metadata_by_id[dataset_id] = metadata if metadata is not None else {}
    missing = tuple(dataset_id for dataset_id in dataset_ids if dataset_id not in metadata_by_id)
    if missing:
        raise _dataset_scoped_runtime_lookup_error(tenant_id=tenant_id, dataset_ids=missing, reason="unavailable")
    current_space = current_embedding_space_hash()
    grouped: OrderedDict[DatasetEmbeddingRuntimeConfig, list[UUID]] = OrderedDict()
    for dataset_id in dataset_ids:
        runtime = resolve_dataset_embedding_runtime(metadata_by_id[dataset_id])
        if not runtime.dataset_scoped:
            runtime = replace(runtime, embedding_space_hash=current_space)
        grouped.setdefault(runtime, []).append(dataset_id)
    return tuple(RuntimeShard(runtime, tuple(group_ids)) for runtime, group_ids in grouped.items())


def resolve_document_datasets(
    db: Session, *, tenant_id: UUID, document_ids: tuple[UUID, ...]
) -> tuple[tuple[UUID, ...], bool]:
    rows = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(document_ids),
        )
        .all()
    )
    if {document_id for document_id, _dataset_id in rows} != set(document_ids):
        raise _dataset_scoped_runtime_lookup_error(
            tenant_id=tenant_id, document_ids=list(document_ids), reason="unavailable"
        )
    return (
        normalize_dataset_scope_ids(tuple(dataset_id for _document_id, dataset_id in rows if dataset_id is not None)),
        any(dataset_id is None for _document_id, dataset_id in rows),
    )


def resolve_runtime_scope(
    db: Session, *, scope: RetrievalScope, embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None
) -> ResolvedRetrievalScope:
    dataset_ids = normalize_dataset_scope_ids(scope.dataset_ids)
    metadata_filter = with_dataset_scope_filter(scope.metadata_filter, dataset_ids=dataset_ids)
    runtime_dataset_ids = dataset_ids
    has_unscoped_documents = False
    try:
        if not runtime_dataset_ids:
            if scope.document_ids:
                if scope.tenant_id is None:
                    raise _dataset_scoped_runtime_lookup_error(tenant_id=None, document_ids=list(scope.document_ids))
                runtime_dataset_ids, has_unscoped_documents = resolve_document_datasets(
                    db,
                    tenant_id=scope.tenant_id,
                    document_ids=scope.document_ids,
                )
            else:
                runtime_dataset_ids = normalize_dataset_scope_ids(tuple(collect_dataset_scope(metadata_filter)))
        shards: tuple[RuntimeShard, ...] = ()
        if runtime_dataset_ids:
            if scope.tenant_id is None:
                raise _dataset_scoped_runtime_lookup_error(tenant_id=None, dataset_ids=runtime_dataset_ids)
            shards = load_runtime_shards(db, tenant_id=scope.tenant_id, dataset_ids=runtime_dataset_ids)
        if has_unscoped_documents:
            default_runtime = default_embedding_runtime()
            grouped = OrderedDict((shard.runtime, shard.dataset_ids) for shard in shards)
            grouped[default_runtime] = ()
            shards = tuple(RuntimeShard(runtime, group_ids) for runtime, group_ids in grouped.items())
    except (ValueError, LookupError):
        raise
    except Exception as exc:
        raise _dataset_scoped_runtime_lookup_error(
            tenant_id=scope.tenant_id,
            dataset_ids=runtime_dataset_ids,
            document_ids=list(scope.document_ids),
            reason="unavailable",
        ) from exc
    runtime = shards[0].runtime if len(shards) == 1 else embedding_runtime or default_embedding_runtime()
    keyword_filter = None
    vector_filter = None
    if metadata_filter:
        keyword_filter = {key: value for key, value in metadata_filter.items() if not key.startswith("document_user.")}
        vector_filter = build_vector_filter(keyword_filter, embedding_space=runtime.embedding_space_hash)
    return ResolvedRetrievalScope(
        scope=scope,
        runtime_dataset_ids=runtime_dataset_ids,
        runtime_shards=shards,
        runtime=runtime,
        metadata_filter=metadata_filter,
        keyword_filter=keyword_filter,
        vector_filter=vector_filter,
        has_unscoped_documents=has_unscoped_documents,
    )
