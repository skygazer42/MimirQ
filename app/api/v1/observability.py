"""
Observability endpoints (admin-only).

Currently provides a small, PII-safe dashboard summary for RAG metrics based on the
JSONL metrics log (ENABLE_METRICS_LOG / METRICS_LOG_PATH).
"""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.dataset_service import DatasetService
from app.services.rag_metrics_dashboard import summarize_rag_metrics

router = APIRouter()

_ADMIN_ROLES = {"owner", "admin"}


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="No permission to access observability dashboards")


class RagMetricsSummaryResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int
    reranker_api_count: int
    retrieval_avg_elapsed_sec: float | None = None
    retrieval_p95_elapsed_sec: float | None = None
    rerank_avg_elapsed_sec: float | None = None
    citations_avg_count: float | None = None
    retrieval_mode_counts: Dict[str, int] = {}
    hit_type_counts: Dict[str, int] = {}
    error_counts: Dict[str, int] = {}
    timeseries: Dict[str, List[Any]] = {}


@router.get("/rag-metrics/summary", response_model=RagMetricsSummaryResponse)
def get_rag_metrics_summary(
    window_minutes: int = Query(default=60, ge=1, le=7 * 24 * 60),
    max_bytes: int = Query(default=5_000_000, ge=100_000, le=50_000_000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_metrics(tenant_id=str(tenant_id), window_minutes=window_minutes, max_bytes=max_bytes)
    # Dataclass -> dict (safe fields only by construction).
    return summary.__dict__
