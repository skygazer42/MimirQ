"""
Chunk presets API.

Tenant-scoped CRUD endpoints for reusable chunking configurations.
"""


from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.chunk_preset import ChunkPreset
from app.services.base_service import BaseService
from app.services.dataset_service import DatasetService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


class ChunkPresetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
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


def _list_chunk_preset_rows(
    *,
    db: Session,
    tenant_id: UUID,
    q: str | None,
    limit: int,
    dataset_id: UUID | None,
    include_global: bool,
) -> list[Any]:
    q = (q or "").strip()
    limit = max(1, min(int(limit or 50), 200))
    include_global = bool(include_global)

    query = db.query(ChunkPreset).filter(ChunkPreset.tenant_id == tenant_id)
    if dataset_id is not None:
        if include_global:
            query = query.filter(or_(ChunkPreset.dataset_id == dataset_id, ChunkPreset.dataset_id.is_(None)))
        else:
            query = query.filter(ChunkPreset.dataset_id == dataset_id)
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


def _create_chunk_preset_row(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None,
    name: str,
    description: str | None,
    payload: dict,
) -> Any:
    row = ChunkPreset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
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
    dataset_id: UUID | None,
    name: str,
    description: str | None,
    payload: dict,
) -> Any | None:
    row = _get_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not row:
        return None

    row.dataset_id = dataset_id
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


def _dataset_uuid_from_payload(payload: dict[str, Any]) -> UUID | None:
    raw = payload.get("dataset_id")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return UUID(s)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid payload.dataset_id: {s[:64]}") from exc


@router.get("", response_model=ChunkPresetListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_chunk_presets(
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    dataset_id: Annotated[str | None, Query(max_length=64)] = None,
    include_global: Annotated[bool, Query()] = True,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset_uuid: UUID | None = None
    if dataset_id is not None and str(dataset_id).strip():
        try:
            dataset_uuid = UUID(str(dataset_id))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid dataset_id: {str(dataset_id)[:64]}") from exc

    rows = _list_chunk_preset_rows(
        db=db,
        tenant_id=tenant_id,
        q=q,
        limit=int(limit or 100),
        dataset_id=dataset_uuid,
        include_global=bool(include_global),
    )
    return ChunkPresetListResponse(items=[_row_to_response(r) for r in rows])


@router.post("", response_model=ChunkPresetResponse, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_chunk_preset(
    req: ChunkPresetCreateRequest,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    BaseService.assert_edit_role(member)
    dataset_uuid = _dataset_uuid_from_payload(req.payload)
    if dataset_uuid is not None:
        DatasetService.get_dataset(db, tenant_id, dataset_uuid)
    row = _create_chunk_preset_row(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_uuid,
        name=req.name,
        description=req.description,
        payload=req.payload,
    )
    return _row_to_response(row)


@router.put("/{preset_id}", response_model=ChunkPresetResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_chunk_preset(
    preset_id: str,
    req: ChunkPresetUpdateRequest,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    BaseService.assert_edit_role(member)
    existing = _get_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    dataset_uuid = _dataset_uuid_from_payload(req.payload)
    if dataset_uuid is not None:
        DatasetService.get_dataset(db, tenant_id, dataset_uuid)
    row = _update_chunk_preset_row(
        db=db,
        tenant_id=tenant_id,
        preset_id=preset_id,
        dataset_id=dataset_uuid,
        name=req.name,
        description=req.description,
        payload=req.payload,
    )
    return _row_to_response(row)


@router.delete("/{preset_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_chunk_preset(
    preset_id: str,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    BaseService.assert_edit_role(member)
    ok = _delete_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    return Response(status_code=204)
