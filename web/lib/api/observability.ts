import type {
  DepsDiagnosticsResponse,
  IndexAuditReconcileEnqueueRequest,
  IndexAuditReconcileEnqueueResponse,
  IndexAuditReconcileResponse,
  IndexAuditReconcileStatusResponse,
  IndexAuditResponse,
  IngestionDashboardSummaryResponse,
  OnlineQualitySummaryResponse,
  OpsConfigSnapshotResponse,
  PeriodicJobFreshnessResponse,
  QuerysetHealthDiffResponse,
  QuerysetHealthRunsResponse,
  RagCostAttributionResponse,
  RagMetricsSummaryResponse,
  RagQueryAnalyticsResponse,
  RagTraceBundleDiffResponse,
  RagTraceBundleResponse,
  SloSnapshotResponse,
  TaskQueueObservabilitySnapshotResponse,
} from '@/types/observability'
import { z } from 'zod'
import type { OpenApiSchema } from '@/types/backend'

import { getAuthHeaders } from '@/lib/auth-headers'
import { authenticatedFetch } from '@/lib/authenticated-fetch'
import { buildFetchError } from '@/lib/fetch-errors'
import type { FrontendTracePayload } from '@/lib/frontend-trace'
import { API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'
import { parseApiResponse } from '@/lib/openapi-request'

const querysetHealthDiffSchema = z.object({
  diff: z.looseObject({
    baseline_generated_at: z.string(),
    current_generated_at: z.string(),
    metric_deltas: z.looseObject({
      hit_at_k_delta: z.number(),
      mrr_delta: z.number(),
      ndcg_at_k_delta: z.number(),
      p95_latency_ms_delta: z.number(),
      miss_rate_delta: z.number(),
      weak_hit_rate_delta: z.number(),
    }),
  }),
}) satisfies z.ZodType<QuerysetHealthDiffResponse>

const indexAuditReconcileStatusSchema = z.looseObject({
  status: z.enum(['legacy_unknown', 'pending', 'error', 'ready', 'unknown']),
  reason: z.string().nullish(),
  legacy: z.boolean().nullish(),
  ready: z.boolean().nullish(),
  channel_rows_present: integerSchema.nullish(),
  current_index_readiness: z
    .looseObject({
      ready: z.boolean().optional(),
      pending_channels: z.array(z.string()).optional(),
      error_channels: z.array(z.string()).optional(),
      statuses: recordSchema.optional(),
    })
    .nullish(),
}) satisfies z.ZodType<IndexAuditReconcileStatusResponse>

const errorKindsSchema = z.custom<Record<string, number>>((value) => {
  const errorKinds = recordSchema.safeParse(value)
  return (
    errorKinds.success &&
    Object.values(errorKinds.data).every((count) => typeof count === 'number' && Number.isInteger(count))
  )
})
const traceBundleSchema: z.ZodType<RagTraceBundleResponse> = z.looseObject({
  enabled: z.boolean(),
  path: z.string(),
  window_minutes: z.number().int(),
  truncated: z.boolean(),
  record_count: z.number().int().nonnegative(),
  request_id: z.string(),
  records: z.array(recordSchema),
})
const traceSummarySchema = z.looseObject({
  request_id: z.string(),
  window_minutes: z.number().int(),
  truncated: z.boolean(),
  retrieval_config_hash: z.string().nullish(),
  retrieval_mode: z.string().nullish(),
  retrieval_requested_mode: z.string().nullish(),
  retrieval_auto_routed: z.boolean().nullish(),
  retrieval_profile: z.string().nullish(),
  retrieval_top_k: z.number().int().nullish(),
  retrieval_alpha: z.number().nullish(),
  retrieval_enable_reranker: z.boolean().nullish(),
  retrieval_reranker_provider: z.string().nullish(),
  retrieval_reranker_top_n: z.number().int().nullish(),
  retrieval_query_parallelism: z.number().int().nullish(),
  retrieval_query_count: z.number().int().nullish(),
  retrieval_elapsed_sec: z.number().nullish(),
  retrieval_error_kinds: errorKindsSchema,
  citations_count: z.number().int().nullish(),
  model_route: z.string().nullish(),
  model_used: z.string().nullish(),
  vector_backend: z.string().nullish(),
})
const traceDiffSchema: z.ZodType<RagTraceBundleDiffResponse> = z.looseObject({
  schema: z.string(),
  generated_at: dateTimeSchema,
  request_id_a: z.string(),
  request_id_b: z.string(),
  truncated: z.boolean(),
  summary_a: traceSummarySchema,
  summary_b: traceSummarySchema,
  diff: z.array(
    z.looseObject({
      key: z.string(),
      a: z.unknown().optional(),
      b: z.unknown().optional(),
      delta: z.number().nullish(),
    }),
  ),
})
const configSnapshotSchema: z.ZodType<OpsConfigSnapshotResponse> = z.looseObject({
  schema: z.string(),
  fingerprint: z.string(),
  config: recordSchema,
})

type FrontendWebVital = OpenApiSchema<'FrontendWebVitalReportRequest'>
export type FrontendWebVitalReportRequest = FrontendWebVital & { id: NonNullable<FrontendWebVital['id']> }

type FrontendWebVitalReportOptions = {
  keepalive?: boolean
  signal?: AbortSignal
}

export const observabilityApi = {
  async reportFrontendVital(
    payload: FrontendWebVitalReportRequest,
    options: FrontendWebVitalReportOptions = {},
  ): Promise<void> {
    const requestId = generateRequestId()
    const response = await authenticatedFetch(`${API_V1_BASE_URL}/observability/frontend-vitals`, {
      method: 'POST',
      headers: withPreferredLanguageHeader({
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      body: JSON.stringify(payload),
      keepalive: options.keepalive === true,
      signal: options.signal,
      allowSessionLogoutOnUnauthorized: false,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Frontend vital report failed')
    }
  },

  async reportFrontendTrace(payload: FrontendTracePayload, options: FrontendWebVitalReportOptions = {}): Promise<void> {
    const requestId = generateRequestId()
    const response = await authenticatedFetch(`${API_V1_BASE_URL}/observability/frontend-traces`, {
      method: 'POST',
      headers: withPreferredLanguageHeader({
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      body: JSON.stringify(payload),
      keepalive: options.keepalive === true,
      signal: options.signal,
      allowSessionLogoutOnUnauthorized: false,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Frontend trace report failed')
    }
  },

  async getRagMetricsSummary(
    params: { window_minutes?: number; max_bytes?: number },
    options: ApiRequestOptions = {},
  ): Promise<RagMetricsSummaryResponse> {
    const { data } = await apiClient.get<RagMetricsSummaryResponse>('/observability/rag-metrics/summary', {
      params,
      signal: options.signal,
    })
    return data
  },

  async getOnlineQualitySummary(params: {
    window_minutes?: number
    bucket_minutes?: number
    max_bytes?: number
  }): Promise<OnlineQualitySummaryResponse> {
    const { data } = await apiClient.get('/observability/online-quality/summary', { params })
    return data
  },

  async getQuerysetHealthRuns(
    params: { limit?: number; profile_hash?: string },
    options: ApiRequestOptions = {},
  ): Promise<QuerysetHealthRunsResponse> {
    const { data } = await apiClient.get<QuerysetHealthRunsResponse>('/observability/queryset-health/runs', {
      params,
      signal: options.signal,
    })
    return data
  },

  async getQuerysetHealthDiff(
    params: {
      baseline_generated_at: string
      current_generated_at: string
      max_hard_case_ids?: number
    },
    options?: ApiRequestOptions,
  ): Promise<z.infer<typeof querysetHealthDiffSchema>> {
    const response = await apiClient.get<unknown>('/observability/queryset-health/diff', {
      params,
      signal: options?.signal,
    })
    const { diff } = parseApiResponse(response, querysetHealthDiffSchema, 'QuerysetHealthDiffResponse')
    if (
      diff.baseline_generated_at !== params.baseline_generated_at.trim() ||
      diff.current_generated_at !== params.current_generated_at.trim()
    ) {
      throw new Error('返回的健康度差异与所选快照不匹配，请重新读取')
    }
    return { diff }
  },

  async getRagQueryAnalytics(
    params: { window_minutes?: number; slow_threshold_sec?: number; top_n?: number; max_bytes?: number },
    options: ApiRequestOptions = {},
  ): Promise<RagQueryAnalyticsResponse> {
    const { data } = await apiClient.get<RagQueryAnalyticsResponse>('/observability/rag-metrics/query-analytics', {
      params,
      signal: options.signal,
    })
    return data
  },

  async getRagCostAttribution(params: {
    window_minutes?: number
    max_bytes?: number
  }): Promise<RagCostAttributionResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/cost-attribution', { params })
    return data
  },

  async getRagMetricsTail(params: { window_minutes?: number; max_bytes?: number }): Promise<ArrayBuffer> {
    const { data } = await apiClient.get('/observability/rag-metrics/tail', { params, responseType: 'arraybuffer' })
    return data
  },

  async getDepsDiagnosticsSnapshot(): Promise<DepsDiagnosticsResponse> {
    const { data } = await apiClient.get('/observability/diagnostics/deps')
    return data
  },

  async getRagTraceBundle(
    params: {
      request_id: string
      window_minutes?: number
      max_bytes?: number
    },
    options: ApiRequestOptions = {},
  ): Promise<RagTraceBundleResponse> {
    const response = await apiClient.get<unknown>('/observability/rag-metrics/trace-bundle', {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, traceBundleSchema, 'RagTraceBundle')
  },

  async getRagTraceBundleDiff(
    params: {
      request_id_a: string
      request_id_b: string
      window_minutes?: number
      max_bytes?: number
    },
    options: ApiRequestOptions = {},
  ): Promise<RagTraceBundleDiffResponse> {
    const response = await apiClient.get<unknown>('/observability/rag-metrics/trace-bundle/diff', {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, traceDiffSchema, 'RagTraceBundleDiff')
  },

  async getOpsConfigSnapshot(options: ApiRequestOptions = {}): Promise<OpsConfigSnapshotResponse> {
    const response = await apiClient.get<unknown>('/observability/config/snapshot', { signal: options.signal })
    return parseApiResponse(response, configSnapshotSchema, 'OpsConfigSnapshot')
  },

  async getPeriodicJobFreshness(): Promise<PeriodicJobFreshnessResponse> {
    const { data } = await apiClient.get('/observability/periodic-jobs/freshness')
    return data
  },

  async getTaskQueueSnapshot(
    params: { force_refresh?: boolean } = {},
  ): Promise<TaskQueueObservabilitySnapshotResponse> {
    const { data } = await apiClient.get('/observability/task-queue/snapshot', { params })
    return data
  },

  async getSloSnapshot(): Promise<SloSnapshotResponse> {
    const { data } = await apiClient.get('/observability/slo/snapshot')
    return data
  },

  async getIngestionDashboardSummary(
    params: {
      window_hours?: number
      bucket_minutes?: number
      dataset_id?: string
    } = {},
  ): Promise<IngestionDashboardSummaryResponse> {
    const { data } = await apiClient.get('/observability/ingestion/summary', { params })
    return data
  },

  async getIndexAudit(
    params: {
      dataset_id: string
      max_check_ids?: number
      milvus_list_limit?: number
      sample_limit?: number
    },
    options?: ApiRequestOptions,
  ): Promise<IndexAuditResponse> {
    const { data } = await apiClient.get<IndexAuditResponse>('/observability/index-audit', {
      params,
      signal: options?.signal,
    })
    return data
  },

  async reconcileIndexAudit(payload: {
    dataset_id: string
    document_id?: string | null
  }): Promise<IndexAuditReconcileResponse> {
    const { data } = await apiClient.post('/observability/index-audit/reconcile', payload)
    return data
  },

  async getIndexAuditReconcileStatus(
    params: { dataset_id: string; document_id: string },
    options?: ApiRequestOptions,
  ): Promise<IndexAuditReconcileStatusResponse> {
    const response = await apiClient.get<unknown>('/observability/index-audit/reconcile-status', {
      params,
      signal: options?.signal,
    })
    return parseApiResponse(response, indexAuditReconcileStatusSchema, 'IndexAuditReconcileStatusResponse')
  },

  async enqueueIndexAuditReconcileJob(
    payload: IndexAuditReconcileEnqueueRequest,
  ): Promise<IndexAuditReconcileEnqueueResponse> {
    const { data } = await apiClient.post('/observability/index-audit/reconcile-jobs', payload)
    return data
  },

  async getEmbeddingDriftSnapshot(
    params: {
      dataset_id?: string
      document_id?: string
      sample_n?: number
      drift_threshold?: number
    } = {},
  ): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/observability/embedding-drift/snapshot', { params })
    return data
  },

  async runPerfSuite(payload: { iterations?: number; timeout_sec?: number } = {}): Promise<Record<string, unknown>> {
    const iterations = payload.iterations ?? 10
    const timeoutSeconds = payload.timeout_sec ?? 2
    // The server runs health, readiness and metadata sequentially.
    const timeout = API_TIMEOUT_MS + 3 * iterations * timeoutSeconds * 1000
    const { data } = await apiClient.post(
      '/observability/perf-suite/run',
      { iterations, timeout_sec: timeoutSeconds },
      { timeout },
    )
    return data
  },

  async invalidateDatasetCache(datasetId: string): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(`/observability/cache/datasets/${encodeURIComponent(datasetId)}/invalidate`)
    return data
  },

  async listIndexDrift(
    params: { dataset_id?: string; status?: string; limit?: number } = {},
  ): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/observability/index-drift', { params })
    return data
  },

  async resolveIndexDrift(
    itemId: string,
    payload: { resolution_note?: string } = {},
  ): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(`/observability/index-drift/${encodeURIComponent(itemId)}/resolve`, {
      resolution_note: payload.resolution_note ?? '',
    })
    return data
  },
}
