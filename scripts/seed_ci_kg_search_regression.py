#!/usr/bin/env python3
"""
Seed a tiny deterministic dataset + documents/chunks + KG rows for the KG-search regression gate.

Design goals (CI-friendly):
- No background queue required.
- No Milvus required.
- No embeddings/LLM required (KG_SEARCH_VECTOR_RECALL_ENABLED=false is expected in CI).

It also exports a portable regression cases bundle (mimirq.regression_cases.v1) which can be
imported via the existing regression-case import API.
"""

# The script must make the repository importable before loading app modules.
# ruff: noqa: E402

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# import app.models._all  # noqa: F401
Base = None
SessionLocal = None
engine = None
apply_runtime_migrations = None
Dataset = None
DatasetPermissionEnum = None
DBDocument = None
DocumentChunk = None
KgEntity = None
KgEntityAlias = None
KgEventEntity = None
KgRelation = None
KgSourceEvent = None
Tenant = None
TenantMember = None


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_file(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_cases_bundle(fixture: dict[str, Any]) -> dict[str, Any]:
    ds = str((fixture.get("dataset") or {}).get("id") or "").strip()
    if not ds:
        raise ValueError("fixture.dataset.id is required")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixture.cases must be a non-empty list")

    items: list[dict[str, Any]] = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        q = str(c.get("question") or "").strip()
        if not q:
            continue
        ref = c.get("reference_sources") or []
        if not isinstance(ref, list) or not ref:
            raise ValueError("each case must include reference_sources[]")
        items.append(
            {
                "question": q,
                "expected_answer": c.get("expected_answer"),
                "reference_sources": ref,
                "tags": list(c.get("tags") or []),
            }
        )

    if not items:
        raise ValueError("fixture produced zero case items")

    return {"schema": "mimirq.regression_cases.v1", "dataset_id": ds, "items": items}


def _ensure_app_imports() -> None:
    global Base, SessionLocal, engine, apply_runtime_migrations
    global Dataset, DatasetPermissionEnum, DBDocument, DocumentChunk
    global KgEntity, KgEntityAlias, KgEventEntity, KgRelation, KgSourceEvent
    global Tenant, TenantMember

    if Base is not None:
        return

    importlib.import_module("app.models._all")
    Base = importlib.import_module("app.core.database").Base
    SessionLocal = importlib.import_module("app.core.database").SessionLocal
    engine = importlib.import_module("app.core.database").engine
    apply_runtime_migrations = importlib.import_module("app.core.migrations").apply_runtime_migrations
    dataset_module = importlib.import_module("app.models.dataset")
    Dataset = dataset_module.Dataset
    DatasetPermissionEnum = dataset_module.DatasetPermissionEnum
    document_module = importlib.import_module("app.models.document")
    DBDocument = document_module.Document
    DocumentChunk = document_module.DocumentChunk
    tenant_module = importlib.import_module("app.models.tenant")
    Tenant = tenant_module.Tenant
    TenantMember = tenant_module.TenantMember
    kg_models = importlib.import_module("app.rag.kg.models")
    KgEntity = kg_models.KgEntity
    KgEntityAlias = kg_models.KgEntityAlias
    KgEventEntity = kg_models.KgEventEntity
    KgRelation = kg_models.KgRelation
    KgSourceEvent = kg_models.KgSourceEvent


def _normalize_name(text: str) -> str:
    from app.rag.kg.extraction.parser import EntityValueParser

    return EntityValueParser().normalize_name(text)


def _normalize_type(text: str) -> str:
    from app.rag.kg.extraction.parser import EntityValueParser

    return EntityValueParser().normalize_type(text)


def _kg_section_list(kg: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = kg.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def ensure_fixture_tenant_owner(db: Any, *, tenant_id: UUID, account_id: str) -> None:
    """Create the explicit CI tenant membership required by authenticated APIs."""
    _ensure_app_imports()

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        tenant = Tenant(
            id=tenant_id,
            name=f"CI KG Search Regression {str(tenant_id)[:8]}",
            status="active",
            plan="basic",
        )
        db.add(tenant)

    member = (
        db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == account_id).first()
    )
    if member is None:
        member = TenantMember(
            tenant_id=tenant_id,
            user_id=account_id,
            role="owner",
            is_active=True,
            is_current=True,
        )
        db.add(member)
    else:
        member.role = "owner"
        member.is_active = True
        member.is_current = True


def _row_uuid_list(rows: list[dict[str, Any]]) -> list[UUID]:
    return [UUID(str(row.get("id"))) for row in rows if row.get("id")]


def _delete_filtered_rows(*, db: Any, model: Any, tenant_id: UUID, filters: list[Any]) -> None:
    if not filters:
        return
    from sqlalchemy import or_

    db.query(model).filter(model.tenant_id == tenant_id).filter(or_(*filters)).delete(synchronize_session=False)


def _relation_delete_filters(
    *,
    entity_ids: list[UUID],
    event_ids: list[UUID],
    relation_ids: list[UUID],
) -> list[Any]:
    filters: list[Any] = []
    if relation_ids:
        filters.append(KgRelation.id.in_(relation_ids))
    if event_ids:
        filters.append(KgRelation.event_id.in_(event_ids))
    if entity_ids:
        filters.append(KgRelation.subject_entity_id.in_(entity_ids))
        filters.append(KgRelation.object_entity_id.in_(entity_ids))
    return filters


def _alias_delete_filters(*, entity_ids: list[UUID], alias_ids: list[UUID]) -> list[Any]:
    filters: list[Any] = []
    if alias_ids:
        filters.append(KgEntityAlias.id.in_(alias_ids))
    if entity_ids:
        filters.append(KgEntityAlias.canonical_entity_id.in_(entity_ids))
    return filters


def _delete_kg_rows(
    *,
    db: Any,
    tenant_id: UUID,
    entity_ids: list[UUID],
    alias_ids: list[UUID],
    event_ids: list[UUID],
    link_ids: list[UUID],
    relation_ids: list[UUID],
) -> None:
    if event_ids:
        db.query(KgEventEntity).filter(KgEventEntity.event_id.in_(event_ids)).delete(synchronize_session=False)
    if link_ids:
        db.query(KgEventEntity).filter(KgEventEntity.id.in_(link_ids)).delete(synchronize_session=False)
    _delete_filtered_rows(
        db=db,
        model=KgRelation,
        tenant_id=tenant_id,
        filters=_relation_delete_filters(
            entity_ids=entity_ids,
            event_ids=event_ids,
            relation_ids=relation_ids,
        ),
    )
    _delete_filtered_rows(
        db=db,
        model=KgEntityAlias,
        tenant_id=tenant_id,
        filters=_alias_delete_filters(entity_ids=entity_ids, alias_ids=alias_ids),
    )

    if event_ids:
        db.query(KgSourceEvent).filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.id.in_(event_ids)).delete(
            synchronize_session=False
        )
    if entity_ids:
        db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids)).delete(
            synchronize_session=False
        )


def _add_entities(*, db: Any, tenant_id: UUID, entities: list[dict[str, Any]]) -> None:
    for ent in entities:
        ent_id = UUID(str(ent.get("id") or "").strip())
        name = str(ent.get("name") or "").strip()
        if not name:
            raise ValueError("kg.entities[].name is required")
        type_raw = str(ent.get("type") or "").strip()
        db.add(
            KgEntity(
                id=ent_id,
                tenant_id=tenant_id,
                name=name,
                type=_normalize_type(type_raw) if type_raw else "unknown",
                normalized_name=str(ent.get("normalized_name") or "").strip() or _normalize_name(name),
                description=(str(ent.get("description") or "").strip() or None),
                vector=ent.get("vector"),
                extra_data=ent.get("extra_data") if isinstance(ent.get("extra_data"), dict) else None,
            )
        )


def _add_aliases(*, db: Any, tenant_id: UUID, account_id: str, aliases: list[dict[str, Any]]) -> None:
    for alias_row in aliases:
        alias = str(alias_row.get("alias") or "").strip()
        if not alias:
            raise ValueError("kg.aliases[].alias is required")
        db.add(
            KgEntityAlias(
                id=UUID(str(alias_row.get("id") or "").strip()),
                tenant_id=tenant_id,
                canonical_entity_id=UUID(str(alias_row.get("canonical_entity_id") or "").strip()),
                alias=alias,
                normalized_alias=str(alias_row.get("normalized_alias") or "").strip() or _normalize_name(alias),
                created_by=str(alias_row.get("created_by") or account_id or "").strip() or None,
                extra_data=alias_row.get("extra_data") if isinstance(alias_row.get("extra_data"), dict) else None,
            )
        )


def _add_events(*, db: Any, tenant_id: UUID, events: list[dict[str, Any]]) -> None:
    for event in events:
        title = str(event.get("title") or "").strip()
        summary = str(event.get("summary") or "").strip()
        content = str(event.get("content") or "").strip()
        if not title or not summary or not content:
            raise ValueError("kg.events[] requires title/summary/content")

        doc_id_raw = str(event.get("document_id") or "").strip()
        chunk_id_raw = str(event.get("chunk_id") or "").strip()
        db.add(
            KgSourceEvent(
                id=UUID(str(event.get("id") or "").strip()),
                tenant_id=tenant_id,
                pipeline_hash=str(event.get("pipeline_hash") or "").strip() or None,
                document_id=UUID(doc_id_raw) if doc_id_raw else None,
                chunk_id=UUID(chunk_id_raw) if chunk_id_raw else None,
                title=title,
                summary=summary,
                content=content,
                content_vector=event.get("content_vector"),
                references=event.get("references") if isinstance(event.get("references"), dict) else None,
                extra_data=event.get("extra_data") if isinstance(event.get("extra_data"), dict) else None,
            )
        )


def _add_event_links(*, db: Any, event_entities: list[dict[str, Any]]) -> None:
    for link in event_entities:
        db.add(
            KgEventEntity(
                id=UUID(str(link.get("id") or "").strip()),
                event_id=UUID(str(link.get("event_id") or "").strip()),
                entity_id=UUID(str(link.get("entity_id") or "").strip()),
                weight=float(link.get("weight", 1.0) or 1.0),
                role=str(link.get("role") or "").strip() or None,
                extra_data=link.get("extra_data") if isinstance(link.get("extra_data"), dict) else None,
            )
        )


def _add_relations(*, db: Any, tenant_id: UUID, relations: list[dict[str, Any]]) -> None:
    for relation in relations:
        doc_id = relation.get("document_id")
        chunk_id = relation.get("chunk_id")
        event_id = relation.get("event_id")
        db.add(
            KgRelation(
                id=UUID(str(relation.get("id") or "").strip()),
                tenant_id=tenant_id,
                pipeline_hash=str(relation.get("pipeline_hash") or "").strip() or None,
                document_id=UUID(str(doc_id)) if doc_id else None,
                chunk_id=UUID(str(chunk_id)) if chunk_id else None,
                event_id=UUID(str(event_id)) if event_id else None,
                subject_entity_id=UUID(str(relation.get("subject_entity_id") or "").strip()),
                predicate=str(relation.get("predicate") or "").strip() or "related_to",
                predicate_raw=str(relation.get("predicate_raw") or "").strip() or None,
                object_entity_id=UUID(str(relation.get("object_entity_id") or "").strip()),
                confidence=float(relation.get("confidence", 0.5) or 0.5),
                qualifiers=relation.get("qualifiers") if isinstance(relation.get("qualifiers"), dict) else None,
                references=relation.get("references") if isinstance(relation.get("references"), dict) else None,
                extra_data=relation.get("extra_data") if isinstance(relation.get("extra_data"), dict) else None,
            )
        )


def _seed_kg_rows(*, db, tenant_id: UUID, account_id: str, fixture: dict[str, Any]) -> None:
    _ensure_app_imports()
    kg = fixture.get("kg") if isinstance(fixture.get("kg"), dict) else {}
    if not kg:
        return

    entities = _kg_section_list(kg, "entities")
    aliases = _kg_section_list(kg, "aliases")
    events = _kg_section_list(kg, "events")
    event_entities = _kg_section_list(kg, "event_entities")
    relations = _kg_section_list(kg, "relations")
    _delete_kg_rows(
        db=db,
        tenant_id=tenant_id,
        entity_ids=_row_uuid_list(entities),
        alias_ids=_row_uuid_list(aliases),
        event_ids=_row_uuid_list(events),
        link_ids=_row_uuid_list(event_entities),
        relation_ids=_row_uuid_list(relations),
    )
    db.commit()
    _add_entities(db=db, tenant_id=tenant_id, entities=entities)
    _add_aliases(db=db, tenant_id=tenant_id, account_id=account_id, aliases=aliases)
    _add_events(db=db, tenant_id=tenant_id, events=events)
    _add_event_links(db=db, event_entities=event_entities)
    _add_relations(db=db, tenant_id=tenant_id, relations=relations)
    db.commit()


def _require_documents(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    documents = fixture.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("fixture.documents must be a non-empty list")
    return [doc for doc in documents if isinstance(doc, dict)]


def _ensure_schema_ready() -> None:
    _ensure_app_imports()
    apply_runtime_migrations(engine)
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)


def _upsert_dataset(
    *,
    db: Any,
    tenant_id: UUID,
    dataset_id: UUID,
    dataset_name: str,
    dataset_desc: str | None,
    account_id: str,
) -> None:
    dataset_row = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).first()
    if dataset_row is None:
        dataset_row = Dataset(
            id=dataset_id,
            tenant_id=tenant_id,
            name=dataset_name,
            description=dataset_desc,
            permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            owner_id=account_id,
            dataset_metadata={},
        )
        db.add(dataset_row)
    else:
        dataset_row.name = dataset_name
        dataset_row.description = dataset_desc
        dataset_row.owner_id = account_id
    db.commit()


def _document_total_chars(chunks: list[Any]) -> int:
    return sum(len(str(chunk.get("content") or "")) for chunk in chunks if isinstance(chunk, dict))


def _safe_page_number(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _chunk_metadata(*, dataset_id: UUID, filename: str, doc_id: UUID, doc_meta: dict[str, Any]) -> dict[str, Any]:
    chunk_meta: dict[str, Any] = {"dataset_id": str(dataset_id), "source": filename}
    for key in ("active_pipeline_hash", "pipeline_hash", "doc_pipeline_key"):
        if key in doc_meta and doc_meta.get(key) is not None:
            chunk_meta[key] = doc_meta.get(key)
    active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
    if active_hash:
        chunk_meta.setdefault("pipeline_hash", active_hash)
        chunk_meta.setdefault("doc_pipeline_key", f"{doc_id}:{active_hash}")
    return chunk_meta


def _upsert_document(
    *,
    db: Any,
    tenant_id: UUID,
    dataset_id: UUID,
    doc_id: UUID,
    filename: str,
    file_type: str,
    total_chars: int,
    chunks: list[Any],
    doc_meta: dict[str, Any],
) -> None:
    row = db.query(DBDocument).filter(DBDocument.id == doc_id, DBDocument.tenant_id == tenant_id).first()
    row_data = {
        "dataset_id": dataset_id,
        "filename": filename,
        "file_type": file_type,
        "file_size": int(total_chars),
        "file_path": f"ci://{filename}",
        "status": "completed",
        "chunk_count": len(chunks),
        "total_characters": int(total_chars),
        "doc_metadata": dict(doc_meta),
    }
    if row is None:
        db.add(DBDocument(id=doc_id, tenant_id=tenant_id, **row_data))
        return

    for key, value in row_data.items():
        setattr(row, key, value)
    row.error_message = None


def _replace_document_chunks(
    *,
    db: Any,
    tenant_id: UUID,
    dataset_id: UUID,
    doc_id: UUID,
    filename: str,
    doc_meta: dict[str, Any],
    chunks: list[Any],
) -> None:
    db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == doc_id).delete(
        synchronize_session=False
    )
    base_meta = _chunk_metadata(dataset_id=dataset_id, filename=filename, doc_id=doc_id, doc_meta=doc_meta)
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        db.add(
            DocumentChunk(
                id=UUID(str(chunk.get("id") or "").strip()),
                tenant_id=tenant_id,
                document_id=doc_id,
                chunk_index=int(chunk.get("chunk_index") or 0),
                content=str(chunk.get("content") or ""),
                page_number=_safe_page_number(chunk.get("page_number")),
                doc_metadata=dict(base_meta),
            )
        )


def seed_fixture(*, fixture: dict[str, Any]) -> None:
    tenant_id = UUID(str(fixture.get("tenant_id") or "").strip())
    account_id = str(fixture.get("account_id") or "").strip() or "ci-bot"
    ds_obj = fixture.get("dataset") if isinstance(fixture.get("dataset"), dict) else {}
    dataset_id = UUID(str(ds_obj.get("id") or "").strip())
    dataset_name = str(ds_obj.get("name") or "CI KG Search Regression Fixture").strip()
    dataset_desc = str(ds_obj.get("description") or "").strip() or None
    documents = _require_documents(fixture)
    _ensure_schema_ready()

    db = SessionLocal()
    try:
        ensure_fixture_tenant_owner(db, tenant_id=tenant_id, account_id=account_id)
        _upsert_dataset(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            dataset_desc=dataset_desc,
            account_id=account_id,
        )
        for doc in documents:
            doc_id = UUID(str(doc.get("id") or "").strip())
            filename = str(doc.get("filename") or "").strip() or f"{doc_id}.txt"
            file_type = str(doc.get("file_type") or "md").strip().lower() or "md"
            doc_meta = doc.get("doc_metadata") if isinstance(doc.get("doc_metadata"), dict) else {}
            chunks = doc.get("chunks")
            if not isinstance(chunks, list) or not chunks:
                raise ValueError("each document must include chunks[]")
            total_chars = _document_total_chars(chunks)
            _upsert_document(
                db=db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                doc_id=doc_id,
                filename=filename,
                file_type=file_type,
                total_chars=total_chars,
                chunks=chunks,
                doc_meta=doc_meta,
            )
            _replace_document_chunks(
                db=db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                doc_id=doc_id,
                filename=filename,
                doc_meta=doc_meta,
                chunks=chunks,
            )
        db.commit()
        _seed_kg_rows(db=db, tenant_id=tenant_id, account_id=account_id, fixture=fixture)
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Seed CI KG-search regression fixture dataset/documents/chunks/KG rows.")
    p.add_argument(
        "--fixture",
        default=str(Path("ci") / "kg_search_regression_fixture.v1.json"),
        help="Fixture JSON path (default: %(default)s)",
    )
    p.add_argument(
        "--out-cases",
        default="",
        help="Write regression cases bundle (mimirq.regression_cases.v1) to this path (optional)",
    )
    args = p.parse_args()

    fixture_path = Path(args.fixture)
    fixture = _load_json(fixture_path)
    if not isinstance(fixture, dict):
        raise SystemExit(2)

    seed_fixture(fixture=fixture)

    if args.out_cases:
        bundle = build_cases_bundle(fixture)
        write_json_file(Path(args.out_cases), bundle)

    print("[seed_ci_kg_search_regression] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
