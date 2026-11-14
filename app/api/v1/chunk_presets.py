"""
Chunk presets API.

Tenant-scoped CRUD endpoints for reusable chunking configurations.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.pipelines import (
    ChunkPresetCreateRequest,
    ChunkPresetListResponse,
    ChunkPresetResponse,
    ChunkPresetUpdateRequest,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.chunk_preset import ChunkPreset
from app.models.dataset import Dataset
from app.services import chunk_preset_service, dataset_service
from app.services.document_access import build_dataset_read_filter
from app.services.rbac_service import assert_edit_role

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _preset_response(row: ChunkPreset) -> ChunkPresetResponse:
    return ChunkPresetResponse(
        id=str(row.id),
        name=row.name,
        description=row.description,
        payload=row.payload if row.payload is not None else {},
    )


def _parse_payload_dataset_id(payload: dict[str, Any]) -> UUID | None:
    raw = payload.get("dataset_id")
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload.dataset_id: {value[:64]}") from exc


def _get_writable_preset(db: Session, *, tenant_id: UUID, account_id: str, preset_id: str) -> ChunkPreset:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    assert_edit_role(member)
    preset = chunk_preset_service.get_chunk_preset(db=db, tenant_id=tenant_id, preset_id=preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Chunk preset not found")
    if preset.dataset_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, preset.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
    return preset


@router.get("", response_model=ChunkPresetListResponse, responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
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

    rows = chunk_preset_service.list_chunk_presets(
        db=db,
        tenant_id=tenant_id,
        q=q,
        limit=limit,
        dataset_id=dataset_uuid,
        include_global=include_global,
        readable_dataset_ids=readable_dataset_ids,
    )
    return ChunkPresetListResponse(items=[_preset_response(row) for row in rows])


@router.post("", response_model=ChunkPresetResponse, status_code=201, responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_chunk_preset(
    req: ChunkPresetCreateRequest,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ChunkPresetResponse:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    assert_edit_role(member)
    dataset_uuid = _parse_payload_dataset_id(req.payload)
    if dataset_uuid is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_uuid)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
    row = chunk_preset_service.create_chunk_preset(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_uuid,
        name=req.name,
        description=req.description,
        payload=req.payload,
    )
    return _preset_response(row)


@router.put("/{preset_id}", response_model=ChunkPresetResponse, responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_chunk_preset(
    preset_id: str,
    req: ChunkPresetUpdateRequest,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ChunkPresetResponse:
    preset = _get_writable_preset(db, tenant_id=tenant_id, account_id=account_id, preset_id=preset_id)
    dataset_uuid = _parse_payload_dataset_id(req.payload)
    if dataset_uuid is not None and dataset_uuid != preset.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_uuid)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
    row = chunk_preset_service.update_chunk_preset(
        db=db,
        preset=preset,
        dataset_id=dataset_uuid,
        name=req.name,
        description=req.description,
        payload=req.payload,
    )
    return _preset_response(row)


@router.delete("/{preset_id}", status_code=204, responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_chunk_preset(
    preset_id: str,
    *,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> Response:
    preset = _get_writable_preset(db, tenant_id=tenant_id, account_id=account_id, preset_id=preset_id)
    chunk_preset_service.delete_chunk_preset(db=db, preset=preset)
    return Response(status_code=204)
