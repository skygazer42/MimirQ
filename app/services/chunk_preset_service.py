"""Persist reusable chunking presets within a tenant."""

from typing import Any
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.chunk_preset import ChunkPreset


def list_chunk_presets(
    *,
    db: Session,
    tenant_id: UUID,
    q: str | None,
    limit: int,
    dataset_id: UUID | None,
    include_global: bool,
    readable_dataset_ids: set[UUID] | None = None,
) -> list[ChunkPreset]:
    q = (q or "").strip()

    query = db.query(ChunkPreset).filter(ChunkPreset.tenant_id == tenant_id)
    if dataset_id is not None:
        if include_global:
            query = query.filter(or_(ChunkPreset.dataset_id == dataset_id, ChunkPreset.dataset_id.is_(None)))
        else:
            query = query.filter(ChunkPreset.dataset_id == dataset_id)
    elif readable_dataset_ids is not None:
        query = query.filter(or_(ChunkPreset.dataset_id.is_(None), ChunkPreset.dataset_id.in_(readable_dataset_ids)))
    if q:
        query = query.filter(ChunkPreset.name.ilike(f"%{q}%"))

    return (
        query.order_by(ChunkPreset.updated_at.desc().nullslast(), ChunkPreset.created_at.desc().nullslast())
        .limit(limit)
        .all()
    )


def get_chunk_preset(*, db: Session, tenant_id: UUID, preset_id: str) -> ChunkPreset | None:
    try:
        pid = UUID(preset_id)
    except ValueError:
        return None

    return db.query(ChunkPreset).filter(ChunkPreset.tenant_id == tenant_id).filter(ChunkPreset.id == pid).first()


def create_chunk_preset(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None,
    name: str,
    description: str | None,
    payload: dict[str, Any],
) -> ChunkPreset:
    row = ChunkPreset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name=name.strip(),
        description=description,
        payload=payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_chunk_preset(
    *,
    db: Session,
    tenant_id: UUID,
    preset_id: str,
    dataset_id: UUID | None,
    name: str,
    description: str | None,
    payload: dict[str, Any],
) -> ChunkPreset | None:
    row = get_chunk_preset(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not row:
        return None

    row.dataset_id = dataset_id
    row.name = name.strip()
    row.description = description
    row.payload = payload

    db.commit()
    db.refresh(row)
    return row


def delete_chunk_preset(*, db: Session, tenant_id: UUID, preset_id: str) -> bool:
    row = get_chunk_preset(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
