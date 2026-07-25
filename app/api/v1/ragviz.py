"""
RAG visualization (ragviz) API.

Provides collection-to-collection similarity matrix endpoints used by the
frontend heatmap page (Kumi-style).
"""


from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.ragviz_similarity import (
    SimilarityLimitError,
    calculate_similarity_matrix,
    list_similarity_collections,
    resolve_similarity_request_limits,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
    422: {"description": "Unprocessable Entity"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


class SimilarityCollectionOut(BaseModel):
    id: str
    label: str
    kind: str
    count: int
    meta: dict[str, Any] = Field(default_factory=dict)


class SimilarityCollectionsResponse(BaseModel):
    success: bool = True
    collections: list[SimilarityCollectionOut] = Field(default_factory=list)
    count: int = 0


@router.get("/similarity/collections", response_model=SimilarityCollectionsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
    x_max_items: int | None = Field(None, ge=1, description="X axis max items")
    y_max_items: int | None = Field(None, ge=1, description="Y axis max items")
    max_items: int | None = Field(100, ge=1, description="Back-compat max items")


class SimilarityCalculateResponse(BaseModel):
    success: bool = True
    result: dict[str, Any] | None = None
    message: str | None = None
    error: str | None = None
    error_type: str | None = None
    x_collection: str | None = None
    y_collection: str | None = None


@router.post("/similarity/calculate", response_model=SimilarityCalculateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def similarity_calculate(
    request: SimilarityRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    x_collection = request.x_collection
    y_collection = request.y_collection

    try:
        x_max_items, y_max_items = resolve_similarity_request_limits(
            x_max_items=request.x_max_items,
            y_max_items=request.y_max_items,
            max_items=request.max_items,
        )
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
    except SimilarityLimitError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), **(exc.detail or {})},
        ) from exc
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
