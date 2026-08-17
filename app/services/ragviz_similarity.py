"""
RAG visualization (ragviz) - collection-to-collection similarity.

This module provides a small "collection" abstraction on top of existing MimirQ
data (datasets/documents/regression cases) so the frontend can compute
collection-collection similarity heatmaps similar to Kumi.
"""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.evaluation import RagasRegressionCase
from app.rag.core.logging import get_logger
from app.rag.embedding import create_langchain_embeddings_from_config
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids


@dataclass(frozen=True)
class RagvizCollection:
    id: str
    label: str
    kind: str
    count: int
    meta: dict[str, Any]


_embeddings_adapter = None
_DEFAULT_SIMILARITY_MAX_ITEMS = 100


class SimilarityLimitError(ValueError):
    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def _get_embeddings_adapter():
    global _embeddings_adapter
    if _embeddings_adapter is not None:
        return _embeddings_adapter

    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or ""
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or ""

    _embeddings_adapter = create_langchain_embeddings_from_config(
        provider=mapped_provider,
        model=settings.EMBEDDING_MODEL,
        api_key=api_key,
        base_url=base_url,
        dimension=None,
    )
    return _embeddings_adapter


def _parse_collection_id(collection_id: str) -> tuple[str, str]:
    raw = str(collection_id or "").strip()
    if ":" not in raw:
        raise ValueError("Invalid collection id")
    kind, value = raw.split(":", 1)
    kind = kind.strip()
    value = value.strip()
    if not kind or not value:
        raise ValueError("Invalid collection id")
    return kind, value


def _similarity_axis_limit() -> int:
    return max(1, int(getattr(settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500) or 500))


def _similarity_pair_limit() -> int:
    return max(1, int(getattr(settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 200_000) or 200_000))


def resolve_similarity_request_limits(
    *,
    x_max_items: int | None,
    y_max_items: int | None,
    max_items: int | None = None,
) -> tuple[int, int]:
    fallback_items = max_items if max_items is not None else _DEFAULT_SIMILARITY_MAX_ITEMS
    resolved = {
        "x_max_items": x_max_items if x_max_items is not None else fallback_items,
        "y_max_items": y_max_items if y_max_items is not None else fallback_items,
    }
    axis_limit = _similarity_axis_limit()
    pair_limit = _similarity_pair_limit()

    normalized: dict[str, int] = {}
    for field_name, raw_value in resolved.items():
        value = int(raw_value)
        if value < 1:
            raise SimilarityLimitError(
                f"{field_name} must be greater than or equal to 1",
                detail={"field": field_name, "requested": value, "minimum": 1},
            )
        if value > axis_limit:
            raise SimilarityLimitError(
                f"{field_name} exceeds ragviz similarity axis limit ({value} > {axis_limit})",
                detail={"field": field_name, "requested": value, "limit": axis_limit},
            )
        normalized[field_name] = value

    total_pairs = normalized["x_max_items"] * normalized["y_max_items"]
    if total_pairs > pair_limit:
        raise SimilarityLimitError(
            "requested ragviz similarity matrix exceeds pair limit "
            f"({normalized['x_max_items']} x {normalized['y_max_items']} = {total_pairs} > {pair_limit})",
            detail={
                "field": "total_pairs",
                "x_max_items": normalized["x_max_items"],
                "y_max_items": normalized["y_max_items"],
                "requested": total_pairs,
                "limit": pair_limit,
            },
        )

    return normalized["x_max_items"], normalized["y_max_items"]


def _is_dataset_readable(ds: Dataset, account_id: str, *, allowed_partial_ids: set[UUID]) -> bool:
    if ds.owner_id == account_id:
        return True
    if ds.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS:
        return True
    if ds.permission == DatasetPermissionEnum.ONLY_ME:
        return False
    return ds.id in allowed_partial_ids


def list_similarity_collections(db: Session, tenant_id: UUID, account_id: str) -> list[RagvizCollection]:
    DatasetService.ensure_member(db, tenant_id, account_id)

    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).order_by(Dataset.created_at.desc()).all()
    partial_ids = [
        ds.id for ds in datasets if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS and ds.owner_id != account_id
    ]

    allowed_partial_ids: set[UUID] = set()
    if partial_ids:
        rows = (
            db.query(DatasetPermission.dataset_id)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.account_id == account_id,
                DatasetPermission.dataset_id.in_(partial_ids),
            )
            .all()
        )
        allowed_partial_ids = {row[0] for row in rows}

    readable_datasets = [
        ds for ds in datasets if _is_dataset_readable(ds, account_id, allowed_partial_ids=allowed_partial_ids)
    ]
    if not readable_datasets:
        return []

    dataset_ids = [ds.id for ds in readable_datasets]

    # Chunk count per dataset (completed docs only).
    chunk_counts = dict(
        db.query(DBDocument.dataset_id, func.coalesce(func.sum(DBDocument.chunk_count), 0))
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.status == "completed",
            DBDocument.dataset_id.in_(dataset_ids),
        )
        .group_by(DBDocument.dataset_id)
        .all()
    )

    # Regression case count per dataset.
    case_counts = dict(
        db.query(RagasRegressionCase.dataset_id, func.count(RagasRegressionCase.id))
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.dataset_id.in_(dataset_ids),
        )
        .group_by(RagasRegressionCase.dataset_id)
        .all()
    )

    collections: list[RagvizCollection] = []
    for ds in readable_datasets:
        ds_chunk_count = int(chunk_counts.get(ds.id) or 0)
        ds_case_count = int(case_counts.get(ds.id) or 0)

        collections.append(
            RagvizCollection(
                id=f"dataset_chunks:{ds.id}",
                label=f"【Dataset Chunks】{ds.name}",
                kind="dataset_chunks",
                count=ds_chunk_count,
                meta={"dataset_id": str(ds.id), "dataset_name": ds.name},
            )
        )
        collections.append(
            RagvizCollection(
                id=f"regression_questions:{ds.id}",
                label=f"【Regression Questions】{ds.name}",
                kind="regression_questions",
                count=ds_case_count,
                meta={"dataset_id": str(ds.id), "dataset_name": ds.name},
            )
        )
        collections.append(
            RagvizCollection(
                id=f"regression_chunks:{ds.id}",
                label=f"【Regression GroundTruth Chunks】{ds.name}",
                kind="regression_chunks",
                count=ds_case_count,
                meta={"dataset_id": str(ds.id), "dataset_name": ds.name},
            )
        )

    return collections


def _dataset_chunks_items(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    ds = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")
    DatasetService.assert_dataset_readable(db, ds, account_id)

    rows = (
        db.query(DocumentChunk, DBDocument.filename, DBDocument.id, DBDocument.file_type)
        .join(DBDocument, DBDocument.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed",
        )
        .order_by(DBDocument.filename.asc(), DocumentChunk.chunk_index.asc())
        .limit(max_items)
        .all()
    )

    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for idx, (chunk, filename, document_id, file_type) in enumerate(rows):
        items.append(
            {
                "id": str(chunk.id),
                "order_id": idx,
                "document_id": str(document_id),
                "document": str(filename or ""),
                "file_type": str(file_type or ""),
                "chunk_index": int(chunk.chunk_index),
                "page_number": int(chunk.page_number or 0),
                "text": chunk.content,
            }
        )
        texts.append(chunk.content or "")
    return items, texts


def _document_chunks_items(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    allowed_ids = filter_allowed_document_ids(db, tenant_id, account_id, [document_id])
    if not allowed_ids:
        raise ValueError("No accessible document")

    doc = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id).first()
    if not doc:
        raise ValueError("Document not found")

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(max_items)
        .all()
    )

    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for idx, chunk in enumerate(rows):
        items.append(
            {
                "id": str(chunk.id),
                "order_id": idx,
                "document_id": str(document_id),
                "document": str(doc.filename or ""),
                "file_type": str(doc.file_type or ""),
                "chunk_index": int(chunk.chunk_index),
                "page_number": int(chunk.page_number or 0),
                "text": chunk.content,
            }
        )
        texts.append(chunk.content or "")
    return items, texts


def _regression_cases_base_query(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
):
    ds = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")
    DatasetService.assert_dataset_readable(db, ds, account_id)

    return (
        db.query(RagasRegressionCase)
        .filter(RagasRegressionCase.tenant_id == tenant_id, RagasRegressionCase.dataset_id == dataset_id)
        .order_by(RagasRegressionCase.created_at.asc())
    )


def _regression_questions_items(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    query = _regression_cases_base_query(db, tenant_id, account_id, dataset_id)

    # Only keep cases with ground-truth chunk id so it can align with regression_chunks.
    rows = query.limit(max_items * 10).all()

    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for row in rows:
        extra = row.extra if isinstance(row.extra, dict) else {}
        chunk_id = str(extra.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        items.append(
            {
                "id": str(row.id),
                "order_id": len(items),
                "document": str(row.question or ""),
                "text": str(row.question or ""),
                "expected_answer": row.expected_answer,
                "tags": row.tags or [],
                "source_document_id": (
                    row.document_ids[0] if isinstance(row.document_ids, list) and row.document_ids else ""
                ),
                "chunk_id": chunk_id,
            }
        )
        texts.append(str(row.question or ""))
        if len(items) >= max_items:
            break
    return items, texts


def _regression_chunks_items(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    query = _regression_cases_base_query(db, tenant_id, account_id, dataset_id)
    rows = query.limit(max_items * 10).all()

    wanted: list[UUID] = []
    ordered_case_rows: list[tuple[RagasRegressionCase, UUID]] = []
    for row in rows:
        extra = row.extra if isinstance(row.extra, dict) else {}
        chunk_id_raw = str(extra.get("chunk_id") or "").strip()
        if not chunk_id_raw:
            continue
        try:
            chunk_uuid = UUID(chunk_id_raw)
        except Exception:  # noqa: BLE001
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        ordered_case_rows.append((row, chunk_uuid))
        wanted.append(chunk_uuid)
        if len(ordered_case_rows) >= max_items:
            break

    if not wanted:
        return [], []

    chunk_rows = (
        db.query(DocumentChunk, DBDocument.filename, DBDocument.id, DBDocument.file_type)
        .join(DBDocument, DBDocument.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(wanted),
            DBDocument.tenant_id == tenant_id,
        )
        .all()
    )
    chunk_map: dict[UUID, tuple[DocumentChunk, str, UUID, str]] = {}
    for chunk, filename, doc_id, file_type in chunk_rows:
        chunk_map[chunk.id] = (chunk, str(filename or ""), doc_id, str(file_type or ""))

    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for case, chunk_id in ordered_case_rows:
        mapped = chunk_map.get(chunk_id)
        if not mapped:
            continue
        chunk, filename, doc_id, file_type = mapped
        items.append(
            {
                "id": str(chunk.id),
                "order_id": len(items),
                "case_id": str(case.id),
                "document_id": str(doc_id),
                "document": filename,
                "file_type": file_type,
                "chunk_index": int(chunk.chunk_index),
                "page_number": int(chunk.page_number or 0),
                "text": chunk.content,
            }
        )
        texts.append(chunk.content or "")
        if len(items) >= max_items:
            break

    return items, texts


def get_collection_items(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    collection_id: str,
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    kind, value = _parse_collection_id(collection_id)

    if max_items <= 0:
        return [], []

    if kind == "dataset_chunks":
        return _dataset_chunks_items(db, tenant_id, account_id, UUID(value), max_items=max_items)
    if kind == "document_chunks":
        return _document_chunks_items(db, tenant_id, account_id, UUID(value), max_items=max_items)
    if kind == "regression_questions":
        return _regression_questions_items(db, tenant_id, account_id, UUID(value), max_items=max_items)
    if kind == "regression_chunks":
        return _regression_chunks_items(db, tenant_id, account_id, UUID(value), max_items=max_items)

    raise ValueError("Unsupported collection kind")


def _raise_empty_collection_error(
    *,
    x_collection: str,
    y_collection: str,
    x_items: list[dict[str, Any]],
    y_items: list[dict[str, Any]],
) -> None:
    empty_parts: list[str] = []
    if not x_items:
        empty_parts.append(f"X 轴无数据: {x_collection}")
    if not y_items:
        empty_parts.append(f"Y 轴无数据: {y_collection}")

    if empty_parts:
        raise ValueError("所选 Collection 无可计算数据；" + "；".join(empty_parts))


def calculate_similarity_matrix(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    *,
    x_collection: str,
    y_collection: str,
    x_max_items: int,
    y_max_items: int,
) -> dict[str, Any]:
    start = time.time()
    x_max_items, y_max_items = resolve_similarity_request_limits(
        x_max_items=x_max_items,
        y_max_items=y_max_items,
    )

    x_items, x_texts = get_collection_items(db, tenant_id, account_id, x_collection, max_items=x_max_items)
    y_items, y_texts = get_collection_items(db, tenant_id, account_id, y_collection, max_items=y_max_items)

    if not x_items or not y_items:
        _raise_empty_collection_error(
            x_collection=x_collection,
            y_collection=y_collection,
            x_items=x_items,
            y_items=y_items,
        )

    embeddings = _get_embeddings_adapter()
    x_vectors = embeddings.embed_documents(x_texts)
    y_vectors = embeddings.embed_documents(y_texts)

    x_arr = np.array(x_vectors, dtype=float)
    y_arr = np.array(y_vectors, dtype=float)
    if x_arr.ndim != 2 or y_arr.ndim != 2 or x_arr.shape[1] != y_arr.shape[1]:
        raise ValueError(f"向量维度不匹配: {x_arr.shape} vs {y_arr.shape}")

    sim = y_arr @ x_arr.T
    # Match Kumi behavior: clamp into [0, 1] for "similarity".
    sim = np.clip(sim, 0.0, 1.0)
    matrix = sim.tolist()

    flat = sim.reshape(-1)
    stats = {
        "total_pairs": int(flat.size),
        "avg_similarity": float(np.mean(flat)),
        "min_similarity": float(np.min(flat)),
        "max_similarity": float(np.max(flat)),
        "std_similarity": float(np.std(flat)),
        "high_similarity_count": int(np.sum(flat > 0.8)),
        "medium_similarity_count": int(np.sum((flat >= 0.5) & (flat <= 0.8))),
        "low_similarity_count": int(np.sum(flat < 0.5)),
        "compute_time": (time.time() - start) * 1000.0,
    }

    x_available_fields = [k for k in (x_items[0].keys() if x_items else []) if k != "id"]
    y_available_fields = [k for k in (y_items[0].keys() if y_items else []) if k != "id"]

    return {
        "matrix": matrix,
        "x_data": x_items,
        "y_data": y_items,
        "x_available_fields": x_available_fields,
        "y_available_fields": y_available_fields,
        "stats": stats,
        "metadata": {
            "x_collection": x_collection,
            "y_collection": y_collection,
            "x_max_items": int(x_max_items),
            "y_max_items": int(y_max_items),
            "calculation_time": time.time() - start,
        },
    }
