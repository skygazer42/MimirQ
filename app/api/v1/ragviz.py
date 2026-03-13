"""
RAG visualization (ragviz) API.

Provides collection-to-collection similarity matrix endpoints used by the
frontend heatmap page (Kumi-style).
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.ragviz_similarity import calculate_similarity_matrix, list_similarity_collections

router = APIRouter()


class SimilarityCollectionOut(BaseModel):
    id: str
    label: str
    kind: str
    count: int
    meta: Dict[str, Any] = Field(default_factory=dict)


class SimilarityCollectionsResponse(BaseModel):
    success: bool = True
    collections: List[SimilarityCollectionOut] = Field(default_factory=list)
    count: int = 0


@router.get("/similarity/collections", response_model=SimilarityCollectionsResponse)
def get_similarity_collections(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    collections = list_similarity_collections(db, tenant_id, account_id)
    out = [
        SimilarityCollectionOut(
            id=c.id,
            label=c.label,
            kind=c.kind,
            count=c.count,
            meta=c.meta,
        )
        for c in collections
    ]
    return SimilarityCollectionsResponse(success=True, collections=out, count=len(out))


class SimilarityRequest(BaseModel):
    x_collection: str = Field(..., description="X axis collection id")
    y_collection: str = Field(..., description="Y axis collection id")
    x_max_items: Optional[int] = Field(100, description="X axis max items")
    y_max_items: Optional[int] = Field(100, description="Y axis max items")
    max_items: Optional[int] = Field(100, description="Back-compat max items")


class SimilarityCalculateResponse(BaseModel):
    success: bool = True
    result: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    x_collection: Optional[str] = None
    y_collection: Optional[str] = None


@router.post("/similarity/calculate", response_model=SimilarityCalculateResponse)
def similarity_calculate(
    request: SimilarityRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    x_collection = request.x_collection
    y_collection = request.y_collection
    x_max_items = int(request.x_max_items or request.max_items or 100)
    y_max_items = int(request.y_max_items or request.max_items or 100)

    # Hard limits to protect the service from excessive memory usage.
    x_max_items = max(1, min(x_max_items, 3000))
    y_max_items = max(1, min(y_max_items, 3000))

    try:
        result = calculate_similarity_matrix(
            db,
            tenant_id,
            account_id,
            x_collection=x_collection,
            y_collection=y_collection,
            x_max_items=x_max_items,
            y_max_items=y_max_items,
        )
        return SimilarityCalculateResponse(
            success=True,
            result=result,
            message=f"成功计算 {len(result.get('y_data') or [])} x {len(result.get('x_data') or [])} 相似度矩阵",
        )
    except ValueError as exc:
        msg = str(exc)
        return SimilarityCalculateResponse(
            success=False,
            error=msg,
            error_type="dimension_mismatch" if "维度不匹配" in msg else "calculation_error",
            x_collection=x_collection,
            y_collection=y_collection,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={"success": False, "error": str(exc)}) from exc

