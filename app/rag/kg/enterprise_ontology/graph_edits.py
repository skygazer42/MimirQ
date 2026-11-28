"""Review a document's graph for its knowledge base's active ontology."""

import json
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.knowledge_graph import (
    OntologyDocumentGraph,
    OntologyGraphChanges,
    OntologyGraphChunk,
    OntologyGraphEditRequest,
)
from app.models.datasets.records import Dataset
from app.rag.kg.enterprise_ontology.activation import active_version_id, published_version
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, validate_ontology_relation
from app.rag.kg.enterprise_ontology.documents import (
    ManualGraph,
    content_hash,
    load_document_chunks,
    read_evidence_row,
    span_matches,
    stored_previews,
    visible_chunk,
)
from app.rag.kg.enterprise_ontology.metadata import GroundedValue, parse_source_value
from app.rag.kg.enterprise_ontology.preview import (
    ChunkPreview,
    mentions,
    supports_mention,
    validate_cardinality,
)
from app.rag.kg.extraction.evidence import normalize_surface_for_match
from app.services.datasets.management import assert_dataset_readable, assert_dataset_writable, get_dataset
from app.services.observability.audit_log import audit_log_event


def _can_edit(db: Session, dataset: Dataset, account_id: str) -> bool:
    try:
        assert_dataset_writable(db, dataset, account_id)
    except HTTPException as exc:
        if exc.status_code not in {401, 403}:
            raise
        return False
    return True


def _checked_graph(
    graph: OntologyGraphChanges,
    current: ChunkPreview,
    definition: OntologyDefinition,
    source: str,
) -> OntologyGraphChanges:
    entities = {}
    originals = {item.id: item for item in current.entities}
    names = Counter((item.object_type, normalize_surface_for_match(item.name)) for item in graph.entities)
    for entity in graph.entities:
        obj = definition.object_types.get(entity.object_type)
        if not entity.id.strip() or len(entity.id) > 64 or entity.id in entities:
            raise ValueError("实体标识须唯一")
        if obj is None or not entity.name.strip() or len(entity.name) > 255:
            raise ValueError("请填写实体名称并选择已发布的对象类型")
        if not span_matches(source, entity.evidence) or not mentions(entity.evidence.quote, entity.name):
            raise ValueError(f"实体「{entity.name}」的原文区间须包含名称")
        original = originals.get(entity.id)
        same_name = names[entity.object_type, normalize_surface_for_match(entity.name)] > 1
        attributes = {}
        for name, values in entity.attributes.items():
            field = obj.properties.get(name)
            if field is None:
                raise ValueError(f"对象「{entity.name}」没有属性 {name}")
            verified = []
            for item in values:
                if item.value_type != field.type or not span_matches(source, item.evidence):
                    raise ValueError(f"请为属性 {name} 选择匹配的值类型和原文")
                if (
                    original is not None
                    and original.object_type == entity.object_type
                    and original.name == entity.name
                    and original.evidence == entity.evidence
                    and item in original.attributes.get(name, [])
                ):
                    verified.append(item)
                    continue
                value = parse_source_value(field, str(item.value))
                value_anchored = mentions(item.evidence.quote, str(item.value))
                if not value_anchored:
                    try:
                        value_anchored = parse_source_value(field, item.evidence.quote) == value
                    except ValueError:
                        pass
                if not value_anchored or not supports_mention(item.evidence, entity, ambiguous=same_name):
                    raise ValueError(f"属性 {name} 的值须来自选中的原文")
                verified.append(GroundedValue(value=value, value_type=field.type, evidence=item.evidence))
            if (
                not field.multiple
                and len({item.value for item in verified}) > 1
                and (original is None or verified != original.attributes.get(name))
            ):
                raise ValueError(f"属性 {name} 只能保存一个值")
            attributes[name] = verified
        entities[entity.id] = entity.model_copy(
            update={"name": entity.name.strip(), "key_fields": obj.key, "attributes": attributes}
        )
    for relation in graph.relations:
        start, end = entities.get(relation.subject_id), entities.get(relation.object_id)
        if (
            start is None
            or end is None
            or validate_ontology_relation(
                definition,
                relation.predicate,
                start.object_type,
                end.object_type,
            )
        ):
            raise ValueError("关系的起点、终点和方向须符合已发布的本体")
        if not span_matches(source, relation.evidence) or not all(
            supports_mention(
                relation.evidence,
                item,
                ambiguous=names[item.object_type, normalize_surface_for_match(item.name)] > 1,
            )
            for item in (start, end)
        ):
            raise ValueError("关系的原文区间须包含两端实体")
    checked = current.model_copy(
        update={"entities": list(entities.values()), "relations": graph.relations, "rejected": []}
    )
    validate_cardinality(checked, definition)
    if checked.rejected:
        raise ValueError("关系数量超出本体定义的基数")
    return OntologyGraphChanges(entities=checked.entities, relations=checked.relations)


def document_graph(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    document_id: UUID,
    chunk_id: UUID | None = None,
    edit: OntologyGraphEditRequest | None = None,
) -> OntologyDocumentGraph:
    if edit is not None:
        locked = db.scalar(
            select(Dataset.id).where(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).with_for_update()
        )
        if locked is None:
            raise HTTPException(status_code=404, detail="知识库不存在")
    dataset = get_dataset(db, tenant_id, dataset_id)
    assert_dataset_readable(db, dataset, account_id)
    can_edit = _can_edit(db, dataset, account_id)
    if edit is not None and not can_edit:
        raise HTTPException(status_code=403, detail="需要知识库编辑权限")
    version_id = active_version_id(db, tenant_id, dataset_id)
    if edit is not None and edit.version_id != version_id:
        raise HTTPException(status_code=409, detail="知识库本体版本已切换，请重新加载")
    version = published_version(db, tenant_id, version_id) if version_id else None
    if version is None:
        raise HTTPException(status_code=404, detail="知识库还没有激活本体")
    document, pipeline, chunks = load_document_chunks(db, tenant_id, account_id, document_id, lock=edit is not None)
    if document.dataset_id != dataset_id or document.archived_at is not None:
        raise HTTPException(status_code=404, detail="文档不在当前知识库范围内")
    row = read_evidence_row(db, document, version.id, pipeline, refresh=edit is not None)
    stored = stored_previews(row)
    by_id = {item.chunk_id: item for item in stored if item.document_id == document_id}
    candidates = [chunk for chunk in chunks if chunk.id in by_id]
    if not candidates:
        raise HTTPException(status_code=404, detail="当前文档没有本体证据")
    if chunk_id is None:
        chunk = next(
            (item for item in candidates if by_id[item.id].entities or by_id[item.id].manual_graph), candidates[0]
        )
    else:
        chunk = next((item for item in candidates if item.id == chunk_id), None)
        if chunk is None:
            raise HTTPException(status_code=404, detail="分块已变更，请重新选择")
    preview = by_id[chunk.id]
    digest = content_hash(chunk.content)
    preview_graph = visible_chunk(preview, chunk)
    definition = OntologyDefinition.model_validate(version.definition)

    def revision() -> str:
        payload = {
            "pipeline_hash": pipeline,
            "source": digest,
            "entities": [item.model_dump(mode="json") for item in preview_graph.entities],
            "relations": [item.model_dump(mode="json") for item in preview_graph.relations],
            "edited_at": preview.manual_graph.edited_at.isoformat() if preview.manual_graph is not None else None,
        }
        return content_hash(json.dumps(payload, sort_keys=True))

    if edit is not None:
        if edit.expected_revision != revision():
            raise HTTPException(status_code=409, detail="图谱或原文已更新，请重新加载后再保存")
        preview.manual_graph = None
        if edit.graph is not None:
            graph = _checked_graph(edit.graph, preview_graph, definition, chunk.content)
            preview.manual_graph = ManualGraph(
                content_hash=digest,
                edited_by=account_id,
                edited_at=datetime.now(UTC),
                entities=graph.entities,
                relations=graph.relations,
            )
        row.chunks = [item.model_dump(mode="json") for item in stored]
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="kg.ontology.graph.correct",
            resource_type="document",
            resource_id=str(document_id),
            details={"version_id": str(version.id), "chunk_id": str(chunk.id), "reset": edit.graph is None},
        )
        db.commit()
        preview_graph = visible_chunk(preview, chunk)
    return OntologyDocumentGraph(
        version_id=version.id,
        version_number=version.number,
        pipeline_hash=pipeline,
        revision=revision(),
        can_edit=can_edit,
        corrected=preview.manual_graph is not None and preview.manual_graph.content_hash == digest,
        chunks=[OntologyGraphChunk(id=item.id, page=item.page_number, index=item.chunk_index) for item in candidates],
        chunk=preview_graph,
        source_text=chunk.content,
        object_types=definition.object_types,
        relations=definition.relations,
    )
