"""Manual, governed KG import support.

This module is deliberately domain-neutral. Business-specific graph building
belongs outside MimirQ; MimirQ only validates and imports curated entity/relation
rows into the existing KG storage model with document-level provenance.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document, DocumentChunk
from app.rag.kg.models import KgEntity, KgEntityAlias, KgEventEntity, KgRelation, KgSourceEvent
from app.rag.kg.schemas import (
    KGManualEntityInput,
    KGManualEntityRef,
    KGManualImportDeleteResponse,
    KGManualImportIssue,
    KGManualImportListItem,
    KGManualImportListResponse,
    KGManualImportPreviewResponse,
    KGManualImportRequest,
    KGManualImportResponse,
    KGManualImportStats,
    KGManualRelationInput,
)
from app.services.dataset_embedding_config import create_embeddings_for_runtime
from app.services.dataset_service import DatasetService
from app.services.indexer import Indexer

logger = logging.getLogger(__name__)

MANUAL_KG_NAMESPACE = uuid.UUID("f69d7ee1-a4d5-45f4-89e1-bfd23315f4a9")
MANUAL_KG_FORMAT = "mimirq_manual_kg_v1"
DEFAULT_MANUAL_DATASET_NAME = "手动知识图谱"
ENTITY_NAME_MAX = 500
ENTITY_NAME_HEAD = 220
ENTITY_NAME_TAIL = 80
REGISTRY_EVENT_ENTITY_BATCH = 200


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u3000", " ")).strip()


def _normalized_key(value: Any) -> str:
    return re.sub(r"\s+", "", _norm(value)).lower()


def _short_hash(value: str, size: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:size]


def _stable_uuid(kind: str, key: str) -> UUID:
    return uuid.uuid5(MANUAL_KG_NAMESPACE, f"{kind}|{key}")


def _compact_entity_label(value: str, *, allow: bool) -> tuple[str, dict[str, Any]]:
    text = _norm(value)
    if len(text) <= ENTITY_NAME_MAX and len(_normalized_key(text)) <= ENTITY_NAME_MAX:
        return text, {}
    if not allow:
        raise ValueError("Entity name exceeds KG label limit")
    digest = _short_hash(text, 10)
    compact = f"{text[:ENTITY_NAME_HEAD]} ... {text[-ENTITY_NAME_TAIL:]} [{digest}]"
    if len(compact) > ENTITY_NAME_MAX:
        compact = f"{text[: ENTITY_NAME_MAX - 16]} [{digest}]"
    return compact, {
        "full_value": text,
        "full_value_hash": digest,
        "label_truncated": True,
    }


def _json_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass
class _EntityRow:
    key: str
    name: str
    type: str
    description: str | None = None
    aliases: list[str] = field(default_factory=list)
    extra_data: dict[str, Any] = field(default_factory=dict)
    row: int | None = None

    @property
    def normalized_name(self) -> str:
        return _normalized_key(self.name)


@dataclass
class _RelationRow:
    subject_key: str
    predicate: str
    object_key: str
    confidence: float = 1.0
    evidence: str = ""
    source: str = ""
    qualifiers: dict[str, Any] = field(default_factory=dict)
    references: dict[str, Any] = field(default_factory=dict)
    extra_data: dict[str, Any] = field(default_factory=dict)
    row: int | None = None


EmbeddingJob = tuple[str, KgSourceEvent | KgEntity, str, str]


@dataclass
class _NormalizedImport:
    import_id: str
    pipeline_hash: str
    name: str
    entities: list[_EntityRow]
    relations: list[_RelationRow]
    issues: list[KGManualImportIssue]

    @property
    def valid(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def stats(self) -> KGManualImportStats:
        relation_entity_keys = {rel.subject_key for rel in self.relations} | {rel.object_key for rel in self.relations}
        isolated_entities = max(0, len([ent for ent in self.entities if ent.key not in relation_entity_keys]))
        registry_events = (isolated_entities + REGISTRY_EVENT_ENTITY_BATCH - 1) // REGISTRY_EVENT_ENTITY_BATCH
        events = len(self.relations) + registry_events
        return KGManualImportStats(
            entities=len(self.entities),
            relations=len(self.relations),
            events=events,
            chunks=events,
            aliases=sum(len(ent.aliases) for ent in self.entities),
            warnings=len([issue for issue in self.issues if issue.level == "warning"]),
        )


@dataclass
class _EntityInsertResult:
    entity_by_key: dict[str, KgEntity]
    inserted_entities: int = 0
    inserted_aliases: int = 0


@dataclass
class _ManualImportWriteState:
    chunk_index: int = 0
    inserted_events: int = 0
    inserted_links: int = 0
    imported_events: list[KgSourceEvent] = field(default_factory=list)


def _add_issue(
    issues: list[KGManualImportIssue],
    *,
    level: str,
    message: str,
    row: int | None = None,
    field_name: str | None = None,
) -> None:
    issues.append(KGManualImportIssue(level=level, row=row, field=field_name, message=message))


def _default_import_id(payload: KGManualImportRequest) -> str:
    seed = "|".join(
        [
            payload.name,
            str(len(payload.entities)),
            str(len(payload.relations)),
            _short_hash("|".join(f"{e.type}:{e.name}" for e in payload.entities[:100]), 16),
            _short_hash("|".join(f"{r.predicate}" for r in payload.relations[:100]), 16),
        ]
    )
    return f"manual_kg_{_short_hash(seed, 16)}"


def _endpoint_to_key(
    endpoint: str | KGManualEntityRef,
    *,
    entities_by_key: dict[str, _EntityRow],
    issues: list[KGManualImportIssue],
    row: int,
    field_name: str,
) -> str:
    if isinstance(endpoint, str):
        key = _norm(endpoint)
        if not key:
            issues.append(
                KGManualImportIssue(level="error", row=row, field=field_name, message="Relation endpoint is empty")
            )
        return key

    raw_key = _norm(endpoint.key)
    if raw_key:
        return raw_key

    name = _norm(endpoint.name)
    type_ = _norm(endpoint.type or "Entity")
    if not name:
        issues.append(
            KGManualImportIssue(
                level="error", row=row, field=field_name, message="Inline relation endpoint requires name"
            )
        )
        return ""

    key = f"inline:{type_}:{_normalized_key(name)}"
    if key not in entities_by_key:
        entities_by_key[key] = _EntityRow(key=key, name=name, type=type_, row=row)
    return key


def _normalize_entity_input(
    item: KGManualEntityInput,
    *,
    row_index: int,
    issues: list[KGManualImportIssue],
) -> tuple[str, tuple[str, str], _EntityRow] | None:
    ent_name = _norm(item.name)
    ent_type = _norm(item.type)
    key = _norm(item.key) or f"{ent_type}:{_normalized_key(ent_name)}"
    if not ent_name:
        _add_issue(issues, level="error", row=row_index, field_name="entities.name", message="Entity name is required")
        return None
    if not ent_type:
        _add_issue(issues, level="error", row=row_index, field_name="entities.type", message="Entity type is required")
        return None
    if len(ent_type) > 100:
        _add_issue(
            issues,
            level="error",
            row=row_index,
            field_name="entities.type",
            message="Entity type exceeds 100 characters",
        )
        return None

    aliases = [_norm(alias) for alias in item.aliases if _norm(alias)]
    return (
        key,
        (ent_type, _normalized_key(ent_name)),
        _EntityRow(
            key=key,
            name=ent_name,
            type=ent_type,
            description=_norm(item.description) or None,
            aliases=aliases,
            extra_data=_json_dict(item.extra_data),
            row=row_index,
        ),
    )


def _normalize_entity_rows(
    payload: KGManualImportRequest,
    issues: list[KGManualImportIssue],
) -> dict[str, _EntityRow]:
    entities_by_key: dict[str, _EntityRow] = {}
    seen_type_name: set[tuple[str, str]] = set()
    for idx, item in enumerate(payload.entities, 1):
        normalized = _normalize_entity_input(item, row_index=idx, issues=issues)
        if not normalized:
            continue
        key, type_name, row = normalized
        if key in entities_by_key:
            _add_issue(
                issues,
                level="warning",
                row=idx,
                field_name="entities.key",
                message=f"Duplicate entity key ignored: {key}",
            )
            continue
        if type_name in seen_type_name:
            _add_issue(
                issues,
                level="warning",
                row=idx,
                field_name="entities.name",
                message=f"Duplicate entity label/type: {row.type}/{row.name}",
            )
        seen_type_name.add(type_name)
        entities_by_key[key] = row

    if not entities_by_key:
        _add_issue(issues, level="error", field_name="entities", message="At least one entity is required")
    return entities_by_key


def _normalize_relation_input(
    item: KGManualRelationInput,
    *,
    row_index: int,
    entities_by_key: dict[str, _EntityRow],
    issues: list[KGManualImportIssue],
) -> _RelationRow | None:
    subject_key = _endpoint_to_key(
        item.subject, entities_by_key=entities_by_key, issues=issues, row=row_index, field_name="relations.subject"
    )
    object_key = _endpoint_to_key(
        item.object, entities_by_key=entities_by_key, issues=issues, row=row_index, field_name="relations.object"
    )
    predicate = _norm(item.predicate)
    if not predicate:
        _add_issue(
            issues, level="error", row=row_index, field_name="relations.predicate", message="Predicate is required"
        )
        return None
    if len(predicate) > 200:
        _add_issue(
            issues,
            level="error",
            row=row_index,
            field_name="relations.predicate",
            message="Predicate exceeds 200 characters",
        )
        return None
    if subject_key and subject_key not in entities_by_key:
        _add_issue(
            issues,
            level="error",
            row=row_index,
            field_name="relations.subject",
            message=f"Unknown subject key: {subject_key}",
        )
    if object_key and object_key not in entities_by_key:
        _add_issue(
            issues,
            level="error",
            row=row_index,
            field_name="relations.object",
            message=f"Unknown object key: {object_key}",
        )
    if not subject_key or not object_key:
        return None
    return _RelationRow(
        subject_key=subject_key,
        predicate=predicate,
        object_key=object_key,
        confidence=float(item.confidence),
        evidence=_norm(item.evidence),
        source=_norm(item.source),
        qualifiers=_json_dict(item.qualifiers),
        references=_json_dict(item.references),
        extra_data=_json_dict(item.extra_data),
        row=row_index,
    )


def _normalize_relation_rows(
    payload: KGManualImportRequest,
    *,
    entities_by_key: dict[str, _EntityRow],
    issues: list[KGManualImportIssue],
) -> list[_RelationRow]:
    relations: list[_RelationRow] = []
    for idx, item in enumerate(payload.relations, 1):
        row = _normalize_relation_input(item, row_index=idx, entities_by_key=entities_by_key, issues=issues)
        if row:
            relations.append(row)
    return relations


def normalize_manual_import(payload: KGManualImportRequest) -> _NormalizedImport:
    issues: list[KGManualImportIssue] = []
    import_id = _norm(payload.import_id) or _default_import_id(payload)
    import_id = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", import_id)[:120] or _default_import_id(payload)
    pipeline_hash = _norm(payload.pipeline_hash) or f"{import_id}:manual"
    name = _norm(payload.name) or "手动知识图谱导入"
    entities_by_key = _normalize_entity_rows(payload, issues)
    relations = _normalize_relation_rows(payload, entities_by_key=entities_by_key, issues=issues)

    return _NormalizedImport(
        import_id=import_id,
        pipeline_hash=pipeline_hash[:200],
        name=name,
        entities=list(entities_by_key.values()),
        relations=relations,
        issues=issues,
    )


def preview_manual_import(payload: KGManualImportRequest) -> KGManualImportPreviewResponse:
    normalized = normalize_manual_import(payload)
    return KGManualImportPreviewResponse(
        import_id=normalized.import_id,
        pipeline_hash=normalized.pipeline_hash,
        name=normalized.name,
        valid=normalized.valid,
        stats=normalized.stats(),
        issues=normalized.issues[:200],
    )


def _ensure_import_dataset(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    payload: KGManualImportRequest,
) -> Dataset:
    if payload.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
        return dataset

    dataset_name = _norm(payload.dataset_name) or DEFAULT_MANUAL_DATASET_NAME
    existing = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.name == dataset_name).first()
    if existing:
        DatasetService.assert_dataset_writable(db, existing, account_id)
        return existing

    return DatasetService.create_dataset(
        db,
        tenant_id,
        name=dataset_name,
        description="人工治理后导入的知识图谱数据集",
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id=account_id,
    )


def _find_import_document(db: Session, *, tenant_id: UUID, import_id: str) -> Document | None:
    return (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.doc_metadata.op("->>")("manual_kg_import_id") == import_id,
        )
        .order_by(Document.updated_at.desc())
        .first()
    )


def _document_pipeline_hash(document: Document) -> str:
    meta = document.doc_metadata or {}
    return str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or "")


def _document_relations_query(db: Session, *, tenant_id: UUID, document: Document, pipeline_hash: str):
    query = db.query(KgRelation).filter(KgRelation.tenant_id == tenant_id, KgRelation.document_id == document.id)
    return query.filter(KgRelation.pipeline_hash == pipeline_hash) if pipeline_hash else query


def _document_events_query(db: Session, *, tenant_id: UUID, document: Document, pipeline_hash: str):
    query = db.query(KgSourceEvent).filter(
        KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id == document.id
    )
    return query.filter(KgSourceEvent.pipeline_hash == pipeline_hash) if pipeline_hash else query


def _manual_import_candidate_entity_ids(db: Session, *, tenant_id: UUID, import_id: str) -> list[UUID]:
    return [
        row[0]
        for row in db.query(KgEntity.id)
        .filter(
            KgEntity.tenant_id == tenant_id,
            KgEntity.extra_data.op("->>")("manual_kg_import_id") == import_id,
            KgEntity.extra_data.op("->>")("manual_kg_created") == "true",
        )
        .all()
    ]


def _linked_manual_entity_ids(db: Session, candidate_ids: list[UUID]) -> set[UUID]:
    event_ids = {
        row[0]
        for row in db.query(KgEventEntity.entity_id).filter(KgEventEntity.entity_id.in_(candidate_ids)).distinct().all()
    }
    subject_ids = {
        row[0]
        for row in db.query(KgRelation.subject_entity_id)
        .filter(KgRelation.subject_entity_id.in_(candidate_ids))
        .distinct()
        .all()
    }
    object_ids = {
        row[0]
        for row in db.query(KgRelation.object_entity_id)
        .filter(KgRelation.object_entity_id.in_(candidate_ids))
        .distinct()
        .all()
    }
    return event_ids | subject_ids | object_ids


def _prune_manual_import_entities(db: Session, *, tenant_id: UUID, import_id: str) -> int:
    candidate_ids = _manual_import_candidate_entity_ids(db, tenant_id=tenant_id, import_id=import_id)
    if not candidate_ids:
        return 0

    linked_entity_ids = _linked_manual_entity_ids(db, candidate_ids)
    prune_ids = [entity_id for entity_id in candidate_ids if entity_id not in linked_entity_ids]
    if not prune_ids:
        return 0

    _delete_manual_import_vectors(db=db, event_ids=[], entity_ids=prune_ids)
    db.query(KgEntityAlias).filter(KgEntityAlias.canonical_entity_id.in_(prune_ids)).delete(synchronize_session=False)
    return int(
        db.query(KgEntity)
        .filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(prune_ids))
        .delete(synchronize_session=False)
        or 0
    )


def _delete_import_rows(
    db: Session,
    *,
    tenant_id: UUID,
    import_id: str,
    document: Document,
    prune_entities: bool = True,
) -> KGManualImportDeleteResponse:
    pipeline_hash = _document_pipeline_hash(document)
    rel_q = _document_relations_query(db, tenant_id=tenant_id, document=document, pipeline_hash=pipeline_hash)
    relations_deleted = rel_q.delete(synchronize_session=False)

    event_q = _document_events_query(db, tenant_id=tenant_id, document=document, pipeline_hash=pipeline_hash)
    event_ids = [row[0] for row in event_q.with_entities(KgSourceEvent.id).all() if row and row[0]]
    _delete_manual_import_vectors(db=db, event_ids=event_ids, entity_ids=[])
    events_deleted = event_q.delete(synchronize_session=False)

    chunks_deleted = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document.id)
        .delete(synchronize_session=False)
    )

    entities_pruned = (
        _prune_manual_import_entities(db, tenant_id=tenant_id, import_id=import_id) if prune_entities else 0
    )

    db.delete(document)
    return KGManualImportDeleteResponse(
        import_id=import_id,
        document_id=document.id,
        events_deleted=int(events_deleted or 0),
        relations_deleted=int(relations_deleted or 0),
        chunks_deleted=int(chunks_deleted or 0),
        entities_pruned=int(entities_pruned or 0),
    )


def delete_manual_import(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    import_id: str,
    prune_entities: bool = True,
) -> KGManualImportDeleteResponse:
    document = _find_import_document(db, tenant_id=tenant_id, import_id=import_id)
    if not document:
        raise HTTPException(status_code=404, detail="Manual KG import not found")
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
    out = _delete_import_rows(
        db, tenant_id=tenant_id, import_id=import_id, document=document, prune_entities=prune_entities
    )
    db.commit()
    return out


def _get_or_create_entity(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    import_id: str,
    row: _EntityRow,
    allow_label_truncation: bool,
    upsert_entities: bool,
) -> tuple[KgEntity, bool]:
    display_name, compact_meta = _compact_entity_label(row.name, allow=allow_label_truncation)
    display_normalized = _normalized_key(display_name)[:ENTITY_NAME_MAX]
    full_normalized = _normalized_key(row.name)

    if upsert_entities:
        existing = (
            db.query(KgEntity)
            .filter(
                KgEntity.tenant_id == tenant_id,
                KgEntity.type == row.type,
                KgEntity.normalized_name == display_normalized,
            )
            .first()
        )
        if existing:
            return existing, False

    entity_id = _stable_uuid("entity", f"{tenant_id}|{row.type}|{full_normalized}")
    existing = db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id == entity_id).first()
    if existing:
        return existing, False

    entity = KgEntity(
        id=entity_id,
        tenant_id=tenant_id,
        name=display_name,
        type=row.type,
        description=row.description,
        normalized_name=display_normalized,
        extra_data={
            **row.extra_data,
            **compact_meta,
            "manual_kg_import": True,
            "manual_kg_import_id": import_id,
            "manual_kg_created": True,
            "external_key": row.key,
            "created_by": account_id,
            "format": MANUAL_KG_FORMAT,
        },
    )
    db.add(entity)
    return entity, True


def _manual_event_embedding_text(event: KgSourceEvent) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in (getattr(event, "title", None), getattr(event, "summary", None), getattr(event, "content", None)):
        text = _norm(value)
        if text and text not in seen:
            parts.append(text)
            seen.add(text)
    return "\n".join(parts)


def _manual_entity_embedding_text(entity: KgEntity) -> str:
    parts: list[str] = []
    for value in (getattr(entity, "name", None), getattr(entity, "type", None), getattr(entity, "description", None)):
        text = _norm(value)
        if text:
            parts.append(text)
    extra = getattr(entity, "extra_data", None)
    if isinstance(extra, dict):
        full_value = _norm(extra.get("full_value"))
        if full_value and full_value not in parts:
            parts.append(full_value)
    return "\n".join(parts)


def _initial_manual_vector_status() -> dict[str, Any]:
    return {
        "status": "skipped",
        "events_embedded": 0,
        "entities_embedded": 0,
        "event_vectors": 0,
        "entity_vectors": 0,
    }


def _collect_manual_embedding_jobs(
    *,
    events: list[KgSourceEvent],
    entities: list[KgEntity],
    event_enabled: bool,
    entity_enabled: bool,
) -> list[EmbeddingJob]:
    jobs: list[EmbeddingJob] = []
    if event_enabled:
        for event in events:
            text = "" if getattr(event, "content_vector", None) else _manual_event_embedding_text(event)
            if text:
                jobs.append(("event", event, "content_vector", text))
    if entity_enabled:
        for entity in entities:
            text = "" if getattr(entity, "vector", None) else _manual_entity_embedding_text(entity)
            if text:
                jobs.append(("entity", entity, "vector", text))
    return jobs


def _flush_if_supported(db: Session) -> None:
    flush = getattr(db, "flush", None)
    if callable(flush):
        flush()


def _embed_manual_vector_jobs(
    *,
    db: Session,
    indexer: Indexer,
    tenant_id: UUID,
    document: Document,
    jobs: list[EmbeddingJob],
    status: dict[str, Any],
) -> None:
    if not jobs:
        return
    runtime = indexer._embedding_runtime_for_document(tenant_id=tenant_id, document_id=document.id)
    embeddings = create_embeddings_for_runtime(runtime)
    vectors = embeddings.embed_documents([text for _kind, _row, _attr, text in jobs])
    for (kind, row, attr, _text), vector in zip(jobs, vectors, strict=False):
        setattr(row, attr, list(vector))
        counter = "events_embedded" if kind == "event" else "entities_embedded"
        status[counter] += 1
    _flush_if_supported(db)


def _index_manual_vector_candidates(
    *,
    indexer: Indexer,
    events: list[KgSourceEvent],
    entities: list[KgEntity],
    event_enabled: bool,
    entity_enabled: bool,
) -> tuple[list[str], list[str], int]:
    event_candidates = [event for event in events if getattr(event, "content_vector", None)]
    entity_candidates = [entity for entity in entities if getattr(entity, "vector", None)]
    event_vector_ids = indexer._index_event_vectors(event_candidates) if event_enabled and event_candidates else []
    entity_vector_ids = indexer._index_entity_vectors(entity_candidates) if entity_enabled and entity_candidates else []
    return event_vector_ids, entity_vector_ids, len(event_candidates) + len(entity_candidates)


def _set_manual_vector_status(status: dict[str, Any], *, expected_vectors: int, stored_vectors: int) -> None:
    if expected_vectors == 0:
        status["status"] = "skipped"
        status["reason"] = "no_vector_candidates"
    elif stored_vectors == expected_vectors:
        status["status"] = "indexed"
    elif stored_vectors > 0:
        status["status"] = "partial"
        status["reason"] = "vector_store_returned_fewer_ids"
    else:
        status["status"] = "failed"
        status["reason"] = "vector_store_returned_no_ids"


def _index_manual_import_vectors(
    *,
    db: Session,
    tenant_id: UUID,
    document: Document,
    events: list[KgSourceEvent],
    entities: list[KgEntity],
    enabled: bool,
) -> dict[str, Any]:
    status = _initial_manual_vector_status()
    if not enabled:
        status["reason"] = "disabled_by_request"
        return status

    try:
        indexer = Indexer(db)
        event_enabled = indexer._resolve_event_vector_enabled(None)
        entity_enabled = indexer._resolve_entity_vector_enabled(None)
        if not event_enabled and not entity_enabled:
            status["reason"] = "disabled_by_settings"
            return status

        embedding_jobs = _collect_manual_embedding_jobs(
            events=events,
            entities=entities,
            event_enabled=event_enabled,
            entity_enabled=entity_enabled,
        )
        _embed_manual_vector_jobs(
            db=db,
            indexer=indexer,
            tenant_id=tenant_id,
            document=document,
            jobs=embedding_jobs,
            status=status,
        )
        event_vector_ids, entity_vector_ids, expected_vectors = _index_manual_vector_candidates(
            indexer=indexer,
            events=events,
            entities=entities,
            event_enabled=event_enabled,
            entity_enabled=entity_enabled,
        )

        status["event_vectors"] = len(event_vector_ids)
        status["entity_vectors"] = len(entity_vector_ids)
        stored_vectors = len(event_vector_ids) + len(entity_vector_ids)
        _set_manual_vector_status(status, expected_vectors=expected_vectors, stored_vectors=stored_vectors)
        return status
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Manual KG vector indexing failed document=%s: %s", getattr(document, "id", None), str(exc)[:300]
        )
        status["status"] = "failed"
        status["error"] = str(exc)[:500]
        return status


def _delete_manual_import_vectors(
    *,
    db: Session,
    event_ids: list[UUID],
    entity_ids: list[UUID],
) -> None:
    if not event_ids and not entity_ids:
        return
    try:
        indexer = Indexer(db)
        if event_ids:
            indexer._event_vector.delete([str(event_id) for event_id in event_ids])
        if entity_ids:
            indexer._entity_vector.delete([str(entity_id) for entity_id in entity_ids])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete manual KG vectors: %s", str(exc)[:300])


def _create_document(
    db: Session,
    *,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    normalized: _NormalizedImport,
) -> Document:
    document_id = _stable_uuid("document", f"{tenant_id}|{normalized.import_id}|{normalized.pipeline_hash}")
    filename = f"{normalized.name}.manual-kg.json"
    meta = {
        "manual_kg_import": True,
        "manual_kg_import_id": normalized.import_id,
        "active_pipeline_hash": normalized.pipeline_hash,
        "pipeline_hash": normalized.pipeline_hash,
        "format": MANUAL_KG_FORMAT,
        "import_name": normalized.name,
        "import_stats": normalized.stats().model_dump(),
    }
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=filename[:500],
        file_type="json",
        file_size=0,
        file_path=f"manual-kg://{normalized.import_id}",
        owner_id=account_id,
        access_mode="all_team_members",
        publication_status="published",
        status="completed",
        processing_progress=100,
        current_stage="completed",
        chunk_count=0,
        total_characters=0,
        doc_metadata=meta,
        processed_at=datetime.now(timezone.utc),
    )
    db.add(document)
    return document


def _trim_entity_value(value: str) -> str:
    return value[:ENTITY_NAME_MAX]


def _add_entity_alias(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    import_id: str,
    entity: KgEntity,
    alias: str,
) -> bool:
    alias_norm = _normalized_key(alias)
    if not alias_norm:
        return False

    alias_key = _trim_entity_value(alias_norm)
    exists = (
        db.query(KgEntityAlias.id)
        .filter(
            KgEntityAlias.tenant_id == tenant_id,
            KgEntityAlias.canonical_entity_id == entity.id,
            KgEntityAlias.normalized_alias == alias_key,
        )
        .first()
    )
    if exists:
        return False

    db.add(
        KgEntityAlias(
            id=_stable_uuid("alias", f"{tenant_id}|{entity.id}|{alias_norm}"),
            tenant_id=tenant_id,
            canonical_entity_id=entity.id,
            alias=_trim_entity_value(alias),
            normalized_alias=alias_key,
            created_by=account_id,
            extra_data={"manual_kg_import_id": import_id, "format": MANUAL_KG_FORMAT},
        )
    )
    return True


def _insert_manual_entities(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    normalized: _NormalizedImport,
    payload: KGManualImportRequest,
) -> _EntityInsertResult:
    result = _EntityInsertResult(entity_by_key={})
    for row in normalized.entities:
        try:
            entity, created = _get_or_create_entity(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                import_id=normalized.import_id,
                row=row,
                allow_label_truncation=payload.allow_label_truncation,
                upsert_entities=payload.upsert_entities,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid entity row {row.row}: {exc}") from exc

        result.entity_by_key[row.key] = entity
        result.inserted_entities += int(created)
        result.inserted_aliases += sum(
            int(
                _add_entity_alias(
                    db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    import_id=normalized.import_id,
                    entity=entity,
                    alias=alias,
                )
            )
            for alias in row.aliases
        )
    db.flush()
    return result


def _add_manual_event(
    db: Session,
    *,
    tenant_id: UUID,
    document: Document,
    normalized: _NormalizedImport,
    state: _ManualImportWriteState,
    key: str,
    title: str,
    summary: str,
    content: str,
    refs: dict[str, Any],
    extra: dict[str, Any],
) -> KgSourceEvent:
    chunk_id = _stable_uuid("chunk", f"{document.id}|{key}")
    content_text = content or summary or title
    db.add(
        DocumentChunk(
            id=chunk_id,
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=state.chunk_index,
            content=content_text,
            start_char=0,
            end_char=len(content_text),
            doc_metadata={
                "manual_kg_import": True,
                "manual_kg_import_id": normalized.import_id,
                "pipeline_hash": normalized.pipeline_hash,
                **refs,
            },
        )
    )
    event = KgSourceEvent(
        id=_stable_uuid("event", f"{tenant_id}|{normalized.import_id}|{key}"),
        tenant_id=tenant_id,
        pipeline_hash=normalized.pipeline_hash,
        document_id=document.id,
        chunk_id=chunk_id,
        title=title[:255] or normalized.name,
        summary=summary,
        content=content_text,
        references={
            "manual_kg_import_id": normalized.import_id,
            "pipeline_hash": normalized.pipeline_hash,
            **refs,
        },
        extra_data={
            "manual_kg_import": True,
            "manual_kg_import_id": normalized.import_id,
            "format": MANUAL_KG_FORMAT,
            **extra,
        },
    )
    db.add(event)
    state.imported_events.append(event)
    state.chunk_index += 1
    state.inserted_events += 1
    return event


def _add_event_entity_link(
    db: Session,
    *,
    normalized: _NormalizedImport,
    document: Document,
    event: KgSourceEvent,
    entity: KgEntity,
    role: str,
    weight: float,
    refs: dict[str, Any] | None = None,
) -> None:
    db.add(
        KgEventEntity(
            id=_stable_uuid("event_entity", f"{event.id}|{entity.id}|{role}"),
            event_id=event.id,
            entity_id=entity.id,
            weight=weight,
            role=role,
            extra_data={
                "manual_kg_import_id": normalized.import_id,
                "document_id": str(document.id),
                "chunk_id": str(event.chunk_id),
                **(refs or {}),
            },
        )
    )


def _insert_manual_relations(
    db: Session,
    *,
    tenant_id: UUID,
    document: Document,
    normalized: _NormalizedImport,
    entity_by_key: dict[str, KgEntity],
    state: _ManualImportWriteState,
) -> tuple[int, set[str]]:
    inserted_relations = 0
    touched_entity_keys: set[str] = set()
    for idx, rel in enumerate(normalized.relations, 1):
        subj = entity_by_key[rel.subject_key]
        obj = entity_by_key[rel.object_key]
        touched_entity_keys.update({rel.subject_key, rel.object_key})
        refs = {**rel.references, "source": rel.source, "relation_row": rel.row}
        content = rel.evidence or f"{subj.name} --{rel.predicate}--> {obj.name}"
        event = _add_manual_event(
            db,
            tenant_id=tenant_id,
            document=document,
            normalized=normalized,
            state=state,
            key=f"relation:{idx}",
            title=f"{subj.name} {rel.predicate} {obj.name}",
            summary=content[:1000],
            content=content,
            refs=refs,
            extra={"event_kind": "manual_relation", **rel.extra_data},
        )
        for entity, role in ((subj, "subject"), (obj, "object")):
            _add_event_entity_link(
                db,
                normalized=normalized,
                document=document,
                event=event,
                entity=entity,
                role=role,
                weight=1.0,
                refs=refs,
            )
            state.inserted_links += 1
        db.add(
            KgRelation(
                id=_stable_uuid(
                    "relation", f"{tenant_id}|{normalized.import_id}|{idx}|{subj.id}|{rel.predicate}|{obj.id}"
                ),
                tenant_id=tenant_id,
                pipeline_hash=normalized.pipeline_hash,
                document_id=document.id,
                chunk_id=event.chunk_id,
                event_id=event.id,
                subject_entity_id=subj.id,
                predicate=rel.predicate,
                predicate_raw=rel.predicate,
                object_entity_id=obj.id,
                confidence=rel.confidence,
                qualifiers=rel.qualifiers,
                references=refs,
                extra_data={
                    "manual_kg_import": True,
                    "manual_kg_import_id": normalized.import_id,
                    "format": MANUAL_KG_FORMAT,
                    **rel.extra_data,
                },
            )
        )
        inserted_relations += 1
    return inserted_relations, touched_entity_keys


def _insert_entity_registry_events(
    db: Session,
    *,
    tenant_id: UUID,
    document: Document,
    normalized: _NormalizedImport,
    entity_by_key: dict[str, KgEntity],
    touched_entity_keys: set[str],
    state: _ManualImportWriteState,
) -> None:
    isolated = [row for row in normalized.entities if row.key not in touched_entity_keys]
    for batch_index in range(0, len(isolated), REGISTRY_EVENT_ENTITY_BATCH):
        batch = isolated[batch_index : batch_index + REGISTRY_EVENT_ENTITY_BATCH]
        batch_number = batch_index // REGISTRY_EVENT_ENTITY_BATCH
        event = _add_manual_event(
            db,
            tenant_id=tenant_id,
            document=document,
            normalized=normalized,
            state=state,
            key=f"entity_registry:{batch_number}",
            title=f"{normalized.name} · 实体登记",
            summary=f"人工导入实体登记：{len(batch)} 个孤立实体",
            content="\n".join(f"{row.type}: {row.name}" for row in batch),
            refs={"entity_registry_batch": batch_number},
            extra={"event_kind": "manual_entity_registry"},
        )
        for row in batch:
            entity = entity_by_key[row.key]
            _add_event_entity_link(
                db, normalized=normalized, document=document, event=event, entity=entity, role="registry", weight=0.8
            )
            state.inserted_links += 1


def _document_content_size(db: Session, *, tenant_id: UUID, document: Document) -> int:
    return int(
        db.query(func.coalesce(func.sum(func.length(DocumentChunk.content)), 0))
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document.id)
        .scalar()
        or 0
    )


def _finalize_manual_import_document(
    db: Session,
    *,
    tenant_id: UUID,
    document: Document,
    normalized: _NormalizedImport,
    state: _ManualImportWriteState,
    entity_result: _EntityInsertResult,
    inserted_relations: int,
) -> dict[str, int]:
    total_chars = _document_content_size(db, tenant_id=tenant_id, document=document)
    document.chunk_count = int(state.chunk_index)
    document.total_characters = total_chars
    document.file_size = total_chars
    inserted = {
        "entities": entity_result.inserted_entities,
        "aliases": entity_result.inserted_aliases,
        "events": state.inserted_events,
        "event_entity_links": state.inserted_links,
        "relations": inserted_relations,
    }
    meta = dict(document.doc_metadata or {})
    meta["import_stats"] = normalized.stats().model_dump()
    meta["inserted"] = inserted
    document.doc_metadata = meta
    return inserted


def _unique_import_entities(entity_by_key: dict[str, KgEntity]) -> list[KgEntity]:
    return list({str(entity.id): entity for entity in entity_by_key.values()}.values())


def _commit_and_index_manual_import(
    db: Session,
    *,
    tenant_id: UUID,
    document: Document,
    payload: KGManualImportRequest,
    state: _ManualImportWriteState,
    entity_by_key: dict[str, KgEntity],
) -> tuple[dict[str, int], dict[str, Any]]:
    db.commit()
    vector_status = _index_manual_import_vectors(
        db=db,
        tenant_id=tenant_id,
        document=document,
        events=state.imported_events,
        entities=_unique_import_entities(entity_by_key),
        enabled=payload.index_vectors,
    )
    meta = dict(document.doc_metadata or {})
    inserted = dict(meta.get("inserted") or {})
    inserted["event_vectors"] = int(vector_status.get("event_vectors") or 0)
    inserted["entity_vectors"] = int(vector_status.get("entity_vectors") or 0)
    meta["inserted"] = inserted
    meta["vector_index"] = vector_status
    document.doc_metadata = meta
    db.commit()
    return inserted, vector_status


def apply_manual_import(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    payload: KGManualImportRequest,
) -> KGManualImportResponse:
    normalized = normalize_manual_import(payload)
    if not normalized.valid:
        return KGManualImportResponse(
            import_id=normalized.import_id,
            pipeline_hash=normalized.pipeline_hash,
            name=normalized.name,
            valid=False,
            stats=normalized.stats(),
            issues=normalized.issues[:200],
            inserted={},
            message="Manual KG import validation failed",
        )

    existing_doc = _find_import_document(db, tenant_id=tenant_id, import_id=normalized.import_id)
    if existing_doc and not payload.replace_existing:
        raise HTTPException(
            status_code=409, detail="Manual KG import_id already exists. Use replace_existing=true to replace it."
        )

    dataset = _ensure_import_dataset(db=db, tenant_id=tenant_id, account_id=account_id, payload=payload)
    if existing_doc:
        _delete_import_rows(
            db, tenant_id=tenant_id, import_id=normalized.import_id, document=existing_doc, prune_entities=True
        )
        db.flush()

    document = _create_document(
        db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        normalized=normalized,
    )

    entity_result = _insert_manual_entities(
        db, tenant_id=tenant_id, account_id=account_id, normalized=normalized, payload=payload
    )
    write_state = _ManualImportWriteState()
    inserted_relations, touched_entity_keys = _insert_manual_relations(
        db,
        tenant_id=tenant_id,
        document=document,
        normalized=normalized,
        entity_by_key=entity_result.entity_by_key,
        state=write_state,
    )
    _insert_entity_registry_events(
        db,
        tenant_id=tenant_id,
        document=document,
        normalized=normalized,
        entity_by_key=entity_result.entity_by_key,
        touched_entity_keys=touched_entity_keys,
        state=write_state,
    )
    _finalize_manual_import_document(
        db,
        tenant_id=tenant_id,
        document=document,
        normalized=normalized,
        state=write_state,
        entity_result=entity_result,
        inserted_relations=inserted_relations,
    )
    inserted, vector_status = _commit_and_index_manual_import(
        db,
        tenant_id=tenant_id,
        document=document,
        payload=payload,
        state=write_state,
        entity_by_key=entity_result.entity_by_key,
    )

    return KGManualImportResponse(
        import_id=normalized.import_id,
        pipeline_hash=normalized.pipeline_hash,
        name=normalized.name,
        valid=True,
        dataset_id=dataset.id,
        document_id=document.id,
        stats=normalized.stats(),
        issues=normalized.issues[:200],
        inserted=inserted,
        vector_index=vector_status,
    )


def list_manual_imports(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    limit: int = 50,
) -> KGManualImportListResponse:
    # Restrict through existing document access trimming by checking datasets.
    rows = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.doc_metadata.op("->>")("manual_kg_import") == "true",
        )
        .order_by(Document.updated_at.desc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    items: list[KGManualImportListItem] = []
    for doc in rows:
        if doc.dataset_id:
            dataset = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == doc.dataset_id).first()
            if not dataset or not DatasetService.check_dataset_permission(db, dataset, account_id):
                continue
        meta = doc.doc_metadata or {}
        items.append(
            KGManualImportListItem(
                import_id=str(meta.get("manual_kg_import_id") or ""),
                name=str(meta.get("import_name") or doc.filename),
                pipeline_hash=str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or ""),
                dataset_id=doc.dataset_id,
                document_id=doc.id,
                stats=_json_dict(meta.get("import_stats")),
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
        )
    return KGManualImportListResponse(items=items)
