import type {
  ConnectorConfigCreateRequest,
  ConnectorConfigListResponse,
  ConnectorConfigOut,
  ConnectorConfigUpdateRequest,
  ConnectorInfo,
  ConnectorRunCreateRequest,
  ConnectorRunListResponse,
  ConnectorRunOut,
  ConnectorScheduledTickResponse,
  ConnectorValidateRequest,
  ConnectorValidateResponse,
  IngestionRunCompareResponse,
  IngestionRunListResponse,
  IngestionRunOut,
} from '@/types'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest } from '@/lib/api/core'

export const connectorApi = {
  async listConnectors(): Promise<ConnectorInfo[]> {
    return openapiRequest({ path: '/api/v1/connectors', method: 'get' })
  },

  async validateConfig(payload: ConnectorValidateRequest): Promise<ConnectorValidateResponse> {
    return openapiRequest({ path: '/api/v1/connectors/validate', method: 'post', body: payload })
  },

  async listConfigs(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    connector_id?: string
    enabled?: boolean
  }): Promise<ConnectorConfigListResponse> {
    return openapiRequest({ path: '/api/v1/connectors/configs', method: 'get', query: params })
  },

  async createConfig(payload: ConnectorConfigCreateRequest): Promise<ConnectorConfigOut> {
    return openapiRequest({ path: '/api/v1/connectors/configs', method: 'post', body: payload })
  },

  async updateConfig(configId: string, payload: ConnectorConfigUpdateRequest): Promise<ConnectorConfigOut> {
    return openapiRequest({
      path: '/api/v1/connectors/configs/{config_id}',
      method: 'put',
      pathParams: { config_id: configId },
      body: payload,
    })
  },

  async deleteConfig(configId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/connectors/configs/{config_id}',
      method: 'delete',
      pathParams: { config_id: configId },
    })
  },

  async runConfig(configId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/configs/{config_id}/run',
      method: 'post',
      pathParams: { config_id: configId },
    })
  },

  async reconcileConfig(
    configId: string,
    params?: { apply?: boolean; sample_limit?: number }
  ): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(
      `/connectors/configs/${encodeURIComponent(configId)}/reconcile`,
      undefined,
      { params, timeout: API_LONG_TIMEOUT_MS }
    )
    return data
  },

  async scheduledTick(): Promise<ConnectorScheduledTickResponse> {
    return openapiRequest({ path: '/api/v1/connectors/scheduled/tick', method: 'post' })
  },

  async createRun(payload: ConnectorRunCreateRequest): Promise<ConnectorRunOut> {
    return openapiRequest({ path: '/api/v1/connectors/runs', method: 'post', body: payload })
  },

  async listRuns(params?: { skip?: number; limit?: number; dataset_id?: string }): Promise<ConnectorRunListResponse> {
    return openapiRequest({ path: '/api/v1/connectors/runs', method: 'get', query: params })
  },

  async getRun(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}',
      method: 'get',
      pathParams: { run_id: runId },
    })
  },

  async cancelRun(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}/cancel',
      method: 'post',
      pathParams: { run_id: runId },
    })
  },

  async retryFailed(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}/retry-failed',
      method: 'post',
      pathParams: { run_id: runId },
    })
  },

  async resumeRun(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}/resume',
      method: 'post',
      pathParams: { run_id: runId },
    })
  },
}

export const ingestionRunApi = {
  async listRuns(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    status?: string
    kind?: string
  }): Promise<IngestionRunListResponse> {
    const { data } = await apiClient.get('/ingestion/runs', { params })
    return data
  },

  async getRun(runId: string): Promise<IngestionRunOut> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}`)
    return data
  },

  async compareRuns(runId: string, otherRunId: string): Promise<IngestionRunCompareResponse> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}/compare/${otherRunId}`)
    return data
  },

  async replayRun(runId: string): Promise<IngestionRunOut> {
    const { data } = await apiClient.post(`/ingestion/runs/${runId}/replay`)
    return data
  },

  async exportRunJson(runId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}/export`, { responseType: 'blob' })
    return data
  },

  async exportRunHtml(runId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}/export-html`, { responseType: 'blob' })
    return data
  },
}
