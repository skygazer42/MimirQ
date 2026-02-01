"""
Chunk presets API.

Tenant-scoped CRUD endpoints for reusable chunking configurations.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.chunk_preset import ChunkPreset
from app.services.dataset_service import DatasetService

router = APIRouter()


class ChunkPresetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetListResponse(BaseModel):
    items: list[ChunkPresetResponse] = Field(default_factory=list)


def _row_to_response(row: Any) -> ChunkPresetResponse:
    return ChunkPresetResponse(
        id=str(row.id),
        name=str(row.name or ""),
        description=row.description,
        payload=dict(row.payload or {}),
    )


def _list_chunk_preset_rows(*, db: Session, tenant_id: UUID, q: str | None, limit: int) -> list[Any]:
    q = (q or "").strip()
    limit = max(1, min(int(limit or 50), 200))

    query = db.query(ChunkPreset).filter(ChunkPreset.tenant_id == tenant_id)
    if q:
        query = query.filter(ChunkPreset.name.ilike(f"%{q}%"))

    return (
        query.order_by(ChunkPreset.updated_at.desc().nullslast(), ChunkPreset.created_at.desc().nullslast())
        .limit(limit)
        .all()
    )


def _get_chunk_preset_row(*, db: Session, tenant_id: UUID, preset_id: str) -> Any | None:
    try:
        pid = UUID(str(preset_id))
    except Exception:  # noqa: BLE001
        return None

    return (
        db.query(ChunkPreset)
        .filter(ChunkPreset.tenant_id == tenant_id)
        .filter(ChunkPreset.id == pid)
        .first()
    )


def _create_chunk_preset_row(*, db: Session, tenant_id: UUID, name: str, description: str | None, payload: dict) -> Any:
    row = ChunkPreset(
        tenant_id=tenant_id,
        name=str(name or "").strip(),
        description=description,
        payload=payload or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _update_chunk_preset_row(
    *,
    db: Session,
    tenant_id: UUID,
    preset_id: str,
    name: str,
    description: str | None,
    payload: dict,
) -> Any | None:
    row = _get_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not row:
        return None

    row.name = str(name or "").strip()
    row.description = description
    row.payload = payload or {}

    db.commit()
    db.refresh(row)
    return row


def _delete_chunk_preset_row(*, db: Session, tenant_id: UUID, preset_id: str) -> bool:
    row = _get_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


@router.get("", response_model=ChunkPresetListResponse)
def list_chunk_presets(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    rows = _list_chunk_preset_rows(db=db, tenant_id=tenant_id, q=q, limit=int(limit or 100))
    return ChunkPresetListResponse(items=[_row_to_response(r) for r in rows])


@router.post("", response_model=ChunkPresetResponse, status_code=201)
def create_chunk_preset(
    req: ChunkPresetCreateRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    row = _create_chunk_preset_row(
        db=db,
        tenant_id=tenant_id,
        name=req.name,
        description=req.description,
        payload=req.payload,
    )
    return _row_to_response(row)


@router.put("/{preset_id}", response_model=ChunkPresetResponse)
def update_chunk_preset(
    preset_id: str,
    req: ChunkPresetUpdateRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    row = _update_chunk_preset_row(
        db=db,
        tenant_id=tenant_id,
        preset_id=preset_id,
        name=req.name,
        description=req.description,
        payload=req.payload,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    return _row_to_response(row)


@router.delete("/{preset_id}", status_code=204)
def delete_chunk_preset(
    preset_id: str,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    ok = _delete_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    return Response(status_code=204)
