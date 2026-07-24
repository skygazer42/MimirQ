import type {
  DepsDiagnosticsResponse,
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
} from '@/types'

import { getAuthHeaders } from '@/lib/auth-headers'
import { authenticatedFetch } from '@/lib/authenticated-fetch'
import { buildFetchError } from '@/lib/fetch-errors'
import { API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { apiClient } from '@/lib/api/core'

export type FrontendWebVitalReportRequest = {
  id: string
  name: 'LCP' | 'CLS' | 'FID' | 'INP'
  value: number
  rating?: string
  navigation_type?: string
  page?: string
}

export type FrontendWebVitalReportOptions = {
  keepalive?: boolean
  signal?: AbortSignal
}

export type FrontendTraceReportRequest = {
  event: string
  duration_ms: number
  component?: string
  page?: string
  input_node_count?: number
  input_link_count?: number
  output_node_count?: number
  output_link_count?: number
  active_filter_count?: number
}

export const observabilityApi = {
  async reportFrontendVital(
    payload: FrontendWebVitalReportRequest,
    options: FrontendWebVitalReportOptions = {}
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

  async reportFrontendTrace(
    payload: FrontendTraceReportRequest,
    options: FrontendWebVitalReportOptions = {}
  ): Promise<void> {
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

  async getRagMetricsSummary(params: { window_minutes?: number; max_bytes?: number }): Promise<RagMetricsSummaryResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/summary', { params })
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

  async getQuerysetHealthRuns(params: { limit?: number; profile_hash?: string } = {}): Promise<QuerysetHealthRunsResponse> {
    const { data } = await apiClient.get('/observability/queryset-health/runs', { params })
    return data
  },

  async getQuerysetHealthDiff(params: {
    baseline_generated_at: string
    current_generated_at: string
    max_hard_case_ids?: number
  }): Promise<QuerysetHealthDiffResponse> {
    const { data } = await apiClient.get('/observability/queryset-health/diff', { params })
    return data
  },

  async getRagQueryAnalytics(params: {
    window_minutes?: number
    slow_threshold_sec?: number
    top_n?: number
    max_bytes?: number
  }): Promise<RagQueryAnalyticsResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/query-analytics', { params })
    return data
  },

  async getRagCostAttribution(params: { window_minutes?: number; max_bytes?: number }): Promise<RagCostAttributionResponse> {
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

  async getRagTraceBundle(params: { request_id: string; window_minutes?: number; max_bytes?: number }): Promise<RagTraceBundleResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/trace-bundle', { params })
    return data
  },

  async getRagTraceBundleDiff(params: {
    request_id_a: string
    request_id_b: string
    window_minutes?: number
    max_bytes?: number
  }): Promise<RagTraceBundleDiffResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/trace-bundle/diff', { params })
    return data
  },

  async getOpsConfigSnapshot(): Promise<OpsConfigSnapshotResponse> {
    const { data } = await apiClient.get('/observability/config/snapshot')
    return data
  },

  async getPeriodicJobFreshness(): Promise<PeriodicJobFreshnessResponse> {
    const { data } = await apiClient.get('/observability/periodic-jobs/freshness')
    return data
  },

  async getTaskQueueSnapshot(params: { force_refresh?: boolean } = {}): Promise<TaskQueueObservabilitySnapshotResponse> {
    const { data } = await apiClient.get('/observability/task-queue/snapshot', { params })
    return data
  },

  async getSloSnapshot(): Promise<SloSnapshotResponse> {
    const { data } = await apiClient.get('/observability/slo/snapshot')
    return data
  },

  async getIngestionDashboardSummary(params: {
    window_hours?: number
    bucket_minutes?: number
    dataset_id?: string
  } = {}): Promise<IngestionDashboardSummaryResponse> {
    const { data } = await apiClient.get('/observability/ingestion/summary', { params })
    return data
  },

  async getIndexAudit(params: {
    dataset_id: string
    max_check_ids?: number
    milvus_list_limit?: number
    sample_limit?: number
  }): Promise<IndexAuditResponse> {
    const { data } = await apiClient.get('/observability/index-audit', { params })
    return data
  },

  async getEmbeddingDriftSnapshot(params: {
    dataset_id?: string
    document_id?: string
    sample_n?: number
    drift_threshold?: number
  } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/observability/embedding-drift/snapshot', { params })
    return data
  },

  async runPerfSuite(payload: { iterations?: number; timeout_sec?: number } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/observability/perf-suite/run', {
      iterations: payload.iterations ?? 10,
      timeout_sec: payload.timeout_sec ?? 2,
    })
    return data
  },

  async invalidateDatasetCache(datasetId: string): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(`/observability/cache/datasets/${encodeURIComponent(datasetId)}/invalidate`)
    return data
  },

  async listIndexDrift(params: { dataset_id?: string; status?: string; limit?: number } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/observability/index-drift', { params })
    return data
  },

  async resolveIndexDrift(itemId: string, payload: { resolution_note?: string } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(`/observability/index-drift/${encodeURIComponent(itemId)}/resolve`, {
      resolution_note: payload.resolution_note ?? '',
    })
    return data
  },
}
