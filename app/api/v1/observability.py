"""
Observability endpoints (admin-only).

Currently provides a small, PII-safe dashboard summary for RAG metrics based on the
JSONL metrics log (ENABLE_METRICS_LOG / METRICS_LOG_PATH).
"""


from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.utils.response_headers import download_response_headers
from app.core.config import settings
from app.core.database import get_db
from app.services.corpus_cache_tokens import invalidate_dataset_cache_namespace
from app.services.dataset_service import DatasetService
from app.services.metrics_logger import log_metrics
from app.services.ops_config_snapshot_service import build_ops_config_snapshot
from app.services.periodic_job_freshness_service import build_periodic_job_freshness_snapshot
from app.services.rag_metrics_dashboard import (
    build_rag_trace_bundle,
    build_rag_trace_bundle_diff,
    summarize_rag_cost_attribution,
    summarize_rag_metrics,
    summarize_rag_query_analytics,
)
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


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
    retrieval_candidate_cache_hit_count: int = 0
    retrieval_candidate_cache_store_ok_count: int = 0
    retrieval_candidate_cache_backend_counts: dict[str, int] = {}
    retrieval_candidate_cache_skip_reason_counts: dict[str, int] = {}
    retrieval_rerank_skip_reason_counts: dict[str, int] = {}
    retrieval_mode_counts: dict[str, int] = {}
    hit_type_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    timeseries: dict[str, list[Any]] = {}


class FrontendWebVitalReportRequest(BaseModel):
    name: Literal["LCP", "CLS", "FID", "INP"]
    value: float
    rating: str | None = Field(default=None, max_length=32)
    id: str | None = Field(default=None, max_length=200)
    navigation_type: str | None = Field(default=None, max_length=64)
    page: str | None = Field(default=None, max_length=500)


class FrontendTraceReportRequest(BaseModel):
    event: str = Field(min_length=1, max_length=120)
    duration_ms: float = Field(ge=0, le=600000)
    component: str | None = Field(default=None, max_length=120)
    page: str | None = Field(default=None, max_length=500)
    input_node_count: int | None = Field(default=None, ge=0)
    input_link_count: int | None = Field(default=None, ge=0)
    output_node_count: int | None = Field(default=None, ge=0)
    output_link_count: int | None = Field(default=None, ge=0)
    active_filter_count: int | None = Field(default=None, ge=0)


class OnlineQualitySummaryResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    bucket_minutes: int
    truncated: bool
    record_count: int
    sample_count: int
    faithfulness_det_avg: float | None = None
    chunk_utilization_avg: float | None = None
    timeseries: dict[str, list[Any]] = {}
    alerts: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/frontend-vitals", status_code=202, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def report_frontend_web_vital(
    body: FrontendWebVitalReportRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    log_metrics(
        {
            "event": "frontend_web_vital",
            "tenant_id": str(tenant_id),
            "account_id": str(account_id),
            "metric_name": body.name,
            "metric_value": float(body.value),
            "metric_rating": body.rating,
            "metric_id": body.id,
            "navigation_type": body.navigation_type,
            "page": body.page,
            "user_agent": http_request.headers.get("user-agent"),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    return Response(status_code=202)


@router.post("/frontend-traces", status_code=202, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def report_frontend_trace(
    body: FrontendTraceReportRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    log_metrics(
        {
            "event": "frontend_trace",
            "tenant_id": str(tenant_id),
            "account_id": str(account_id),
            "trace_event": body.event,
            "duration_ms": float(body.duration_ms),
            "component": body.component,
            "page": body.page,
            "input_node_count": body.input_node_count,
            "input_link_count": body.input_link_count,
            "output_node_count": body.output_node_count,
            "output_link_count": body.output_link_count,
            "active_filter_count": body.active_filter_count,
            "user_agent": http_request.headers.get("user-agent"),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    return Response(status_code=202)


class QuerysetHealthRunsResponse(BaseModel):
    enabled: bool
    path: str
    total: int
    truncated: bool = False
    items: list[dict[str, Any]] = Field(default_factory=list)
    timeseries: dict[str, list[Any]] = Field(default_factory=dict)


class QuerysetHealthDiffResponse(BaseModel):
    diff: dict[str, Any] = Field(default_factory=dict)


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

    error_kind_counts: dict[str, int] = Field(default_factory=dict)
    top_zero_hit_queries: list[dict[str, Any]] = Field(default_factory=list)
    top_slow_queries: list[dict[str, Any]] = Field(default_factory=list)
    timeseries: dict[str, list[Any]] = Field(default_factory=dict)
    anomalies: list[dict[str, Any]] = Field(default_factory=list)


class RagCostAttributionResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int

    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    llm_model_counts: dict[str, int] = Field(default_factory=dict)
    llm_source_counts: dict[str, int] = Field(default_factory=dict)

    embed_query_tokens: int = 0
    embed_query_chars: int = 0
    embed_query_count: int = 0
    embed_provider_counts: dict[str, int] = Field(default_factory=dict)
    embed_model_counts: dict[str, int] = Field(default_factory=dict)

    retrieval_elapsed_avg_sec: float | None = None
    retrieval_elapsed_p95_sec: float | None = None
    rerank_elapsed_avg_sec: float | None = None
    rerank_elapsed_p95_sec: float | None = None
    retrieval_vector_backend_counts: dict[str, int] = Field(default_factory=dict)
    retrieval_query_count: int = 0


class RagTraceBundleResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    request_id: str
    records: list[dict[str, Any]] = Field(default_factory=list)


class _SchemaAliasedModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", serialization_alias="schema")

    @property
    def schema(self) -> str:
        return str(self.schema_)


class RagTraceBundleSummaryResponse(BaseModel):
    request_id: str
    window_minutes: int
    truncated: bool

    retrieval_config_hash: str | None = None
    retrieval_mode: str | None = None
    retrieval_requested_mode: str | None = None
    retrieval_auto_routed: bool | None = None
    retrieval_profile: str | None = None
    retrieval_top_k: int | None = None
    retrieval_alpha: float | None = None
    retrieval_enable_reranker: bool | None = None
    retrieval_reranker_provider: str | None = None
    retrieval_reranker_top_n: int | None = None
    retrieval_query_parallelism: int | None = None
    retrieval_query_count: int | None = None
    retrieval_elapsed_sec: float | None = None
    retrieval_error_kinds: dict[str, int] = Field(default_factory=dict)

    citations_count: int | None = None

    model_route: str | None = None
    model_used: str | None = None
    vector_backend: str | None = None


class RagTraceBundleDiffItem(BaseModel):
    key: str
    a: Any | None = None
    b: Any | None = None
    delta: float | None = None


class RagTraceBundleDiffResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    generated_at: datetime
    request_id_a: str
    request_id_b: str
    truncated: bool

    summary_a: RagTraceBundleSummaryResponse
    summary_b: RagTraceBundleSummaryResponse
    diff: list[RagTraceBundleDiffItem] = Field(default_factory=list)


class OpsConfigSnapshotResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    fingerprint: str
    config: dict[str, Any] = Field(default_factory=dict)


class TaskQueueObservabilitySnapshotResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    generated_at: datetime
    source: str

    enabled: bool
    queue_name: str

    broker_up: bool
    queue_depth: int | None = None
    workers_active: int | None = None

    heartbeat_interval_sec: float = 0.0
    heartbeat_ttl_sec: int = 0
    poll_interval_sec: float = 0.0
    recent_job_outcomes: list[dict[str, Any]] = Field(default_factory=list)

    error: str | None = None


class PeriodicJobFreshnessItemResponse(BaseModel):
    key: str
    action: str
    resource_type: str

    expected_interval_hours: int = 24
    stale_after_hours: int = 36

    last_created_at: datetime | None = None
    last_resource_id: str | None = None
    age_seconds: int | None = None
    stale: bool = True


class PeriodicJobFreshnessResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    generated_at: datetime
    tenant_id: str
    items: list[PeriodicJobFreshnessItemResponse] = Field(default_factory=list)


class SloWindowSnapshotResponse(BaseModel):
    window_minutes: int
    source: str
    rag_trace_count: int | None = None
    retrieval_p95_elapsed_sec: float | None = None
    retrieval_p99_elapsed_sec: float | None = None
    zero_hit_rate: float | None = None
    error_rate: float | None = None


class SloSnapshotResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    generated_at: datetime
    windows: list[SloWindowSnapshotResponse] = Field(default_factory=list)


class IndexAuditResponse(BaseModel):
    tenant_id: str
    dataset_id: str
    vector_backend: str = ""

    active_documents: int = 0
    active_chunks: int = 0

    vector_id_missing: int = 0

    vector_ids_checked: int = 0
    vector_ids_missing_in_backend: int = 0
    vector_ids_missing_in_backend_sample: list[str] = []

    milvus_ids_sampled: int = 0
    milvus_orphan_ids_sample: list[str] = []
    index_channels: dict[str, Any] = Field(default_factory=dict)


class IndexAuditReconcileRequest(BaseModel):
    dataset_id: UUID
    document_id: UUID | None = None


class IndexAuditReconcileResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    tenant_id: str
    dataset_id: str
    document_id: str | None = None
    scope: str
    status: str
    reason: str | None = None
    task_id: str | None = None
    current_index_readiness: dict[str, Any] | None = None


class IndexAuditReconcileStatusResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    tenant_id: str
    dataset_id: str
    document_id: str
    status: str
    reason: str | None = None
    legacy: bool = False
    ready: bool = False
    channel_rows_present: int = 0
    current_index_readiness: dict[str, Any] = Field(default_factory=dict)


class IndexAuditReconcileEnqueueRequest(BaseModel):
    dataset_id: UUID
    document_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=200)
    dry_run: bool = True


class IndexAuditReconcileEnqueueResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    job_name: str
    job_id: str
    tenant_id: str
    dataset_id: str
    document_id: str | None = None
    scope: str
    dry_run: bool
    limit: int
    status: str
    reason: str | None = None
    report_in_job_result: bool = True
    legacy_unknown_report_only: bool = True


def _audit_index_reconcile_request(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    document_id: UUID | None,
    scope: str,
    status: str,
    dry_run: bool | None = None,
    limit: int | None = None,
    job_id: str | None = None,
) -> None:
    """Persist a PII-safe repair-request audit event without blocking the request."""
    try:
        from app.services.audit_log_service import audit_log_event

        details: dict[str, Any] = {
            "dataset_id": str(dataset_id),
            "document_id": str(document_id) if document_id is not None else None,
            "scope": str(scope),
            "status": str(status),
            "job_id": str(job_id)[:255] if job_id else None,
        }
        if dry_run is not None:
            details["dry_run"] = bool(dry_run)
        if limit is not None:
            details["limit"] = int(limit)
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="index_audit.reconcile.request",
            resource_type="document" if document_id is not None else "dataset",
            resource_id=str(document_id or dataset_id),
            details=details,
        )
        db.commit()
    except Exception:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


class IndexDriftItemResponse(BaseModel):
    id: str
    tenant_id: str
    dataset_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    operation: str
    channel: str
    strictness: str
    status: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)
    reconcile_task_id: str | None = None
    replay_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_replayed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None


class IndexDriftListResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    items: list[IndexDriftItemResponse] = Field(default_factory=list)


class IndexDriftResolveRequest(BaseModel):
    resolution_note: str = Field(default="", max_length=2000)


class IngestionDashboardSummaryResponse(BaseModel):
    window_hours: int
    bucket_minutes: int
    window_start: datetime
    window_end: datetime
    dataset_id: str | None = None

    created_count: int = 0
    by_status: dict[str, int] = {}
    by_stage_processing: dict[str, int] = {}
    avg_completed_latency_sec: float | None = None

    top_error_reasons: dict[str, int] = {}
    timeseries: dict[str, list[Any]] = {}


class DepsDiagnosticsResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    generated_at: datetime

    postgres: dict[str, Any] = Field(default_factory=dict)
    redis: dict[str, Any] = Field(default_factory=dict)
    minio: dict[str, Any] = Field(default_factory=dict)
    milvus: dict[str, Any] = Field(default_factory=dict)


class DatasetCacheInvalidationResponse(BaseModel):
    dataset_id: str
    previous_corpus_cache_token: str | None = None
    current_corpus_cache_token: str | None = None
    invalidated_at: datetime
    evidence_post_rerank_memory_cleared: bool = False
    note: str = ""


class PerfSuiteRunRequest(BaseModel):
    iterations: int = Field(default=10, ge=1, le=200, description="Iterations per case (bounded)")
    timeout_sec: float = Field(default=2.0, ge=0.05, le=10.0, description="Timeout per request in seconds (bounded)")


class PerfSuiteRunResponse(_SchemaAliasedModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    baseline_path: str
    policy_path: str
    baseline_ts: str = ""
    current_report: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)


def _serialize_index_drift_item(item: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(item, "id", "") or ""),
        "tenant_id": str(getattr(item, "tenant_id", "") or ""),
        "dataset_id": str(getattr(item, "dataset_id", "") or "") or None,
        "document_id": str(getattr(item, "document_id", "") or "") or None,
        "chunk_id": str(getattr(item, "chunk_id", "") or "") or None,
        "operation": str(getattr(item, "operation", "") or ""),
        "channel": str(getattr(item, "channel", "") or ""),
        "strictness": str(getattr(item, "strictness", "") or ""),
        "status": str(getattr(item, "status", "") or ""),
        "reason": str(getattr(item, "reason", "") or ""),
        "details": dict(getattr(item, "details", {}) or {}),
        "reconcile_task_id": str(getattr(item, "reconcile_task_id", "") or "") or None,
        "replay_count": int(getattr(item, "replay_count", 0) or 0),
        "created_at": getattr(item, "created_at", None),
        "updated_at": getattr(item, "updated_at", None),
        "last_replayed_at": getattr(item, "last_replayed_at", None),
        "resolved_at": getattr(item, "resolved_at", None),
        "resolved_by": str(getattr(item, "resolved_by", "") or "") or None,
        "resolution_note": str(getattr(item, "resolution_note", "") or "") or None,
    }


@router.get("/rag-metrics/summary", response_model=RagMetricsSummaryResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_metrics_summary(
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_metrics(tenant_id=str(tenant_id), window_minutes=window_minutes, max_bytes=max_bytes)
    # Dataclass -> dict (safe fields only by construction).
    return summary.__dict__


@router.get(
    "/online-quality/summary",
    response_model=OnlineQualitySummaryResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_online_quality_summary(
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 60,
    bucket_minutes: Annotated[int, Query(ge=1, le=60)] = 5,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Online quality snapshot (sampled, deterministic, PII-minimal).

    This reads the shared metrics JSONL log and aggregates `event=="online_eval"` records.
    """
    _ensure_admin(db, tenant_id, account_id)
    from app.services.online_eval_service import summarize_online_quality

    summary = summarize_online_quality(
        tenant_id=str(tenant_id),
        window_minutes=window_minutes,
        bucket_minutes=bucket_minutes,
        max_bytes=max_bytes,
    )
    return summary.__dict__


@router.get(
    "/queryset-health/runs",
    response_model=QuerysetHealthRunsResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_queryset_health_runs(
    limit: Annotated[int, Query(ge=1, le=500)] = 90,
    profile_hash: Annotated[str | None, Query(description="Optional retrieval profile hash to filter history")] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List query-set health snapshots from the local history JSONL file.

    This is intended for UI diagnostics and CI review. Data is PII-minimal by construction
    (questions are clipped and bounded in the snapshot schema).
    """
    _ensure_admin(db, tenant_id, account_id)

    from pathlib import Path

    from app.core.config import settings
    from app.services.queryset_health_service import load_queryset_health_history

    path_str = str(getattr(settings, "QUERYSET_HEALTH_HISTORY_PATH", "./runs/queryset_health/history.jsonl") or "")
    path = Path(path_str)

    rows = load_queryset_health_history(path)
    if profile_hash:
        ph = str(profile_hash or "").strip()
        if ph:
            rows = [r for r in rows if isinstance(r, dict) and str(r.get("profile_hash") or "").strip() == ph]

    total = int(len(rows))
    cap = max(1, int(limit or 1))
    truncated = total > cap
    visible = rows[-cap:] if cap else rows

    # Build a compact timeseries for charts (chronological order).
    ts_rows = visible
    ts_ms: list[int] = []
    hit_at_k: list[float | None] = []
    mrr: list[float | None] = []
    ndcg: list[float | None] = []
    p95_latency_ms: list[float | None] = []
    miss_rate: list[float | None] = []
    weak_hit_rate: list[float | None] = []
    status: list[str] = []

    def _to_ms(raw: Any) -> int:
        ts = str(raw or "").strip()
        if not ts:
            return 0
        try:
            # fromisoformat does not accept trailing "Z".
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    for r in ts_rows:
        if not isinstance(r, dict):
            continue
        ts_ms.append(_to_ms(r.get("generated_at")))

        metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
        risk = r.get("risk") if isinstance(r.get("risk"), dict) else {}

        def _f(v: Any) -> float | None:
            try:
                if v is None or isinstance(v, bool):
                    return None
                return float(v)
            except Exception:
                return None

        hit_at_k.append(_f(metrics.get("hit_at_k")))
        mrr.append(_f(metrics.get("mrr")))
        ndcg.append(_f(metrics.get("ndcg_at_k")))
        p95_latency_ms.append(_f(metrics.get("p95_latency_ms")))
        miss_rate.append(_f(risk.get("miss_rate")))
        weak_hit_rate.append(_f(risk.get("weak_hit_rate")))
        status.append(str(r.get("status") or "unknown"))

    # Return newest-first list for the table.
    items = list(reversed([dict(r) for r in visible if isinstance(r, dict)]))

    return QuerysetHealthRunsResponse(
        enabled=bool(path.exists()),
        path=str(path),
        total=total,
        truncated=bool(truncated),
        items=items,
        timeseries={
            "ts_ms": ts_ms,
            "hit_at_k": hit_at_k,
            "mrr": mrr,
            "ndcg_at_k": ndcg,
            "p95_latency_ms": p95_latency_ms,
            "miss_rate": miss_rate,
            "weak_hit_rate": weak_hit_rate,
            "status": status,
        },
    )


@router.get(
    "/queryset-health/diff",
    response_model=QuerysetHealthDiffResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def diff_queryset_health_runs(
    baseline_generated_at: Annotated[str, Query(min_length=1, max_length=64)],
    current_generated_at: Annotated[str, Query(min_length=1, max_length=64)],
    max_hard_case_ids: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    from pathlib import Path

    from app.core.config import settings
    from app.services.queryset_health_diff_service import diff_queryset_health_snapshots
    from app.services.queryset_health_service import load_queryset_health_history

    path_str = str(getattr(settings, "QUERYSET_HEALTH_HISTORY_PATH", "./runs/queryset_health/history.jsonl") or "")
    path = Path(path_str)
    rows = load_queryset_health_history(path)

    base_ts = str(baseline_generated_at or "").strip()
    curr_ts = str(current_generated_at or "").strip()
    if not base_ts or not curr_ts:
        raise HTTPException(status_code=400, detail="baseline_generated_at and current_generated_at are required")

    baseline = next((r for r in rows if isinstance(r, dict) and str(r.get("generated_at") or "").strip() == base_ts), None)
    current = next((r for r in rows if isinstance(r, dict) and str(r.get("generated_at") or "").strip() == curr_ts), None)
    if baseline is None or current is None:
        raise HTTPException(status_code=404, detail="baseline/current snapshot not found in history")

    diff = diff_queryset_health_snapshots(baseline=baseline, current=current, max_hard_case_ids=int(max_hard_case_ids or 20))
    return QuerysetHealthDiffResponse(diff=diff)


@router.get("/rag-metrics/query-analytics", response_model=RagQueryAnalyticsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_query_analytics(
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 60,
    slow_threshold_sec: Annotated[float, Query(ge=0.0, le=120.0)] = 2.0,
    top_n: Annotated[int, Query(ge=1, le=200)] = 20,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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


@router.get("/rag-metrics/tail", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_metrics_tail(
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 24 * 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Download a redacted tail of the metrics JSONL log (gzip).

    Intended for offline incident/support debugging. Always strips raw text fields.
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.rag_metrics_dashboard import build_redacted_metrics_tail_gzip

    payload = build_redacted_metrics_tail_gzip(
        tenant_id=str(tenant_id),
        window_minutes=int(window_minutes),
        max_bytes=int(max_bytes),
    )

    ts = datetime.now(UTC).replace(tzinfo=None).strftime("%Y%m%dT%H%M%SZ")
    filename = f"rag-metrics-tail.{ts}.jsonl.gz"
    return Response(
        content=payload,
        media_type="application/gzip",
        headers=download_response_headers(filename),
    )


@router.get("/rag-metrics/cost-attribution", response_model=RagCostAttributionResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_cost_attribution(
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_cost_attribution(tenant_id=str(tenant_id), window_minutes=window_minutes, max_bytes=max_bytes)
    return summary.__dict__


@router.get("/diagnostics/deps", response_model=DepsDiagnosticsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_deps_diagnostics_snapshot(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Snapshot dependency connectivity + latency + versions (admin-only, PII-safe).
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.deps_diagnostics_service import build_deps_diagnostics_snapshot

    snap = build_deps_diagnostics_snapshot()
    return snap.__dict__


@router.get("/rag-metrics/trace-bundle", response_model=RagTraceBundleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_trace_bundle(
    request_id: Annotated[str, Query(..., min_length=1, max_length=200, description="X-Request-ID to export")],
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 24 * 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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


@router.get("/rag-metrics/trace-bundle/diff", response_model=RagTraceBundleDiffResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_rag_trace_bundle_diff(
    request_id_a: Annotated[str, Query(..., min_length=1, max_length=200, description="X-Request-ID A to compare")],
    request_id_b: Annotated[str, Query(..., min_length=1, max_length=200, description="X-Request-ID B to compare")],
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 24 * 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    a = str(request_id_a or "").strip()
    b = str(request_id_b or "").strip()
    if not a or not b:
        raise HTTPException(status_code=400, detail="request_id_a and request_id_b are required")
    if a == b:
        raise HTTPException(status_code=400, detail="request_id_a and request_id_b must be different")

    bundle_a = build_rag_trace_bundle(
        tenant_id=str(tenant_id),
        request_id=a,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    if bundle_a is None:
        raise HTTPException(status_code=404, detail="trace bundle not found for request_id_a")

    bundle_b = build_rag_trace_bundle(
        tenant_id=str(tenant_id),
        request_id=b,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )
    if bundle_b is None:
        raise HTTPException(status_code=404, detail="trace bundle not found for request_id_b")

    diff = build_rag_trace_bundle_diff(bundle_a=bundle_a, bundle_b=bundle_b)
    return diff.__dict__


@router.get("/config/snapshot", response_model=OpsConfigSnapshotResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_ops_config_snapshot(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    snap = build_ops_config_snapshot()
    return snap.__dict__


@router.post("/cache/datasets/{dataset_id}/invalidate", response_model=DatasetCacheInvalidationResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def invalidate_dataset_cache_namespace_endpoint(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    try:
        return invalidate_dataset_cache_namespace(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/periodic-jobs/freshness", response_model=PeriodicJobFreshnessResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_periodic_job_freshness(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Periodic job freshness snapshot (admin-only, PII-safe).

    Summarizes the latest "daily audit/access review" events written to audit logs and
    reports staleness/age for oncall dashboards.
    """
    _ensure_admin(db, tenant_id, account_id)
    return build_periodic_job_freshness_snapshot(db=db, tenant_id=tenant_id)


@router.get("/task-queue/snapshot", response_model=TaskQueueObservabilitySnapshotResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_task_queue_observability_snapshot(
    force_refresh: Annotated[bool, Query(description='Force refresh from broker (best-effort)')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Task queue observability snapshot (admin-only, PII-safe).

    Includes:
    - Broker health (ping)
    - Queue depth
    - Active worker count (heartbeat-based, aggregated)
    - Recent standardized job outcomes (best-effort)
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.task_queue_observability_service import get_task_queue_observability_snapshot

    snap = await get_task_queue_observability_snapshot(force_refresh=bool(force_refresh))
    return snap.__dict__


@router.get("/slo/snapshot", response_model=SloSnapshotResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_slo_snapshot(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    from app.services.slo_snapshot_service import build_slo_snapshot

    return await build_slo_snapshot(tenant_id=str(tenant_id))


@router.get("/ingestion/summary", response_model=IngestionDashboardSummaryResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_ingestion_dashboard_summary(
    window_hours: Annotated[int, Query(ge=1, le=30 * 24)] = 24,
    bucket_minutes: Annotated[int, Query(ge=1, le=30 * 24 * 60)] = 60,
    dataset_id: Annotated[UUID | None, Query(description='Optional dataset_id filter')] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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


@router.get("/index-audit", response_model=IndexAuditResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_index_audit(
    dataset_id: Annotated[UUID, Query(..., description="Dataset id to audit (required)")],
    max_check_ids: Annotated[int, Query(ge=0, le=50000, description='Max DB vector_ids to existence-check')] = 5000,
    milvus_list_limit: Annotated[int, Query(ge=0, le=50000, description='Max Milvus ids to sample for orphans')] = 2000,
    sample_limit: Annotated[int, Query(ge=0, le=200, description='Max sample ids to return per category')] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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


@router.post("/index-audit/reconcile", response_model=IndexAuditReconcileResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def reconcile_index_audit(
    payload: IndexAuditReconcileRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Minimal admin-triggered reconcile entrypoint for index audit findings.

    Current worker support is document-scoped only. Dataset-only requests remain
    explicitly unsupported rather than broadening to a tenant-wide rebuild.
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.index_audit_service import (
        enqueue_index_audit_reconcile,
        get_index_audit_reconcile_document_state,
    )

    current_index_readiness: dict[str, Any] | None = None
    if payload.document_id is not None:
        state = get_index_audit_reconcile_document_state(
            db=db,
            tenant_id=tenant_id,
            dataset_id=payload.dataset_id,
            document_id=payload.document_id,
        )
        if state is None:
            raise HTTPException(status_code=404, detail="document not found in dataset")
        current_index_readiness = (
            dict(state.get("current_index_readiness") or {})
            if isinstance(state.get("current_index_readiness"), dict)
            else None
        )
        if bool(state.get("already_ready")):
            response = {
                "schema": "mimirq.index_audit_reconcile.v1",
                "tenant_id": str(tenant_id),
                "dataset_id": str(payload.dataset_id),
                "document_id": str(payload.document_id),
                "scope": "document",
                "status": "noop_ready",
                "reason": "document_index_channels_already_ready",
                "task_id": None,
                "current_index_readiness": current_index_readiness,
            }
            _audit_index_reconcile_request(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=payload.dataset_id,
                document_id=payload.document_id,
                scope="document",
                status="noop_ready",
            )
            return response

    result = await enqueue_index_audit_reconcile(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        requested_by=account_id,
    )
    result["current_index_readiness"] = current_index_readiness
    _audit_index_reconcile_request(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        scope=str(result.get("scope") or ("document" if payload.document_id is not None else "dataset")),
        status=str(result.get("status") or "unknown"),
        job_id=str(result.get("task_id") or "") or None,
    )
    return result


@router.get("/index-audit/reconcile-status", response_model=IndexAuditReconcileStatusResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_index_audit_reconcile_status(
    dataset_id: Annotated[UUID, Query(..., description="Dataset id for the reconciled document")],
    document_id: Annotated[UUID, Query(..., description="Document id to inspect reconcile readiness for")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Read current persisted document index-channel readiness for a reconcile target.

    This does not infer queue completion from task ids; it reports only durable
    `document_index_channels` state for the document's current pipeline.
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.index_audit_service import get_index_audit_reconcile_document_status

    status = get_index_audit_reconcile_document_status(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
    )
    if status is None:
        raise HTTPException(status_code=404, detail="document not found in dataset")
    return status


@router.post("/index-audit/reconcile-jobs", response_model=IndexAuditReconcileEnqueueResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def enqueue_index_audit_reconcile_job_endpoint(
    payload: IndexAuditReconcileEnqueueRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Manually enqueue a bounded tenant+dataset scoped index-audit reconcile job.

    This never schedules a cross-tenant scan. Legacy/no-row documents remain
    report-only inside the job and are not auto-rebuilt.
    """
    _ensure_admin(db, tenant_id, account_id)
    DatasetService.get_dataset(db, tenant_id, payload.dataset_id)

    if payload.document_id is not None:
        from app.services.index_audit_service import get_index_audit_reconcile_document_state

        state = get_index_audit_reconcile_document_state(
            db=db,
            tenant_id=tenant_id,
            dataset_id=payload.dataset_id,
            document_id=payload.document_id,
        )
        if state is None:
            raise HTTPException(status_code=404, detail="document not found in dataset")

    from app.tasks.queue import enqueue_index_audit_reconcile_job

    scope = "document" if payload.document_id is not None else "dataset"
    job_id = (
        f"index-audit-reconcile-job:{tenant_id}:{payload.dataset_id}:"
        f"{payload.document_id or 'dataset'}:{int(payload.limit)}:{int(bool(payload.dry_run))}"
    )
    queued_job_id = await enqueue_index_audit_reconcile_job(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        requested_by=account_id,
        limit=int(payload.limit),
        dry_run=bool(payload.dry_run),
        job_id=job_id,
    )
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        response = {
            "schema": "mimirq.index_audit_reconcile_enqueue.v1",
            "job_name": "reconcile_index_audit_job",
            "job_id": job_id,
            "tenant_id": str(tenant_id),
            "dataset_id": str(payload.dataset_id),
            "document_id": str(payload.document_id) if payload.document_id is not None else None,
            "scope": scope,
            "dry_run": bool(payload.dry_run),
            "limit": int(payload.limit),
            "status": "not_enqueued",
            "reason": "task_queue_disabled",
            "report_in_job_result": True,
            "legacy_unknown_report_only": True,
        }
    else:
        response = {
            "schema": "mimirq.index_audit_reconcile_enqueue.v1",
            "job_name": "reconcile_index_audit_job",
            "job_id": str(queued_job_id or job_id),
            "tenant_id": str(tenant_id),
            "dataset_id": str(payload.dataset_id),
            "document_id": str(payload.document_id) if payload.document_id is not None else None,
            "scope": scope,
            "dry_run": bool(payload.dry_run),
            "limit": int(payload.limit),
            "status": ("enqueued" if queued_job_id else "already_queued"),
            "reason": (None if queued_job_id else "duplicate_job"),
            "report_in_job_result": True,
            "legacy_unknown_report_only": True,
        }
    _audit_index_reconcile_request(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        scope=scope,
        status=str(response["status"]),
        dry_run=bool(payload.dry_run),
        limit=int(payload.limit),
        job_id=str(response["job_id"]),
    )
    return response


@router.get("/embedding-drift/snapshot", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_embedding_drift_snapshot(
    dataset_id: Annotated[UUID | None, Query(description="Optional dataset_id scope")] = None,
    document_id: Annotated[UUID | None, Query(description="Optional document_id scope")] = None,
    sample_n: Annotated[int, Query(ge=1, le=2000, description="Max chunks sampled (bounded)")] = 200,
    drift_threshold: Annotated[float, Query(ge=0.0, le=1.0, description="Cosine distance threshold")] = 0.05,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Embedding drift snapshot (admin-only, PII-safe).

    Compares stored vectors with re-embedded vectors for a bounded sample of active chunks
    and returns aggregate drift statistics. Output never includes chunk/document identifiers
    or raw content.
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.embedding_drift_monitor import run_embedding_drift_monitor

    return run_embedding_drift_monitor(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        sample_n=int(sample_n or 0),
        drift_threshold=float(drift_threshold),
    )


@router.post("/perf-suite/run", response_model=PerfSuiteRunResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def run_perf_suite(
    payload: PerfSuiteRunRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Run a minimal, PII-safe perf suite and diff vs the checked-in baseline (admin-only).

    Intended for ad-hoc diagnostics. Nightly gating is implemented in GitHub Actions.
    """
    _ensure_admin(db, tenant_id, account_id)

    from app.services.perf_suite_run_service import run_minimal_perf_suite_report_and_diff

    try:
        return run_minimal_perf_suite_report_and_diff(
            iterations=int(payload.iterations or 0),
            timeout_sec=float(payload.timeout_sec or 0.0),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"perf baseline/policy not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"perf suite run failed: {exc}") from exc


@router.get("/index-drift", response_model=IndexDriftListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_index_drift(
    dataset_id: Annotated[UUID | None, Query(description='Optional dataset UUID filter')] = None,
    status: Annotated[str, Query(description='open | resolved | all')] = "open",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    from app.services.index_audit_service import list_index_drift_items

    rows = list_index_drift_items(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status=status,
        limit=limit,
    )
    return {
        "schema": "mimirq.index_drift_list.v1",
        "items": [_serialize_index_drift_item(row) for row in rows],
    }


@router.post("/index-drift/{item_id}/resolve", response_model=IndexDriftItemResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def resolve_index_drift(
    item_id: UUID,
    payload: IndexDriftResolveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    from app.services.index_audit_service import resolve_index_drift_item

    item = resolve_index_drift_item(
        db=db,
        tenant_id=tenant_id,
        item_id=item_id,
        resolved_by=account_id,
        resolution_note=str(payload.resolution_note or ""),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="index drift item not found")
    return _serialize_index_drift_item(item)
