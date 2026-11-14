"""
Observability endpoints (admin-only).

Metrics, trace exports, dependency snapshots and bounded index repair requests
retain their tenant scope, permission checks and PII-safe producer boundaries.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.system import (
    DatasetCacheInvalidationResponse,
    DepsDiagnosticsResponse,
    EmbeddingDriftParams,
    FrontendTraceReportRequest,
    FrontendWebVitalReportRequest,
    IndexAuditParams,
    IndexAuditReconcileEnqueueRequest,
    IndexAuditReconcileEnqueueResponse,
    IndexAuditReconcileRequest,
    IndexAuditReconcileResponse,
    IndexAuditReconcileStatusResponse,
    IndexAuditResponse,
    IndexDriftItemResponse,
    IndexDriftListParams,
    IndexDriftListResponse,
    IndexDriftResolveRequest,
    IndexReconcileStatusParams,
    IngestionDashboardSummaryResponse,
    IngestionSummaryParams,
    MetricsTailParams,
    MetricsWindowParams,
    OnlineQualitySummaryParams,
    OnlineQualitySummaryResponse,
    OpsConfigSnapshotResponse,
    PerfSuiteRunRequest,
    PerfSuiteRunResponse,
    PeriodicJobFreshnessResponse,
    QuerysetHealthDiffParams,
    QuerysetHealthDiffResponse,
    QuerysetHealthRunsParams,
    QuerysetHealthRunsResponse,
    QuerysetHealthTimeseries,
    RagCostAttributionResponse,
    RagMetricsSummaryResponse,
    RagQueryAnalyticsParams,
    RagQueryAnalyticsResponse,
    RagTraceBundleDiffParams,
    RagTraceBundleDiffResponse,
    RagTraceBundleParams,
    RagTraceBundleResponse,
    SloSnapshotResponse,
    TaskQueueObservabilitySnapshotResponse,
    TaskQueueSnapshotParams,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.utils import file_response_headers
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.corpus_cache_tokens import invalidate_dataset_cache_namespace
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

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.OBSERVABILITY_READ,
        detail="No permission to access observability dashboards",
    )


def _authorize_observability(tenant_id: UUID, account_id: str) -> None:
    with SessionLocal() as db:
        _ensure_admin(db, tenant_id, account_id)


def _prepare_index_reconcile(
    *, tenant_id: UUID, account_id: str, dataset_id: UUID, document_id: UUID | None, require_dataset: bool
) -> dict[str, Any] | None:
    with SessionLocal() as db:
        _ensure_admin(db, tenant_id, account_id)
        if document_id is None:
            if require_dataset:
                dataset_service.get_dataset(db, tenant_id, dataset_id)
            return None
        from app.services.index_audit_service import get_index_audit_reconcile_document_state

        state = get_index_audit_reconcile_document_state(
            db=db, tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id
        )
        if state is None:
            raise HTTPException(status_code=404, detail="document not found in dataset")
        return {
            "current_index_readiness": state["current_index_readiness"],
            "already_ready": state["already_ready"],
        }


def _filter_queryset_health_rows(rows: list[dict[str, Any]], *, profile_hash: str | None) -> list[dict[str, Any]]:
    ph = profile_hash.strip() if profile_hash is not None else None
    if not ph:
        return rows
    return [row for row in rows if row.get("profile_hash") is not None and row["profile_hash"].strip() == ph]


def _queryset_health_ts_to_ms(raw: Any) -> int:
    if raw is None:
        return 0
    ts = str(raw).strip()
    if not ts:
        return 0
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError, OSError):
        return 0


def _queryset_health_optional_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _build_queryset_health_timeseries(rows: list[dict[str, Any]]) -> QuerysetHealthTimeseries:
    timeseries = QuerysetHealthTimeseries(
        ts_ms=[],
        hit_at_k=[],
        mrr=[],
        ndcg_at_k=[],
        p95_latency_ms=[],
        miss_rate=[],
        weak_hit_rate=[],
        status=[],
    )
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
        timeseries.ts_ms.append(_queryset_health_ts_to_ms(row.get("generated_at")))
        timeseries.hit_at_k.append(_queryset_health_optional_float(metrics.get("hit_at_k")))
        timeseries.mrr.append(_queryset_health_optional_float(metrics.get("mrr")))
        timeseries.ndcg_at_k.append(_queryset_health_optional_float(metrics.get("ndcg_at_k")))
        timeseries.p95_latency_ms.append(_queryset_health_optional_float(metrics.get("p95_latency_ms")))
        timeseries.miss_rate.append(_queryset_health_optional_float(risk.get("miss_rate")))
        timeseries.weak_hit_rate.append(_queryset_health_optional_float(risk.get("weak_hit_rate")))
        timeseries.status.append(str(row.get("status") or "unknown"))
    return timeseries


@router.post("/frontend-vitals", status_code=202)
def report_frontend_web_vital(
    body: FrontendWebVitalReportRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset_service.ensure_member(db, tenant_id, account_id)

    log_metrics(
        {
            "event": "frontend_web_vital",
            "tenant_id": str(tenant_id),
            "account_id": account_id,
            "metric_name": body.name,
            "metric_value": body.value,
            "metric_rating": body.rating,
            "metric_id": body.id,
            "navigation_type": body.navigation_type,
            "page": body.page,
            "user_agent": http_request.headers.get("user-agent"),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    return Response(status_code=202)


@router.post("/frontend-traces", status_code=202)
def report_frontend_trace(
    body: FrontendTraceReportRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset_service.ensure_member(db, tenant_id, account_id)

    log_metrics(
        {
            "event": "frontend_trace",
            "tenant_id": str(tenant_id),
            "account_id": account_id,
            "trace_event": body.event,
            "duration_ms": body.duration_ms,
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


def _audit_index_reconcile_in_session(
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
    """Commit the repair audit in its worker-owned session; log audit failures."""
    from app.services.audit_log_service import audit_log_event

    with SessionLocal() as db:
        try:
            details: dict[str, Any] = {
                "dataset_id": str(dataset_id),
                "document_id": str(document_id) if document_id is not None else None,
                "scope": scope,
                "status": status,
                "job_id": job_id[:255] if job_id is not None else None,
            }
            if dry_run is not None:
                details["dry_run"] = dry_run
            if limit is not None:
                details["limit"] = limit
            audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action="index_audit.reconcile.request",
                resource_type="document" if document_id is not None else "dataset",
                resource_id=str(document_id if document_id is not None else dataset_id),
                details=details,
            )
            db.commit()
        except SQLAlchemyError as exc:
            try:
                db.rollback()
            except SQLAlchemyError as rollback_error:
                logger.warning("Index audit rollback failed (%s)", type(rollback_error).__name__, exc_info=True)
            logger.warning("Index audit event commit failed (%s)", type(exc).__name__, exc_info=True)


@router.get(
    "/rag-metrics/summary",
    response_model=RagMetricsSummaryResponse,
)
def get_rag_metrics_summary(
    params: Annotated[MetricsWindowParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_metrics(
        tenant_id=str(tenant_id),
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
    )
    return summary


@router.get(
    "/online-quality/summary",
    response_model=OnlineQualitySummaryResponse,
)
def get_online_quality_summary(
    params: Annotated[OnlineQualitySummaryParams, Query()],
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
        window_minutes=params.window_minutes,
        bucket_minutes=params.bucket_minutes,
        max_bytes=params.max_bytes,
    )
    return summary


@router.get(
    "/queryset-health/runs",
    response_model=QuerysetHealthRunsResponse,
)
def list_queryset_health_runs(
    params: Annotated[QuerysetHealthRunsParams, Query()],
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

    from app.services.queryset_health_service import load_queryset_health_history

    path = Path(settings.QUERYSET_HEALTH_HISTORY_PATH)
    rows = _filter_queryset_health_rows(load_queryset_health_history(path), profile_hash=params.profile_hash)
    total = len(rows)
    truncated = total > params.limit
    visible = rows[-params.limit :]

    # Return newest-first list for the table.
    items = list(reversed(visible))

    return QuerysetHealthRunsResponse(
        enabled=path.exists(),
        path=str(path),
        total=total,
        truncated=truncated,
        items=items,
        timeseries=_build_queryset_health_timeseries(visible),
    )


@router.get(
    "/queryset-health/diff",
    response_model=QuerysetHealthDiffResponse,
)
def diff_queryset_health_runs(
    params: Annotated[QuerysetHealthDiffParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    from pathlib import Path

    from app.services.queryset_health_diff_service import diff_queryset_health_snapshots
    from app.services.queryset_health_service import load_queryset_health_history

    path_str = str(settings.QUERYSET_HEALTH_HISTORY_PATH)
    path = Path(path_str)
    rows = load_queryset_health_history(path)

    base_ts = params.baseline_generated_at.strip()
    curr_ts = params.current_generated_at.strip()
    if not base_ts or not curr_ts:
        raise HTTPException(status_code=400, detail="baseline_generated_at and current_generated_at are required")

    baseline = next(
        (r for r in rows if r.get("generated_at") == base_ts),
        None,
    )
    current = next(
        (r for r in rows if r.get("generated_at") == curr_ts),
        None,
    )
    if baseline is None or current is None:
        raise HTTPException(status_code=404, detail="baseline/current snapshot not found in history")

    diff = diff_queryset_health_snapshots(
        baseline=baseline,
        current=current,
        max_hard_case_ids=params.max_hard_case_ids,
    )
    return QuerysetHealthDiffResponse(diff=diff)


@router.get(
    "/rag-metrics/query-analytics",
    response_model=RagQueryAnalyticsResponse,
)
def get_rag_query_analytics(
    params: Annotated[RagQueryAnalyticsParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_query_analytics(
        tenant_id=str(tenant_id),
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
        slow_threshold_sec=params.slow_threshold_sec,
        top_n=params.top_n,
    )
    return summary


@router.get("/rag-metrics/tail")
def get_rag_metrics_tail(
    params: Annotated[MetricsTailParams, Query()],
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
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
    )

    ts = datetime.now(UTC).replace(tzinfo=None).strftime("%Y%m%dT%H%M%SZ")
    filename = f"rag-metrics-tail.{ts}.jsonl.gz"
    return Response(
        content=payload,
        media_type="application/gzip",
        headers=file_response_headers(filename),
    )


@router.get(
    "/rag-metrics/cost-attribution",
    response_model=RagCostAttributionResponse,
)
def get_rag_cost_attribution(
    params: Annotated[MetricsWindowParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    summary = summarize_rag_cost_attribution(
        tenant_id=str(tenant_id),
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
    )
    return summary


@router.get("/diagnostics/deps", response_model=DepsDiagnosticsResponse)
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
    return snap


@router.get(
    "/rag-metrics/trace-bundle",
    response_model=RagTraceBundleResponse,
)
def get_rag_trace_bundle(
    params: Annotated[RagTraceBundleParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    bundle = build_rag_trace_bundle(
        tenant_id=str(tenant_id),
        request_id=params.request_id,
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="trace bundle not found for request_id")
    return bundle


@router.get(
    "/rag-metrics/trace-bundle/diff",
    response_model=RagTraceBundleDiffResponse,
)
def get_rag_trace_bundle_diff(
    params: Annotated[RagTraceBundleDiffParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    a = params.request_id_a.strip()
    b = params.request_id_b.strip()
    if not a or not b:
        raise HTTPException(status_code=400, detail="request_id_a and request_id_b are required")
    if a == b:
        raise HTTPException(status_code=400, detail="request_id_a and request_id_b must be different")

    bundle_a = build_rag_trace_bundle(
        tenant_id=str(tenant_id),
        request_id=a,
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
    )
    if bundle_a is None:
        raise HTTPException(status_code=404, detail="trace bundle not found for request_id_a")

    bundle_b = build_rag_trace_bundle(
        tenant_id=str(tenant_id),
        request_id=b,
        window_minutes=params.window_minutes,
        max_bytes=params.max_bytes,
    )
    if bundle_b is None:
        raise HTTPException(status_code=404, detail="trace bundle not found for request_id_b")

    diff = build_rag_trace_bundle_diff(bundle_a=bundle_a, bundle_b=bundle_b)
    return diff


@router.get("/config/snapshot", response_model=OpsConfigSnapshotResponse)
def get_ops_config_snapshot(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    snap = build_ops_config_snapshot()
    return snap


@router.post(
    "/cache/datasets/{dataset_id}/invalidate",
    response_model=DatasetCacheInvalidationResponse,
)
def invalidate_dataset_cache_namespace_endpoint(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)
    try:
        result = invalidate_dataset_cache_namespace(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        )
        db.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/periodic-jobs/freshness",
    response_model=PeriodicJobFreshnessResponse,
)
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


@router.get(
    "/task-queue/snapshot",
    response_model=TaskQueueObservabilitySnapshotResponse,
)
async def get_task_queue_observability_snapshot(
    params: Annotated[TaskQueueSnapshotParams, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    """
    Task queue observability snapshot (admin-only, PII-safe).

    Includes:
    - Broker health (ping)
    - Queue depth
    - Active worker count (heartbeat-based, aggregated)
    - Recent standardized job outcomes (best-effort)
    """
    await run_blocking_in_thread(_authorize_observability, tenant_id, account_id)

    from app.services.task_queue_observability_service import get_task_queue_observability_snapshot

    snap = await get_task_queue_observability_snapshot(force_refresh=params.force_refresh)
    return snap


@router.get("/slo/snapshot", response_model=SloSnapshotResponse)
async def get_slo_snapshot(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    await run_blocking_in_thread(_authorize_observability, tenant_id, account_id)
    from app.services.slo_snapshot_service import build_slo_snapshot

    return await build_slo_snapshot(tenant_id=str(tenant_id))


@router.get(
    "/ingestion/summary",
    response_model=IngestionDashboardSummaryResponse,
)
def get_ingestion_dashboard_summary(
    params: Annotated[IngestionSummaryParams, Query()],
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
        dataset_id=params.dataset_id,
        window_hours=params.window_hours,
        bucket_minutes=params.bucket_minutes,
    )


@router.get("/index-audit", response_model=IndexAuditResponse)
def get_index_audit(
    params: Annotated[IndexAuditParams, Query()],
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
        dataset_id=params.dataset_id,
        max_check_ids=params.max_check_ids,
        milvus_list_limit=params.milvus_list_limit,
        sample_limit=params.sample_limit,
    )


@router.post(
    "/index-audit/reconcile",
    response_model=IndexAuditReconcileResponse,
)
async def reconcile_index_audit(
    payload: IndexAuditReconcileRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    """
    Minimal admin-triggered reconcile entrypoint for index audit findings.

    Current worker support is document-scoped only. Dataset-only requests remain
    explicitly unsupported rather than broadening to a tenant-wide rebuild.
    """
    state = await run_blocking_in_thread(
        _prepare_index_reconcile,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        require_dataset=False,
    )
    from app.services.index_audit_service import enqueue_index_audit_reconcile

    current_index_readiness: dict[str, Any] | None = None
    if state is not None:
        current_index_readiness = state["current_index_readiness"]
        if state["already_ready"]:
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
            await run_blocking_in_thread(
                _audit_index_reconcile_in_session,
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
    await run_blocking_in_thread(
        _audit_index_reconcile_in_session,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        scope=result["scope"],
        status=result["status"],
        job_id=result["task_id"],
    )
    return result


@router.get(
    "/index-audit/reconcile-status",
    response_model=IndexAuditReconcileStatusResponse,
)
def get_index_audit_reconcile_status(
    params: Annotated[IndexReconcileStatusParams, Query()],
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
        dataset_id=params.dataset_id,
        document_id=params.document_id,
    )
    if status is None:
        raise HTTPException(status_code=404, detail="document not found in dataset")
    return status


@router.post(
    "/index-audit/reconcile-jobs",
    response_model=IndexAuditReconcileEnqueueResponse,
)
async def enqueue_index_audit_reconcile_job_endpoint(
    payload: IndexAuditReconcileEnqueueRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    """
    Manually enqueue a bounded tenant+dataset scoped index-audit reconcile job.

    This never schedules a cross-tenant scan. Legacy/no-row documents remain
    report-only inside the job and are not auto-rebuilt.
    """
    await run_blocking_in_thread(
        _prepare_index_reconcile,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        require_dataset=True,
    )

    from app.tasks.queue import enqueue_index_audit_reconcile_job

    scope = "document" if payload.document_id is not None else "dataset"
    job_id = (
        f"index-audit-reconcile-job:{tenant_id}:{payload.dataset_id}:"
        f"{payload.document_id if payload.document_id is not None else 'dataset'}:"
        f"{payload.limit}:{int(payload.dry_run)}"
    )
    queued_job_id = await enqueue_index_audit_reconcile_job(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        requested_by=account_id,
        limit=payload.limit,
        dry_run=payload.dry_run,
        job_id=job_id,
    )
    if not settings.TASK_QUEUE_ENABLED:
        status = "not_enqueued"
        reason = "task_queue_disabled"
    elif queued_job_id is None:
        status = "already_queued"
        reason = "duplicate_job"
    else:
        status = "enqueued"
        reason = None
    response = IndexAuditReconcileEnqueueResponse(
        schema="mimirq.index_audit_reconcile_enqueue.v1",
        job_name="reconcile_index_audit_job",
        job_id=queued_job_id if queued_job_id is not None else job_id,
        tenant_id=str(tenant_id),
        dataset_id=str(payload.dataset_id),
        document_id=str(payload.document_id) if payload.document_id is not None else None,
        scope=scope,
        dry_run=payload.dry_run,
        limit=payload.limit,
        status=status,
        reason=reason,
        report_in_job_result=True,
        legacy_unknown_report_only=True,
    )
    await run_blocking_in_thread(
        _audit_index_reconcile_in_session,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        document_id=payload.document_id,
        scope=scope,
        status=response.status,
        dry_run=payload.dry_run,
        limit=payload.limit,
        job_id=response.job_id,
    )
    return response


@router.get("/embedding-drift/snapshot")
def get_embedding_drift_snapshot(
    params: Annotated[EmbeddingDriftParams, Query()],
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
        dataset_id=params.dataset_id,
        document_id=params.document_id,
        sample_n=params.sample_n,
        drift_threshold=params.drift_threshold,
    )


@router.post("/perf-suite/run", response_model=PerfSuiteRunResponse)
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
            iterations=payload.iterations,
            timeout_sec=payload.timeout_sec,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"perf baseline/policy not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"perf suite run failed: {exc}") from exc


@router.get("/index-drift", response_model=IndexDriftListResponse)
def list_index_drift(
    params: Annotated[IndexDriftListParams, Query()],
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
        dataset_id=params.dataset_id,
        status=params.status,
        limit=params.limit,
    )
    return {
        "schema": "mimirq.index_drift_list.v1",
        "items": rows,
    }


@router.post(
    "/index-drift/{item_id}/resolve",
    response_model=IndexDriftItemResponse,
)
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
        resolution_note=payload.resolution_note,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="index drift item not found")
    return item
