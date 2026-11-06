"""
Chunk presets API.

Tenant-scoped CRUD endpoints for reusable chunking configurations.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chunk_preset import (
    ChunkPresetCreateRequest,
    ChunkPresetListResponse,
    ChunkPresetResponse,
    ChunkPresetUpdateRequest,
)
from app.core.database import get_db
from app.models.chunk_preset import ChunkPreset
from app.models.dataset import Dataset
from app.services import dataset_service
from app.services.chunk_preset_service import create_chunk_preset as _create_chunk_preset_row
from app.services.chunk_preset_service import delete_chunk_preset as _delete_chunk_preset_row
from app.services.chunk_preset_service import get_chunk_preset as _get_chunk_preset_row
from app.services.chunk_preset_service import list_chunk_presets as _list_chunk_preset_rows
from app.services.chunk_preset_service import update_chunk_preset as _update_chunk_preset_row
from app.services.document_access import build_dataset_read_filter
from app.services.rbac_service import assert_edit_role

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _row_to_response(row: ChunkPreset) -> ChunkPresetResponse:
    return ChunkPresetResponse(
        id=str(row.id),
        name=row.name,
        description=row.description,
        payload=dict(row.payload or {}),
    )


def _dataset_uuid_from_payload(payload: dict[str, Any]) -> UUID | None:
    raw = payload.get("dataset_id")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return UUID(s)
    except ValueError as exc:
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
) -> ChunkPresetListResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset_uuid: UUID | None = None
    if dataset_id is not None and dataset_id.strip():
        try:
            dataset_uuid = UUID(dataset_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid dataset_id: {dataset_id[:64]}") from exc
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_uuid)
        dataset_service.assert_dataset_readable(db, dataset, account_id)

    readable_dataset_ids: set[UUID] | None = None
    if dataset_uuid is None:
        readable_dataset_ids = set(
            db.scalars(
                select(Dataset.id).where(
                    Dataset.tenant_id == tenant_id,
                    build_dataset_read_filter(tenant_id=tenant_id, account_id=account_id),
                )
            ).all()
        )

    rows = _list_chunk_preset_rows(
        db=db,
        tenant_id=tenant_id,
        q=q,
        limit=limit,
        dataset_id=dataset_uuid,
        include_global=include_global,
        readable_dataset_ids=readable_dataset_ids,
    )
    return ChunkPresetListResponse(items=[_row_to_response(r) for r in rows])


@router.post("", response_model=ChunkPresetResponse, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_chunk_preset(
    req: ChunkPresetCreateRequest,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ChunkPresetResponse:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    assert_edit_role(member)
    dataset_uuid = _dataset_uuid_from_payload(req.payload)
    if dataset_uuid is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_uuid)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
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
) -> ChunkPresetResponse:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    assert_edit_role(member)
    existing = _get_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    if existing.dataset_id is not None:
        existing_dataset = dataset_service.get_dataset(db, tenant_id, existing.dataset_id)
        dataset_service.assert_dataset_writable(db, existing_dataset, account_id)
    dataset_uuid = _dataset_uuid_from_payload(req.payload)
    if dataset_uuid is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_uuid)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
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
) -> Response:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    assert_edit_role(member)
    existing = _get_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    if existing.dataset_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, existing.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
    ok = _delete_chunk_preset_row(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    return Response(status_code=204)
