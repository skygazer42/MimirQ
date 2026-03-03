"""
Observability endpoints (admin-only).

Currently provides a small, PII-safe dashboard summary for RAG metrics based on the
JSONL metrics log (ENABLE_METRICS_LOG / METRICS_LOG_PATH).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.rag_metrics_dashboard import (
    build_rag_trace_bundle,
    summarize_rag_metrics,
    summarize_rag_query_analytics,
)
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter()


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.OBSERVABILITY_READ,
        detail="No permission to access observability dashboards",
    )


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


class RagQueryAnalyticsResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int
    unique_query_hashes: int

    zero_hit_count: int
    zero_hit_rate: float | None = None

    slow_threshold_sec: float
    slow_count: int
    slow_rate: float | None = None

    retrieval_p50_elapsed_sec: float | None = None
    retrieval_p95_elapsed_sec: float | None = None
    retrieval_p99_elapsed_sec: float | None = None

    error_kind_counts: Dict[str, int] = Field(default_factory=dict)
    top_zero_hit_queries: List[Dict[str, Any]] = Field(default_factory=list)
    top_slow_queries: List[Dict[str, Any]] = Field(default_factory=list)
    timeseries: Dict[str, List[Any]] = Field(default_factory=dict)


class RagTraceBundleResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    request_id: str
    records: List[Dict[str, Any]] = Field(default_factory=list)


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


class IngestionDashboardSummaryResponse(BaseModel):
    window_hours: int
    bucket_minutes: int
    window_start: datetime
    window_end: datetime
    dataset_id: str | None = None

    created_count: int = 0
    by_status: Dict[str, int] = {}
    by_stage_processing: Dict[str, int] = {}
    avg_completed_latency_sec: float | None = None

    top_error_reasons: Dict[str, int] = {}
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


@router.get("/rag-metrics/query-analytics", response_model=RagQueryAnalyticsResponse)
def get_rag_query_analytics(
    window_minutes: int = Query(default=60, ge=1, le=7 * 24 * 60),
    slow_threshold_sec: float = Query(default=2.0, ge=0.0, le=120.0),
    top_n: int = Query(default=20, ge=1, le=200),
    max_bytes: int = Query(default=5_000_000, ge=100_000, le=50_000_000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_query_analytics(
        tenant_id=str(tenant_id),
        window_minutes=window_minutes,
        max_bytes=max_bytes,
        slow_threshold_sec=slow_threshold_sec,
        top_n=top_n,
    )
    return summary.__dict__


@router.get("/rag-metrics/trace-bundle", response_model=RagTraceBundleResponse)
def get_rag_trace_bundle(
    request_id: str = Query(..., min_length=1, max_length=200, description="X-Request-ID to export"),
    window_minutes: int = Query(default=24 * 60, ge=1, le=7 * 24 * 60),
    max_bytes: int = Query(default=5_000_000, ge=100_000, le=50_000_000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    _ensure_admin(db, tenant_id, account_id)
    bundle = build_rag_trace_bundle(
        tenant_id=str(tenant_id),
        request_id=request_id,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="trace bundle not found for request_id")
    return bundle.__dict__


@router.get("/ingestion/summary", response_model=IngestionDashboardSummaryResponse)
def get_ingestion_dashboard_summary(
    window_hours: int = Query(default=24, ge=1, le=30 * 24),
    bucket_minutes: int = Query(default=60, ge=1, le=30 * 24 * 60),
    dataset_id: UUID | None = Query(default=None, description="Optional dataset_id filter"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return ingestion throughput + error taxonomy aggregates (admin-only, PII-safe).

    Notes:
    - Uses coarse time buckets (hour/day) for stability.
    - Normalizes error messages into "reason keys" to avoid leaking raw exception details.
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.ingestion_dashboard_service import summarize_ingestion_dashboard

    return summarize_ingestion_dashboard(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        window_hours=int(window_hours or 24),
        bucket_minutes=int(bucket_minutes or 60),
    )


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
