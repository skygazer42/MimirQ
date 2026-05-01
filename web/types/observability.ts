export interface RagMetricsSummaryResponse {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  record_count: number
  rag_trace_count: number
  reranker_api_count: number
  retrieval_avg_elapsed_sec?: number | null
  retrieval_p95_elapsed_sec?: number | null
  rerank_avg_elapsed_sec?: number | null
  citations_avg_count?: number | null
  retrieval_mode_counts: Record<string, number>
  hit_type_counts: Record<string, number>
  error_counts: Record<string, number>
  timeseries: Record<string, unknown[]>
}

export interface OnlineQualitySummaryResponse {
  enabled: boolean
  path: string
  window_minutes: number
  bucket_minutes: number
  truncated: boolean
  record_count: number
  sample_count: number
  faithfulness_det_avg?: number | null
  chunk_utilization_avg?: number | null
  timeseries: Record<string, unknown[]>
  alerts: Array<Record<string, unknown>>
}

export interface QuerysetHealthRunsResponse {
  enabled: boolean
  path: string
  total: number
  truncated: boolean
  items: Array<Record<string, unknown>>
  timeseries: Record<string, unknown[]>
}

export interface QuerysetHealthDiffResponse {
  diff: Record<string, unknown>
}

export interface RagQueryAnalyticsResponse {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  record_count: number
  rag_trace_count: number
  unique_query_hashes: number

  zero_hit_count: number
  zero_hit_rate?: number | null

  slow_threshold_sec: number
  slow_count: number
  slow_rate?: number | null

  retrieval_p50_elapsed_sec?: number | null
  retrieval_p95_elapsed_sec?: number | null
  retrieval_p99_elapsed_sec?: number | null

  error_kind_counts: Record<string, number>
  top_zero_hit_queries: Array<{ query_hash: string; count: number } | Record<string, unknown>>
  top_slow_queries: Array<{ query_hash: string; count: number; max_elapsed_sec: number } | Record<string, unknown>>
  timeseries: Record<string, unknown[]>
}

export interface DepsDiagnosticsResponse {
  schema: string
  generated_at: string

  postgres: Record<string, unknown>
  redis: Record<string, unknown>
  minio: Record<string, unknown>
  milvus: Record<string, unknown>
}

export interface RagCostAttributionResponse {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  record_count: number
  rag_trace_count: number

  llm_prompt_tokens: number
  llm_completion_tokens: number
  llm_total_tokens: number
  llm_model_counts: Record<string, number>
  llm_source_counts: Record<string, number>

  embed_query_tokens: number
  embed_query_chars: number
  embed_query_count: number
  embed_provider_counts: Record<string, number>
  embed_model_counts: Record<string, number>

  retrieval_elapsed_avg_sec?: number | null
  retrieval_elapsed_p95_sec?: number | null
  rerank_elapsed_avg_sec?: number | null
  rerank_elapsed_p95_sec?: number | null
  retrieval_vector_backend_counts: Record<string, number>
  retrieval_query_count: number
}

export interface OpsConfigSnapshotResponse {
  schema: string
  fingerprint: string
  config: Record<string, unknown>
}

export interface PeriodicJobFreshnessItemResponse {
  key: string
  action: string
  resource_type: string

  expected_interval_hours: number
  stale_after_hours: number

  last_created_at?: string | null
  last_resource_id?: string | null
  age_seconds?: number | null
  stale: boolean
}

export interface PeriodicJobFreshnessResponse {
  schema: string
  generated_at: string
  tenant_id: string
  items: PeriodicJobFreshnessItemResponse[]
}

export interface TaskQueueObservabilitySnapshotResponse {
  schema: string
  generated_at: string
  source: string

  enabled: boolean
  queue_name: string

  broker_up: boolean
  queue_depth?: number | null
  workers_active?: number | null

  heartbeat_interval_sec: number
  heartbeat_ttl_sec: number
  poll_interval_sec: number
  recent_job_outcomes?: Array<Record<string, unknown>>

  error?: string | null
}

export interface RagTraceBundleResponse {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  record_count: number
  request_id: string
  records: Array<Record<string, unknown>>
}

export interface RagTraceBundleSummaryResponse {
  request_id: string
  window_minutes: number
  truncated: boolean

  retrieval_config_hash?: string | null
  retrieval_mode?: string | null
  retrieval_requested_mode?: string | null
  retrieval_auto_routed?: boolean | null
  retrieval_profile?: string | null
  retrieval_top_k?: number | null
  retrieval_alpha?: number | null
  retrieval_enable_reranker?: boolean | null
  retrieval_reranker_provider?: string | null
  retrieval_reranker_top_n?: number | null
  retrieval_query_parallelism?: number | null
  retrieval_query_count?: number | null
  retrieval_elapsed_sec?: number | null
  retrieval_error_kinds: Record<string, number>

  citations_count?: number | null

  model_route?: string | null
  model_used?: string | null
  vector_backend?: string | null
}

export interface RagTraceBundleDiffItem {
  key: string
  a?: unknown
  b?: unknown
  delta?: number | null
}

export interface RagTraceBundleDiffResponse {
  schema: string
  generated_at: string
  request_id_a: string
  request_id_b: string
  truncated: boolean

  summary_a: RagTraceBundleSummaryResponse
  summary_b: RagTraceBundleSummaryResponse
  diff: RagTraceBundleDiffItem[]
}

export interface SloWindowSnapshotResponse {
  window_minutes: number
  source: string
  rag_trace_count?: number | null
  retrieval_p95_elapsed_sec?: number | null
  retrieval_p99_elapsed_sec?: number | null
  zero_hit_rate?: number | null
  error_rate?: number | null
}

export interface SloSnapshotResponse {
  schema: string
  generated_at: string
  windows: SloWindowSnapshotResponse[]
}

export interface IndexAuditResponse {
  tenant_id: string
  dataset_id: string
  vector_backend: string

  active_documents: number
  active_chunks: number

  vector_id_missing: number
  vector_ids_checked: number
  vector_ids_missing_in_backend: number
  vector_ids_missing_in_backend_sample: string[]

  milvus_ids_sampled: number
  milvus_orphan_ids_sample: string[]
}

export interface IngestionDashboardSummaryResponse {
  window_hours: number
  bucket_minutes: number
  window_start: string
  window_end: string
  dataset_id?: string | null

  created_count: number
  by_status: Record<string, number>
  by_stage_processing: Record<string, number>
  avg_completed_latency_sec?: number | null

  top_error_reasons: Record<string, number>
  timeseries: Record<string, any[]>
}
