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


import argparse
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import app.models._all  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.migrations import apply_runtime_migrations
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.kg.models import KgEntity, KgEntityAlias, KgEventEntity, KgRelation, KgSourceEvent


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


def _normalize_name(text: str) -> str:
    from app.rag.kg.extraction.parser import EntityValueParser

    return EntityValueParser().normalize_name(text)


def _normalize_type(text: str) -> str:
    from app.rag.kg.extraction.parser import EntityValueParser

    return EntityValueParser().normalize_type(text)


def _seed_kg_rows(*, db, tenant_id: UUID, account_id: str, fixture: dict[str, Any]) -> None:
    kg = fixture.get("kg") if isinstance(fixture.get("kg"), dict) else {}
    if not kg:
        return

    entities = kg.get("entities") if isinstance(kg.get("entities"), list) else []
    aliases = kg.get("aliases") if isinstance(kg.get("aliases"), list) else []
    events = kg.get("events") if isinstance(kg.get("events"), list) else []
    event_entities = kg.get("event_entities") if isinstance(kg.get("event_entities"), list) else []
    relations = kg.get("relations") if isinstance(kg.get("relations"), list) else []

    entity_ids = [UUID(str(e.get("id"))) for e in entities if isinstance(e, dict) and e.get("id")]
    alias_ids = [UUID(str(a.get("id"))) for a in aliases if isinstance(a, dict) and a.get("id")]
    event_ids = [UUID(str(ev.get("id"))) for ev in events if isinstance(ev, dict) and ev.get("id")]
    link_ids = [UUID(str(link.get("id"))) for link in event_entities if isinstance(link, dict) and link.get("id")]
    relation_ids = [UUID(str(r.get("id"))) for r in relations if isinstance(r, dict) and r.get("id")]

    # Deterministic re-seed: delete fixture rows (children -> parents).
    if event_ids:
        db.query(KgEventEntity).filter(KgEventEntity.event_id.in_(event_ids)).delete(synchronize_session=False)
    if link_ids:
        db.query(KgEventEntity).filter(KgEventEntity.id.in_(link_ids)).delete(synchronize_session=False)

    if relation_ids or event_ids or entity_ids:
        from sqlalchemy import or_  # noqa: WPS433

        parts = []
        if relation_ids:
            parts.append(KgRelation.id.in_(relation_ids))
        if event_ids:
            parts.append(KgRelation.event_id.in_(event_ids))
        if entity_ids:
            parts.append(KgRelation.subject_entity_id.in_(entity_ids))
            parts.append(KgRelation.object_entity_id.in_(entity_ids))
        if parts:
            db.query(KgRelation).filter(KgRelation.tenant_id == tenant_id).filter(or_(*parts)).delete(
                synchronize_session=False
            )

    if alias_ids or entity_ids:
        from sqlalchemy import or_  # noqa: WPS433

        parts = []
        if alias_ids:
            parts.append(KgEntityAlias.id.in_(alias_ids))
        if entity_ids:
            parts.append(KgEntityAlias.canonical_entity_id.in_(entity_ids))
        if parts:
            db.query(KgEntityAlias).filter(KgEntityAlias.tenant_id == tenant_id).filter(or_(*parts)).delete(
                synchronize_session=False
            )

    if event_ids:
        db.query(KgSourceEvent).filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.id.in_(event_ids),
        ).delete(synchronize_session=False)

    if entity_ids:
        db.query(KgEntity).filter(
            KgEntity.tenant_id == tenant_id,
            KgEntity.id.in_(entity_ids),
        ).delete(synchronize_session=False)

    db.commit()

    # Insert entities.
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        ent_id = UUID(str(ent.get("id") or "").strip())
        name = str(ent.get("name") or "").strip()
        if not name:
            raise ValueError("kg.entities[].name is required")
        type_raw = str(ent.get("type") or "").strip()
        type_norm = _normalize_type(type_raw) if type_raw else "unknown"
        norm_name = str(ent.get("normalized_name") or "").strip() or _normalize_name(name)

        db.add(
            KgEntity(
                id=ent_id,
                tenant_id=tenant_id,
                name=name,
                type=type_norm,
                normalized_name=norm_name,
                description=(str(ent.get("description") or "").strip() or None),
                vector=ent.get("vector"),
                extra_data=ent.get("extra_data") if isinstance(ent.get("extra_data"), dict) else None,
            )
        )

    # Insert aliases.
    for a in aliases:
        if not isinstance(a, dict):
            continue
        alias_id = UUID(str(a.get("id") or "").strip())
        canonical_id = UUID(str(a.get("canonical_entity_id") or "").strip())
        alias = str(a.get("alias") or "").strip()
        if not alias:
            raise ValueError("kg.aliases[].alias is required")
        normalized_alias = str(a.get("normalized_alias") or "").strip() or _normalize_name(alias)

        db.add(
            KgEntityAlias(
                id=alias_id,
                tenant_id=tenant_id,
                canonical_entity_id=canonical_id,
                alias=alias,
                normalized_alias=normalized_alias,
                created_by=str(a.get("created_by") or account_id or "").strip() or None,
                extra_data=a.get("extra_data") if isinstance(a.get("extra_data"), dict) else None,
            )
        )

    # Insert events.
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev_id = UUID(str(ev.get("id") or "").strip())
        pipeline_hash = str(ev.get("pipeline_hash") or "").strip() or None
        doc_id_raw = str(ev.get("document_id") or "").strip()
        chunk_id_raw = str(ev.get("chunk_id") or "").strip()

        doc_id = UUID(doc_id_raw) if doc_id_raw else None
        chunk_id = UUID(chunk_id_raw) if chunk_id_raw else None

        title = str(ev.get("title") or "").strip()
        summary = str(ev.get("summary") or "").strip()
        content = str(ev.get("content") or "").strip()
        if not title or not summary or not content:
            raise ValueError("kg.events[] requires title/summary/content")

        db.add(
            KgSourceEvent(
                id=ev_id,
                tenant_id=tenant_id,
                pipeline_hash=pipeline_hash,
                document_id=doc_id,
                chunk_id=chunk_id,
                title=title,
                summary=summary,
                content=content,
                content_vector=ev.get("content_vector"),
                references=ev.get("references") if isinstance(ev.get("references"), dict) else None,
                extra_data=ev.get("extra_data") if isinstance(ev.get("extra_data"), dict) else None,
            )
        )

    # Insert event<->entity links.
    for link in event_entities:
        if not isinstance(link, dict):
            continue
        link_id = UUID(str(link.get("id") or "").strip())
        ev_id = UUID(str(link.get("event_id") or "").strip())
        ent_id = UUID(str(link.get("entity_id") or "").strip())
        weight = float(link.get("weight", 1.0) or 1.0)
        role = str(link.get("role") or "").strip() or None

        db.add(
            KgEventEntity(
                id=link_id,
                event_id=ev_id,
                entity_id=ent_id,
                weight=weight,
                role=role,
                extra_data=link.get("extra_data") if isinstance(link.get("extra_data"), dict) else None,
            )
        )

    # Insert relations (optional).
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        rel_id = UUID(str(rel.get("id") or "").strip())
        subj = UUID(str(rel.get("subject_entity_id") or "").strip())
        obj = UUID(str(rel.get("object_entity_id") or "").strip())
        predicate = str(rel.get("predicate") or "").strip() or "related_to"
        conf = float(rel.get("confidence", 0.5) or 0.5)

        doc_id = rel.get("document_id")
        ch_id = rel.get("chunk_id")
        ev_id = rel.get("event_id")
        pipeline_hash = str(rel.get("pipeline_hash") or "").strip() or None

        db.add(
            KgRelation(
                id=rel_id,
                tenant_id=tenant_id,
                pipeline_hash=pipeline_hash,
                document_id=UUID(str(doc_id)) if doc_id else None,
                chunk_id=UUID(str(ch_id)) if ch_id else None,
                event_id=UUID(str(ev_id)) if ev_id else None,
                subject_entity_id=subj,
                predicate=predicate,
                predicate_raw=str(rel.get("predicate_raw") or "").strip() or None,
                object_entity_id=obj,
                confidence=conf,
                qualifiers=rel.get("qualifiers") if isinstance(rel.get("qualifiers"), dict) else None,
                references=rel.get("references") if isinstance(rel.get("references"), dict) else None,
                extra_data=rel.get("extra_data") if isinstance(rel.get("extra_data"), dict) else None,
            )
        )

    db.commit()


def seed_fixture(*, fixture: dict[str, Any]) -> None:
    tenant_id = UUID(str(fixture.get("tenant_id") or "").strip())
    account_id = str(fixture.get("account_id") or "").strip() or "ci-bot"

    ds_obj = fixture.get("dataset") if isinstance(fixture.get("dataset"), dict) else {}
    dataset_id = UUID(str(ds_obj.get("id") or "").strip())
    dataset_name = str(ds_obj.get("name") or "CI KG Search Regression Fixture").strip()
    dataset_desc = str(ds_obj.get("description") or "").strip() or None

    documents = fixture.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("fixture.documents must be a non-empty list")

    # Ensure schema is up-to-date (best-effort; mirrors app startup).
    apply_runtime_migrations(engine)
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)

    db = SessionLocal()
    try:
        # Upsert dataset by id.
        ds = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).first()
        if ds is None:
            ds = Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name=dataset_name,
                description=dataset_desc,
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id=account_id,
                dataset_metadata={},
            )
            db.add(ds)
        else:
            ds.name = dataset_name
            ds.description = dataset_desc
            ds.owner_id = account_id
        db.commit()

        # Upsert documents + replace chunks for determinism.
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            doc_id = UUID(str(doc.get("id") or "").strip())
            filename = str(doc.get("filename") or "").strip() or f"{doc_id}.txt"
            file_type = str(doc.get("file_type") or "md").strip().lower() or "md"
            doc_meta = doc.get("doc_metadata") if isinstance(doc.get("doc_metadata"), dict) else {}

            chunks = doc.get("chunks")
            if not isinstance(chunks, list) or not chunks:
                raise ValueError("each document must include chunks[]")
            total_chars = 0
            for ch in chunks:
                if isinstance(ch, dict):
                    total_chars += len(str(ch.get("content") or ""))

            row = db.query(DBDocument).filter(DBDocument.id == doc_id, DBDocument.tenant_id == tenant_id).first()
            if row is None:
                row = DBDocument(
                    id=doc_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    filename=filename,
                    file_type=file_type,
                    file_size=int(total_chars),
                    file_path=f"ci://{filename}",
                    status="completed",
                    chunk_count=len(chunks),
                    total_characters=int(total_chars),
                    doc_metadata=dict(doc_meta),
                )
                db.add(row)
            else:
                row.dataset_id = dataset_id
                row.filename = filename
                row.file_type = file_type
                row.file_size = int(total_chars)
                row.file_path = f"ci://{filename}"
                row.status = "completed"
                row.error_message = None
                row.chunk_count = len(chunks)
                row.total_characters = int(total_chars)
                row.doc_metadata = dict(doc_meta)

            # Replace chunks for this document (idempotent across reruns).
            db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == doc_id).delete(
                synchronize_session=False
            )

            for ch in chunks:
                if not isinstance(ch, dict):
                    continue
                chunk_id = UUID(str(ch.get("id") or "").strip())
                chunk_index = int(ch.get("chunk_index") or 0)
                content = str(ch.get("content") or "")
                page_number = ch.get("page_number")
                try:
                    page_number = int(page_number) if page_number is not None else None
                except Exception:
                    page_number = None

                chunk_meta: dict[str, Any] = {
                    "dataset_id": str(dataset_id),
                    "source": filename,
                }
                for k in ("active_pipeline_hash", "pipeline_hash", "doc_pipeline_key"):
                    if k in doc_meta and doc_meta.get(k) is not None:
                        chunk_meta[k] = doc_meta.get(k)

                active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
                if active_hash:
                    chunk_meta.setdefault("pipeline_hash", active_hash)
                    chunk_meta.setdefault("doc_pipeline_key", f"{doc_id}:{active_hash}")

                db.add(
                    DocumentChunk(
                        id=chunk_id,
                        tenant_id=tenant_id,
                        document_id=doc_id,
                        chunk_index=chunk_index,
                        content=content,
                        page_number=page_number,
                        doc_metadata=chunk_meta,
                    )
                )

        db.commit()

        # Seed KG rows last (depends on documents/chunks being present).
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
