"""Observability request, query and response contracts.

Raw trace records, historical snapshots, readiness details and generated reports
keep their producer-owned JSON structure. Stable envelopes are declared here.
"""

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.base import OrmModel


class ChatUsageSummaryQuery(BaseModel):
    window_days: int = Field(default=1, ge=1, le=30)
    since: datetime | None = None
    until: datetime | None = None

    def resolve_window(self, now: datetime) -> tuple[datetime, datetime]:
        window_end = self.until if self.until is not None else now
        window_start = self.since if self.since is not None else window_end - timedelta(days=self.window_days)
        return window_start, window_end


class RagMetricsTimeseries(BaseModel):
    ts_ms: list[int]
    rag_trace: list[int]
    reranker_api: list[int]
    retrieval_avg_elapsed_sec: list[float | None]


class OnlineQualityTimeseries(BaseModel):
    ts_ms: list[int]
    samples: list[int]
    faithfulness_det_avg: list[float | None]
    chunk_utilization_avg: list[float | None]


class OnlineQualityAlert(BaseModel):
    kind: str
    metric: str
    value: float
    threshold: float
    bucket_ts_ms: int
    samples: int


class QuerysetHealthTimeseries(BaseModel):
    ts_ms: list[int]
    hit_at_k: list[float | None]
    mrr: list[float | None]
    ndcg_at_k: list[float | None]
    p95_latency_ms: list[float | None]
    miss_rate: list[float | None]
    weak_hit_rate: list[float | None]
    status: list[str]


class RagQueryAnalyticsTimeseries(BaseModel):
    ts_ms: list[int]
    requests: list[int]
    zero_hit: list[int]
    slow: list[int]
    errors: list[int]


class ZeroHitQuerySummary(BaseModel):
    query_hash: str
    count: int


class SlowQuerySummary(ZeroHitQuerySummary):
    max_elapsed_sec: float


class IngestionTimeseries(BaseModel):
    ts_ms: list[int]
    completed: list[int]
    failed: list[int]
    quarantined: list[int]
    cancelled: list[int]


class RagMetricsSummaryResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int
    reranker_api_count: int
    retrieval_avg_elapsed_sec: float | None
    retrieval_p95_elapsed_sec: float | None
    rerank_avg_elapsed_sec: float | None
    citations_avg_count: float | None
    retriever_overfetch_count: int
    retriever_overfetch_avg_ratio: float | None
    retriever_filtered_acl_total: int
    retrieval_candidate_cache_hit_count: int
    retrieval_candidate_cache_store_ok_count: int
    retrieval_candidate_cache_backend_counts: dict[str, int]
    retrieval_candidate_cache_skip_reason_counts: dict[str, int]
    retrieval_rerank_skip_reason_counts: dict[str, int]
    retrieval_mode_counts: dict[str, int]
    hit_type_counts: dict[str, int]
    error_counts: dict[str, int]
    timeseries: RagMetricsTimeseries


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
    faithfulness_det_avg: float | None
    chunk_utilization_avg: float | None
    timeseries: OnlineQualityTimeseries
    alerts: list[OnlineQualityAlert]


class QuerysetHealthRunsResponse(BaseModel):
    enabled: bool
    path: str
    total: int
    truncated: bool
    items: list[dict[str, Any]]
    timeseries: QuerysetHealthTimeseries


class QuerysetHealthDiffResponse(BaseModel):
    diff: dict[str, Any]


class RagQueryAnalyticsResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int
    unique_query_hashes: int

    zero_hit_count: int
    zero_hit_rate: float | None

    slow_threshold_sec: float
    slow_count: int
    slow_rate: float | None

    retrieval_p50_elapsed_sec: float | None
    retrieval_p95_elapsed_sec: float | None
    retrieval_p99_elapsed_sec: float | None

    error_kind_counts: dict[str, int]
    top_zero_hit_queries: list[ZeroHitQuerySummary]
    top_slow_queries: list[SlowQuerySummary]
    timeseries: RagQueryAnalyticsTimeseries
    anomalies: list[dict[str, Any]]


class RagCostAttributionResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    rag_trace_count: int

    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_model_counts: dict[str, int]
    llm_source_counts: dict[str, int]

    embed_query_tokens: int
    embed_query_chars: int
    embed_query_count: int
    embed_provider_counts: dict[str, int]
    embed_model_counts: dict[str, int]

    retrieval_elapsed_avg_sec: float | None
    retrieval_elapsed_p95_sec: float | None
    rerank_elapsed_avg_sec: float | None
    rerank_elapsed_p95_sec: float | None
    retrieval_vector_backend_counts: dict[str, int]
    retrieval_query_count: int


class RagTraceBundleResponse(BaseModel):
    enabled: bool
    path: str
    window_minutes: int
    truncated: bool
    record_count: int
    request_id: str
    records: list[dict[str, Any]]


class _SchemaAliasedModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema", serialization_alias="schema")


class RagTraceBundleSummaryResponse(BaseModel):
    request_id: str
    window_minutes: int
    truncated: bool

    retrieval_config_hash: str | None
    retrieval_mode: str | None
    retrieval_requested_mode: str | None
    retrieval_auto_routed: bool | None
    retrieval_profile: str | None
    retrieval_top_k: int | None
    retrieval_alpha: float | None
    retrieval_enable_reranker: bool | None
    retrieval_reranker_provider: str | None
    retrieval_reranker_top_n: int | None
    retrieval_query_parallelism: int | None
    retrieval_query_count: int | None
    retrieval_elapsed_sec: float | None
    retrieval_error_kinds: dict[str, int]

    citations_count: int | None

    model_route: str | None
    model_used: str | None
    vector_backend: str | None


class RagTraceBundleDiffItem(BaseModel):
    key: str
    a: Any | None
    b: Any | None
    delta: float | None


class RagTraceBundleDiffResponse(_SchemaAliasedModel):
    generated_at: datetime
    request_id_a: str
    request_id_b: str
    truncated: bool

    summary_a: RagTraceBundleSummaryResponse
    summary_b: RagTraceBundleSummaryResponse
    diff: list[RagTraceBundleDiffItem]


class OpsConfigSnapshotResponse(_SchemaAliasedModel):
    fingerprint: str
    config: dict[str, Any]


class TaskQueueObservabilitySnapshotResponse(_SchemaAliasedModel):
    generated_at: datetime
    source: str

    enabled: bool
    queue_name: str

    broker_up: bool
    queue_depth: int | None
    workers_active: int | None

    heartbeat_interval_sec: float
    heartbeat_ttl_sec: int
    poll_interval_sec: float
    recent_job_outcomes: list[dict[str, Any]]

    error: str | None


class PeriodicJobFreshnessItemResponse(BaseModel):
    key: str
    action: str
    resource_type: str

    expected_interval_hours: int
    stale_after_hours: int

    last_created_at: datetime | None
    last_resource_id: str | None
    age_seconds: int | None
    stale: bool


class PeriodicJobFreshnessResponse(_SchemaAliasedModel):
    generated_at: datetime
    tenant_id: str
    items: list[PeriodicJobFreshnessItemResponse]


class SloWindowSnapshotResponse(BaseModel):
    window_minutes: int
    source: str
    rag_trace_count: int | None
    retrieval_p95_elapsed_sec: float | None
    retrieval_p99_elapsed_sec: float | None
    zero_hit_rate: float | None
    error_rate: float | None


class SloSnapshotResponse(_SchemaAliasedModel):
    generated_at: datetime
    windows: list[SloWindowSnapshotResponse]


class IndexAuditResponse(BaseModel):
    tenant_id: str
    dataset_id: str
    vector_backend: str

    active_documents: int
    active_chunks: int

    vector_id_missing: int

    vector_ids_checked: int
    vector_ids_missing_in_backend: int
    vector_ids_missing_in_backend_sample: list[str]

    milvus_ids_sampled: int
    milvus_orphan_ids_sample: list[str]
    index_channels: dict[str, Any]


class IndexAuditReconcileRequest(BaseModel):
    dataset_id: UUID
    document_id: UUID | None = None


class IndexAuditReconcileResponse(_SchemaAliasedModel):
    tenant_id: str
    dataset_id: str
    document_id: str | None
    scope: str
    status: str
    reason: str | None
    task_id: str | None
    current_index_readiness: dict[str, Any] | None


class IndexAuditReconcileStatusResponse(_SchemaAliasedModel):
    tenant_id: str
    dataset_id: str
    document_id: str
    status: str
    reason: str | None
    legacy: bool
    ready: bool
    channel_rows_present: int
    current_index_readiness: dict[str, Any]


class IndexAuditReconcileEnqueueRequest(BaseModel):
    dataset_id: UUID
    document_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=200)
    dry_run: bool = True


class IndexAuditReconcileEnqueueResponse(_SchemaAliasedModel):
    job_name: str
    job_id: str
    tenant_id: str
    dataset_id: str
    document_id: str | None
    scope: str
    dry_run: bool
    limit: int
    status: str
    reason: str | None
    report_in_job_result: bool
    legacy_unknown_report_only: bool


class IndexDriftItemResponse(OrmModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID | None
    document_id: UUID | None
    chunk_id: UUID | None
    operation: str
    channel: str
    strictness: str
    status: str
    reason: str
    details: dict[str, Any]
    reconcile_task_id: str | None
    replay_count: int
    created_at: datetime | None
    updated_at: datetime | None
    last_replayed_at: datetime | None
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None


class IndexDriftListResponse(_SchemaAliasedModel):
    items: list[IndexDriftItemResponse]


class IndexDriftResolveRequest(BaseModel):
    resolution_note: str = Field(default="", max_length=2000)


class IngestionDashboardSummaryResponse(BaseModel):
    window_hours: int
    bucket_minutes: int
    window_start: datetime
    window_end: datetime
    dataset_id: str | None

    created_count: int
    by_status: dict[str, int]
    by_stage_processing: dict[str, int]
    avg_completed_latency_sec: float | None

    top_error_reasons: dict[str, int]
    timeseries: IngestionTimeseries


class DepsDiagnosticsResponse(_SchemaAliasedModel):
    generated_at: datetime

    postgres: dict[str, Any]
    redis: dict[str, Any]
    minio: dict[str, Any]
    milvus: dict[str, Any]


class DatasetCacheInvalidationResponse(BaseModel):
    dataset_id: str
    previous_corpus_cache_token: str | None
    current_corpus_cache_token: str | None
    invalidated_at: datetime
    evidence_post_rerank_memory_cleared: bool
    note: str


class PerfSuiteRunRequest(BaseModel):
    iterations: int = Field(default=10, ge=1, le=200, description="Iterations per case (bounded)")
    timeout_sec: float = Field(default=2.0, ge=0.05, le=10.0, description="Timeout per request in seconds (bounded)")


class PerfSuiteRunResponse(_SchemaAliasedModel):
    baseline_path: str
    policy_path: str
    baseline_ts: str
    current_report: dict[str, Any]
    diff: dict[str, Any]


class MetricsWindowParams(BaseModel):
    window_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)
    max_bytes: int = Field(default=5000000, ge=100000, le=50000000)


class OnlineQualitySummaryParams(BaseModel):
    window_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)
    bucket_minutes: int = Field(default=5, ge=1, le=60)
    max_bytes: int = Field(default=5000000, ge=100000, le=50000000)


class QuerysetHealthRunsParams(BaseModel):
    limit: int = Field(default=90, ge=1, le=500)
    profile_hash: str | None = Field(default=None, description="Optional retrieval profile hash to filter history")


class QuerysetHealthDiffParams(BaseModel):
    baseline_generated_at: str = Field(min_length=1, max_length=64)
    current_generated_at: str = Field(min_length=1, max_length=64)
    max_hard_case_ids: int = Field(default=20, ge=1, le=200)


class RagQueryAnalyticsParams(BaseModel):
    window_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)
    slow_threshold_sec: float = Field(default=2.0, ge=0.0, le=120.0)
    top_n: int = Field(default=20, ge=1, le=200)
    max_bytes: int = Field(default=5000000, ge=100000, le=50000000)


class MetricsTailParams(BaseModel):
    window_minutes: int = Field(default=24 * 60, ge=1, le=7 * 24 * 60)
    max_bytes: int = Field(default=5000000, ge=100000, le=50000000)


class RagTraceBundleParams(BaseModel):
    request_id: str = Field(min_length=1, max_length=200, description="X-Request-ID to export")
    window_minutes: int = Field(default=24 * 60, ge=1, le=7 * 24 * 60)
    max_bytes: int = Field(default=5000000, ge=100000, le=50000000)


class RagTraceBundleDiffParams(BaseModel):
    request_id_a: str = Field(min_length=1, max_length=200, description="X-Request-ID A to compare")
    request_id_b: str = Field(min_length=1, max_length=200, description="X-Request-ID B to compare")
    window_minutes: int = Field(default=24 * 60, ge=1, le=7 * 24 * 60)
    max_bytes: int = Field(default=5000000, ge=100000, le=50000000)


class TaskQueueSnapshotParams(BaseModel):
    force_refresh: bool = Field(default=False, description="Force refresh from broker (best-effort)")


class IngestionSummaryParams(BaseModel):
    window_hours: int = Field(default=24, ge=1, le=30 * 24)
    bucket_minutes: int = Field(default=60, ge=1, le=30 * 24 * 60)
    dataset_id: UUID | None = Field(default=None, description="Optional dataset_id filter")


class IndexAuditParams(BaseModel):
    dataset_id: UUID = Field(description="Dataset id to audit (required)")
    max_check_ids: int = Field(default=5000, ge=0, le=50000, description="Max DB vector_ids to existence-check")
    milvus_list_limit: int = Field(default=2000, ge=0, le=50000, description="Max Milvus ids to sample for orphans")
    sample_limit: int = Field(default=20, ge=0, le=200, description="Max sample ids to return per category")


class IndexReconcileStatusParams(BaseModel):
    dataset_id: UUID = Field(description="Dataset id for the reconciled document")
    document_id: UUID = Field(description="Document id to inspect reconcile readiness for")


class EmbeddingDriftParams(BaseModel):
    dataset_id: UUID | None = Field(default=None, description="Optional dataset_id scope")
    document_id: UUID | None = Field(default=None, description="Optional document_id scope")
    sample_n: int = Field(default=200, ge=1, le=2000, description="Max chunks sampled (bounded)")
    drift_threshold: float = Field(default=0.05, ge=0.0, le=1.0, description="Cosine distance threshold")


class IndexDriftListParams(BaseModel):
    dataset_id: UUID | None = Field(default=None, description="Optional dataset UUID filter")
    status: str = Field(default="open", description="open | resolved | all")
    limit: int = Field(default=100, ge=1, le=500)


__all__ = [
    "DatasetCacheInvalidationResponse",
    "DepsDiagnosticsResponse",
    "EmbeddingDriftParams",
    "FrontendTraceReportRequest",
    "FrontendWebVitalReportRequest",
    "IndexAuditParams",
    "IndexAuditReconcileEnqueueRequest",
    "IndexAuditReconcileEnqueueResponse",
    "IndexAuditReconcileRequest",
    "IndexAuditReconcileResponse",
    "IndexAuditReconcileStatusResponse",
    "IndexAuditResponse",
    "IndexDriftItemResponse",
    "IndexDriftListParams",
    "IndexDriftListResponse",
    "IndexDriftResolveRequest",
    "IndexReconcileStatusParams",
    "IngestionDashboardSummaryResponse",
    "IngestionSummaryParams",
    "IngestionTimeseries",
    "MetricsTailParams",
    "MetricsWindowParams",
    "OnlineQualityAlert",
    "OnlineQualitySummaryParams",
    "OnlineQualitySummaryResponse",
    "OnlineQualityTimeseries",
    "OpsConfigSnapshotResponse",
    "PerfSuiteRunRequest",
    "PerfSuiteRunResponse",
    "PeriodicJobFreshnessItemResponse",
    "PeriodicJobFreshnessResponse",
    "QuerysetHealthDiffParams",
    "QuerysetHealthDiffResponse",
    "QuerysetHealthRunsParams",
    "QuerysetHealthRunsResponse",
    "QuerysetHealthTimeseries",
    "RagCostAttributionResponse",
    "RagMetricsSummaryResponse",
    "RagMetricsTimeseries",
    "RagQueryAnalyticsParams",
    "RagQueryAnalyticsResponse",
    "RagQueryAnalyticsTimeseries",
    "RagTraceBundleDiffItem",
    "RagTraceBundleDiffParams",
    "RagTraceBundleDiffResponse",
    "RagTraceBundleParams",
    "RagTraceBundleResponse",
    "RagTraceBundleSummaryResponse",
    "SloSnapshotResponse",
    "SloWindowSnapshotResponse",
    "SlowQuerySummary",
    "TaskQueueObservabilitySnapshotResponse",
    "TaskQueueSnapshotParams",
    "ZeroHitQuerySummary",
]
