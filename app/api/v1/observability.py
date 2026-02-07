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
    retriever_overfetch_count: int = 0
    retriever_overfetch_avg_ratio: float | None = None
    retriever_filtered_acl_total: int = 0
    retrieval_mode_counts: Dict[str, int] = {}
    hit_type_counts: Dict[str, int] = {}
    error_counts: Dict[str, int] = {}
    timeseries: Dict[str, List[Any]] = {}


class IndexAuditResponse(BaseModel):
    tenant_id: str
    dataset_id: str
    vector_backend: str = ""

    active_documents: int = 0
    active_chunks: int = 0

    vector_id_missing: int = 0

    vector_ids_checked: int = 0
    vector_ids_missing_in_backend: int = 0
    vector_ids_missing_in_backend_sample: List[str] = []

    milvus_ids_sampled: int = 0
    milvus_orphan_ids_sample: List[str] = []


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


@router.get("/index-audit", response_model=IndexAuditResponse)
def get_index_audit(
    dataset_id: UUID = Query(..., description="Dataset id to audit (required)"),
    max_check_ids: int = Query(default=5000, ge=0, le=50_000, description="Max DB vector_ids to existence-check"),
    milvus_list_limit: int = Query(default=2000, ge=0, le=50_000, description="Max Milvus ids to sample for orphans"),
    sample_limit: int = Query(default=20, ge=0, le=200, description="Max sample ids to return per category"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Dataset-scoped index consistency audit (admin-only).

    This is best-effort and bounded:
    - Detects chunks missing `vector_id` in Postgres.
    - Checks a bounded set of DB `vector_id` values for existence in the vector backend (Milvus).
    - Optionally samples a bounded set of Milvus ids and reports orphans (vectors without active DB chunks).
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.index_audit_service import run_dataset_index_audit

    return run_dataset_index_audit(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        max_check_ids=max_check_ids,
        milvus_list_limit=milvus_list_limit,
        sample_limit=sample_limit,
    )
