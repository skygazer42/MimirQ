import { z } from 'zod'
import type {
  Dataset,
  DatasetCategoryAssignmentRequest,
  DatasetCategoryCreate,
  DatasetCategoryMoveRequest,
  DatasetCategoryOut,
  DatasetCategoryTreeResponse,
  DatasetCategoryUpdate,
  DatasetCloneRequest,
  DatasetConfigExport,
  DatasetConfigImportRequest,
  DatasetCreate,
  DatasetIngestionStats,
  DatasetListResponse,
  DatasetPrecheckDiffResponse,
  DatasetPrecheckFindingListResponse,
  DatasetPrecheckIngestionSuggestionResponse,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSampleReviewOut,
  DatasetPrecheckSampleReviewPatchRequest,
  DatasetPrecheckSamplesResponse,
  DatasetPrecheckScanRunCreateRequest,
  DatasetPrecheckScanRunListResponse,
  DatasetPrecheckScanRunOut,
  DatasetPrecheckSummary,
  DatasetProfileScanRunCreateRequest,
  DatasetTableAsset,
  DatasetTablesListResponse,
  DatasetUpdate,
  DbCatalogTableDetail,
  DbCatalogTablesListResponse,
  DbProfileSnapshotListResponse,
  LotusSemFilterRequest,
  TableAskRequest,
  TableAskResponse,
  TableQueryRequest,
  TableQueryResponse,
} from '@/types/datasets'
import type {
  IngestionPolicy,
  IngestionPolicyImportResponse,
  IngestionPolicyRollbackRequest,
  IngestionPolicyVersionListResponse,
} from '@/types/processing'

import {
  datasetHealthSchema,
  datasetProfileSchema,
  profileDocumentsSchema,
  profileScanRunSchema,
  profileScanRunsSchema,
  type DatasetHealthResponse,
  type DatasetProfileSummary,
  type DatasetProfileFindingListResponse,
  type DatasetProfileDocumentListResponse,
  type DatasetProfileScanRunOut,
  type DatasetProfileScanRunListResponse,
} from '@/lib/dataset-profile-schema'
import { parseApiResponse } from '@/lib/openapi-request'
import {
  datasetTablesPageSchema,
  tableAskResponseSchema,
  tableAssetSchema,
  tableQueryResponseSchema,
} from '@/lib/dataset-table-schema'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'
import { integerSchema } from '@/lib/response-schema'
import { matchesResourceId } from '@/lib/resource-id'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'
import type { OpenApiSchema } from '@/types/backend'

export type DatasetAnalysisFilters = NonNullable<
  OpenApiQueryParams<'/api/v1/datasets/{dataset_id}/analysis/summary', 'get'>
>

export type DatasetProfileBucketDimension = 'file_type' | 'language' | 'directory' | 'quality_bucket'

export type DatasetAnalysisDashboardParams = Omit<DatasetAnalysisFilters, 'category'> & {
  limit?: number
}

export type DatasetAnalysisExamplesParams = DatasetAnalysisFilters & {
  limit?: number
}

export type DatasetAnalysisRuleSuggestionParams = NonNullable<
  OpenApiQueryParams<'/api/v1/datasets/{dataset_id}/analysis/rule-suggestions', 'get'>
>

export type DatasetAnalysisGlossaryWritebackParams = DatasetAnalysisFilters & {
  ruleset: string
  limit?: number
}

export type DatasetAnalysisResponse = Record<string, unknown>
const purgeCountSchema = integerSchema.nonnegative()
const datasetPurgeSchema = z.looseObject({
  dataset_id: z.string(),
  dry_run: z.boolean(),
  max_delete: integerSchema.positive(),
  eligible: purgeCountSchema,
  deleted: purgeCountSchema,
  not_found: purgeCountSchema,
  denied: purgeCountSchema,
  conflicts: purgeCountSchema,
  errors: purgeCountSchema,
}) satisfies z.ZodType<OpenApiSchema<'DatasetPurgeResponse'>>

export type DatasetPurgeResponse = z.infer<typeof datasetPurgeSchema>
export type DatasetListParams = NonNullable<OpenApiQueryParams<'/api/v1/datasets/', 'get'>>
export type ExhaustiveDatasetListParams = Omit<DatasetListParams, 'skip' | 'limit'> & {
  pageSize?: number
}
export type DatasetRetrievalAuditPayload = OpenApiSchema<'DatasetRetrievalAuditOut'>

const DEFAULT_DATASET_PAGE_SIZE = 200
const datasetRuleSuggestionsSchema = z.looseObject({
  glossary_suggestions: z.array(z.looseObject({ token: z.string().min(1), count: integerSchema, source: z.string() })),
})

const datasetCategoryAssignmentSchema = z.looseObject({
  dataset_id: z.string().min(1),
  category_ids: z.array(z.string().min(1)),
})

function categoryAssignmentFor(datasetId: string) {
  return datasetCategoryAssignmentSchema.refine((assignment) => matchesResourceId(assignment.dataset_id, datasetId), {
    message: '分类结果的数据集与请求不一致',
  })
}

async function listDatasets(params?: DatasetListParams, options: ApiRequestOptions = {}): Promise<DatasetListResponse> {
  return openapiRequest({ path: '/api/v1/datasets/', method: 'get', query: params, signal: options.signal })
}

export async function listAllDatasets(
  { pageSize = DEFAULT_DATASET_PAGE_SIZE, ...params }: ExhaustiveDatasetListParams = {},
  options: ApiRequestOptions = {},
): Promise<Dataset[]> {
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > DEFAULT_DATASET_PAGE_SIZE) {
    throw new RangeError('数据集目录每页条数必须是 1 到 200 的整数')
  }
  const items = new Map<string, Dataset>()
  let skip = 0
  let page = await listDatasets({ ...params, skip, limit: pageSize }, options)
  const total = page.total
  if (!Number.isInteger(total) || total < 0) {
    throw new Error('数据集目录总数无效，请重新读取')
  }
  while (true) {
    if (page.total !== total) throw new Error('数据集目录在读取期间发生变化，请重新读取')
    for (const item of page.items) {
      if (!items.has(item.id)) items.set(item.id, item)
    }
    skip += page.items.length
    if (skip >= total) {
      if (items.size !== total) throw new Error('数据集目录在读取期间发生变化，请重新读取')
      return [...items.values()]
    }
    if (page.items.length === 0) throw new Error('数据集目录尚未完整返回，请重新读取')
    page = await listDatasets({ ...params, skip, limit: pageSize }, options)
  }
}

export const datasetApi = {
  async create(params: DatasetCreate): Promise<Dataset> {
    return openapiRequest({ path: '/api/v1/datasets/', method: 'post', body: params })
  },

  list: listDatasets,

  listAll: listAllDatasets,

  async get(datasetId: string, options: ApiRequestOptions = {}): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'get',
      pathParams: { dataset_id: datasetId },
      signal: options.signal,
    })
  },

  async getIngestionStats(datasetId: string): Promise<DatasetIngestionStats> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion/stats',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async getHealth(datasetId: string, options: ApiRequestOptions = {}): Promise<DatasetHealthResponse> {
    const response = await apiClient.get<unknown>(`/datasets/${encodeURIComponent(datasetId)}/health`, {
      signal: options.signal,
    })
    return parseApiResponse(response, datasetHealthSchema, 'DatasetHealth')
  },

  async putRetrievalAudit(
    datasetId: string,
    payload: DatasetRetrievalAuditPayload,
  ): Promise<DatasetRetrievalAuditPayload> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/retrieval-audit',
      method: 'put',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  async getAnalysisDashboard(params?: DatasetAnalysisDashboardParams): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get('/datasets/analysis/dashboard', { params })
    return data
  },

  async getAnalysisSummary(datasetId: string, params?: DatasetAnalysisFilters): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/summary`, { params })
    return data
  },

  async getAnalysisExamples(
    datasetId: string,
    params?: DatasetAnalysisExamplesParams,
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/examples`, { params })
    return data
  },

  async getAnalysisRuleSuggestions(
    datasetId: string,
    params: DatasetAnalysisRuleSuggestionParams,
    options?: ApiRequestOptions,
  ) {
    const response = await apiClient.get<unknown>(`/datasets/${datasetId}/analysis/rule-suggestions`, {
      params,
      signal: options?.signal,
    })
    return parseApiResponse(response, datasetRuleSuggestionsSchema, 'DatasetAnalysisRuleSuggestions')
  },

  async exportAnalysisJson(datasetId: string, params?: DatasetAnalysisFilters): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/export.json`, { params })
    return data
  },

  async exportAnalysisJsonl(datasetId: string, params?: DatasetAnalysisFilters): Promise<string> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/export.jsonl`, {
      params,
      responseType: 'text',
    })
    return data
  },

  async exportAnalysisHtmlReport(datasetId: string, params?: DatasetAnalysisFilters): Promise<string> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/report.html`, {
      params,
      responseType: 'text',
    })
    return data
  },

  async writebackAnalysisGlossary(
    datasetId: string,
    params: DatasetAnalysisGlossaryWritebackParams,
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/analysis/glossary-writeback`, undefined, { params })
    return data
  },

  async createAnalysisPngExportTask(
    datasetId: string,
    params?: DatasetAnalysisFilters,
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/analysis/export.png`, undefined, { params })
    return data
  },

  async getAnalysisPngExportTask(datasetId: string, taskId: string): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/export-tasks/${taskId}`)
    return data
  },

  async getAnalysisPngExportResult(datasetId: string, taskId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/export-tasks/${taskId}/result.png`, {
      responseType: 'blob',
    })
    return data as Blob
  },

  async update(datasetId: string, params: DatasetUpdate): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'patch',
      pathParams: { dataset_id: datasetId },
      body: params,
    })
  },

  async getCategories(datasetId: string, options?: ApiRequestOptions) {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/categories',
      method: 'get',
      pathParams: { dataset_id: datasetId },
      signal: options?.signal,
      responseSchema: categoryAssignmentFor(datasetId),
    })
  },

  async setCategories(datasetId: string, payload: DatasetCategoryAssignmentRequest) {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/categories',
      method: 'put',
      pathParams: { dataset_id: datasetId },
      body: payload,
      responseSchema: categoryAssignmentFor(datasetId),
    })
  },

  async delete(datasetId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'delete',
      pathParams: { dataset_id: datasetId },
    })
  },

  async purge(datasetId: string, params: { max_delete: number; dry_run: boolean }): Promise<DatasetPurgeResponse> {
    const response = await apiClient.post<unknown>(`/datasets/${datasetId}/purge`, undefined, { params })
    const receipt = parseApiResponse(response, datasetPurgeSchema, 'DatasetPurgeResponse')
    if (
      !matchesResourceId(receipt.dataset_id, datasetId) ||
      receipt.dry_run !== params.dry_run ||
      receipt.max_delete !== params.max_delete
    ) {
      throw new Error('数据集清理回执与本次请求不匹配，请先重新读取文档列表')
    }
    return receipt
  },

  async getIngestionPolicy(datasetId: string): Promise<IngestionPolicy> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async updateIngestionPolicy(datasetId: string, policy: IngestionPolicy): Promise<IngestionPolicy> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy',
      method: 'put',
      pathParams: { dataset_id: datasetId },
      body: policy,
    })
  },

  async importIngestionPolicy(datasetId: string, file: File, replace = true): Promise<IngestionPolicyImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('replace', replace ? 'true' : 'false')
    const { data } = await apiClient.post(`/datasets/${datasetId}/ingestion-policy/import`, formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async exportIngestionPolicy(datasetId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/ingestion-policy/export`, {
      responseType: 'blob',
    })
    return data as Blob
  },

  async listIngestionPolicyVersions(datasetId: string): Promise<IngestionPolicyVersionListResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy/versions',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async rollbackIngestionPolicy(datasetId: string, body: IngestionPolicyRollbackRequest): Promise<IngestionPolicy> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy/rollback',
      method: 'post',
      pathParams: { dataset_id: datasetId },
      body,
    })
  },

  async exportConfig(datasetId: string): Promise<DatasetConfigExport> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/config/export',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async importConfig(datasetId: string, payload: DatasetConfigImportRequest): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/config/import',
      method: 'post',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  async clone(datasetId: string, payload: DatasetCloneRequest): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/clone',
      method: 'post',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  async exportDocumentsNdjson(
    datasetId: string,
    params?: {
      limit?: number
      after_created_at?: string
      after_id?: string
      include_sensitive?: boolean
      gzip?: boolean
    },
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/documents/export`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async exportBundleZip(datasetId: string, params?: { limit?: number; include_sensitive?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/export`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async getProfileSummary(datasetId: string, options: ApiRequestOptions = {}): Promise<DatasetProfileSummary> {
    const response = await apiClient.get<unknown>(`/datasets/${encodeURIComponent(datasetId)}/profile/summary`, {
      signal: options.signal,
    })
    return parseApiResponse(response, datasetProfileSchema, 'DatasetProfileSummary')
  },

  async listProfileFinding(
    datasetId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number },
    options: ApiRequestOptions = {},
  ): Promise<DatasetProfileFindingListResponse> {
    const response = await apiClient.get<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/profile/findings/${encodeURIComponent(findingKey)}`,
      { params, signal: options.signal },
    )
    return parseApiResponse(response, profileDocumentsSchema, 'DatasetProfileFindingDocuments')
  },

  async listProfileBucketDocuments(
    datasetId: string,
    params: {
      dimension: DatasetProfileBucketDimension
      bucket: string
      skip?: number
      limit?: number
      include_preview?: boolean
      preview_max_chars?: number
    },
    options: ApiRequestOptions = {},
  ): Promise<DatasetProfileDocumentListResponse> {
    const response = await apiClient.get<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/profile/buckets/documents`,
      { params, signal: options.signal },
    )
    return parseApiResponse(response, profileDocumentsSchema, 'DatasetProfileBucketDocuments')
  },

  async startProfileScan(
    datasetId: string,
    body: DatasetProfileScanRunCreateRequest,
  ): Promise<DatasetProfileScanRunOut> {
    const response = await apiClient.post<unknown>(`/datasets/${encodeURIComponent(datasetId)}/profile/scan-runs`, body)
    return parseApiResponse(response, profileScanRunSchema, 'DatasetProfileScanCreated')
  },

  async listProfileScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number },
    options: ApiRequestOptions = {},
  ): Promise<DatasetProfileScanRunListResponse> {
    const response = await apiClient.get<unknown>(`/datasets/${encodeURIComponent(datasetId)}/profile/scan-runs`, {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, profileScanRunsSchema, 'DatasetProfileScanRuns')
  },

  async listAllProfileScanRuns(
    datasetId: string,
    options: ApiRequestOptions = {},
  ): Promise<DatasetProfileScanRunOut[]> {
    const runs = new Map<string, DatasetProfileScanRunOut>()
    let skip = 0
    let page = await datasetApi.listProfileScanRuns(datasetId, { skip, limit: 200 }, options)
    const total = page.total
    while (true) {
      if (page.total !== total) throw new Error('扫描历史在读取期间发生变化，请重新读取')
      for (const run of page.items) runs.set(run.id, run)
      skip += page.items.length
      if (skip >= total) {
        if (runs.size !== total) throw new Error('扫描历史在读取期间发生变化，请重新读取')
        return [...runs.values()]
      }
      if (page.items.length === 0) throw new Error('扫描历史尚未完整返回，请重新读取')
      page = await datasetApi.listProfileScanRuns(datasetId, { skip, limit: 200 }, options)
    }
  },

  async getProfileScanRun(
    datasetId: string,
    scanRunId: string,
    options: ApiRequestOptions = {},
  ): Promise<DatasetProfileScanRunOut> {
    const response = await apiClient.get<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/profile/scan-runs/${encodeURIComponent(scanRunId)}`,
      { signal: options.signal },
    )
    return parseApiResponse(response, profileScanRunSchema, 'DatasetProfileScanRun')
  },

  async exportProfileSummary(datasetId: string, options: ApiRequestOptions = {}): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/datasets/${encodeURIComponent(datasetId)}/profile/export`, {
      responseType: 'blob',
      signal: options.signal,
    })
    return data
  },

  async exportProfileHtml(
    datasetId: string,
    params?: { redact?: boolean },
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/datasets/${encodeURIComponent(datasetId)}/profile/export-html`, {
      params,
      responseType: 'blob',
      signal: options.signal,
    })
    return data
  },

  async startPrecheckScan(
    datasetId: string,
    body: DatasetPrecheckScanRunCreateRequest,
  ): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post<DatasetPrecheckScanRunOut>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs`,
      body,
    )
    return data
  },

  async listPrecheckScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number },
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckScanRunListResponse> {
    const { data } = await apiClient.get<DatasetPrecheckScanRunListResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs`,
      { params, signal: options?.signal },
    )
    return data
  },

  async getPrecheckScanRun(
    datasetId: string,
    scanRunId: string,
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.get<DatasetPrecheckScanRunOut>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}`,
      { signal: options?.signal },
    )
    return data
  },

  async getPrecheckSummary(
    datasetId: string,
    scanRunId: string,
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckSummary> {
    const { data } = await apiClient.get<DatasetPrecheckSummary>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/summary`,
      { signal: options?.signal },
    )
    return data
  },

  async listPrecheckFinding(
    datasetId: string,
    scanRunId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number },
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckFindingListResponse> {
    const { data } = await apiClient.get<DatasetPrecheckFindingListResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/findings/${encodeURIComponent(findingKey)}`,
      { params, signal: options?.signal },
    )
    return data
  },

  async exportPrecheckSummary(datasetId: string, scanRunId: string, options?: ApiRequestOptions): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/export`,
      { responseType: 'blob', signal: options?.signal },
    )
    return data
  },

  async exportPrecheckHtml(
    datasetId: string,
    scanRunId: string,
    params?: { redact?: boolean },
    options?: ApiRequestOptions,
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/export-html`,
      { params, responseType: 'blob', signal: options?.signal },
    )
    return data
  },

  async cancelPrecheckScan(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/cancel`)
    return data
  },

  async getPrecheckSamples(
    datasetId: string,
    scanRunId: string,
    params?: { size?: number; prefer_artifact?: boolean },
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckSamplesResponse> {
    const { data } = await apiClient.get<DatasetPrecheckSamplesResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/samples`,
      { params, signal: options?.signal },
    )
    return data
  },

  async patchPrecheckSampleReview(
    datasetId: string,
    scanRunId: string,
    payload: DatasetPrecheckSampleReviewPatchRequest,
  ): Promise<DatasetPrecheckSampleReviewOut> {
    const { data } = await apiClient.patch(
      `/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/samples/review`,
      payload,
    )
    return data
  },

  async getPrecheckNearDups(
    datasetId: string,
    scanRunId: string,
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckNearDupResponse> {
    const { data } = await apiClient.get<DatasetPrecheckNearDupResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/near-dups`,
      { signal: options?.signal },
    )
    return data
  },

  async diffPrecheckScanRuns(
    datasetId: string,
    scanRunId: string,
    params: { base_scan_run_id: string },
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckDiffResponse> {
    const { data } = await apiClient.get<DatasetPrecheckDiffResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/diff`,
      { params, signal: options?.signal },
    )
    return data
  },

  async suggestPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { max_names_per_bucket?: number },
    options?: ApiRequestOptions,
  ): Promise<DatasetPrecheckIngestionSuggestionResponse> {
    const { data } = await apiClient.get<DatasetPrecheckIngestionSuggestionResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/suggest-ingestion-policy`,
      { params, signal: options?.signal },
    )
    return data
  },

  async applyPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { replace?: boolean },
  ): Promise<IngestionPolicyImportResponse> {
    const { data } = await apiClient.post(
      `/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/apply-ingestion-policy`,
      undefined,
      { params },
    )
    return data
  },

  async listTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; include_columns?: boolean; include_sample_rows?: boolean },
    options?: ApiRequestOptions,
  ): Promise<DatasetTablesListResponse> {
    const response = await apiClient.get<unknown>(`/datasets/${encodeURIComponent(datasetId)}/tables`, {
      params,
      signal: options?.signal,
    })
    const page = parseApiResponse(response, datasetTablesPageSchema, 'DatasetTablesListResponse')
    if (page.next_skip !== null && page.next_skip <= (params?.skip ?? 0)) {
      throw new Error('表格文档游标没有前进，请重新读取')
    }
    return page
  },

  async getTable(
    datasetId: string,
    tableId: string,
    params?: { include_columns?: boolean; include_sample_rows?: boolean },
    options?: ApiRequestOptions,
  ): Promise<DatasetTableAsset> {
    const response = await apiClient.get<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}`,
      { params, signal: options?.signal },
    )
    return parseApiResponse(response, tableAssetSchema, 'TableAssetOut')
  },

  async queryTable(datasetId: string, tableId: string, body: TableQueryRequest): Promise<TableQueryResponse> {
    const response = await apiClient.post<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}/query`,
      body,
    )
    return parseApiResponse(response, tableQueryResponseSchema, 'TableQueryResponse')
  },

  async askTable(datasetId: string, tableId: string, body: TableAskRequest): Promise<TableAskResponse> {
    const response = await apiClient.post<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}/ask`,
      body,
      { timeout: API_LONG_TIMEOUT_MS },
    )
    return parseApiResponse(response, tableAskResponseSchema, 'TableAskResponse')
  },

  async lotusSemFilter(datasetId: string, tableId: string, body: LotusSemFilterRequest): Promise<TableQueryResponse> {
    const response = await apiClient.post<unknown>(
      `/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}/lotus/sem-filter`,
      body,
      { timeout: API_LONG_TIMEOUT_MS },
    )
    return parseApiResponse(response, tableQueryResponseSchema, 'TableQueryResponse')
  },

  async listDbCatalogTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; engine?: string; q?: string },
    options?: ApiRequestOptions,
  ): Promise<DbCatalogTablesListResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/db-catalog/tables',
      method: 'get',
      pathParams: { dataset_id: datasetId },
      query: params,
      signal: options?.signal,
    })
  },

  async getDbCatalogTable(
    datasetId: string,
    tableId: string,
    options?: ApiRequestOptions,
  ): Promise<DbCatalogTableDetail> {
    const { data } = await apiClient.get<DbCatalogTableDetail>(
      `/datasets/${encodeURIComponent(datasetId)}/db-catalog/tables/${encodeURIComponent(tableId)}`,
      { signal: options?.signal },
    )
    return data
  },

  async listDbCatalogProfiles(
    datasetId: string,
    params: { table_id: string; entitlement_hash?: string; skip?: number; limit?: number },
    options?: ApiRequestOptions,
  ): Promise<DbProfileSnapshotListResponse> {
    const { data } = await apiClient.get<DbProfileSnapshotListResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/db-catalog/profiles`,
      { params, signal: options?.signal },
    )
    return data
  },
}

export const datasetCategoryApi = {
  async listTree(options: ApiRequestOptions = {}): Promise<DatasetCategoryTreeResponse> {
    return openapiRequest({ path: '/api/v1/dataset-categories/', method: 'get', signal: options.signal })
  },

  async create(payload: DatasetCategoryCreate): Promise<DatasetCategoryOut> {
    return openapiRequest({ path: '/api/v1/dataset-categories/', method: 'post', body: payload })
  },

  async update(categoryId: string, payload: DatasetCategoryUpdate): Promise<DatasetCategoryOut> {
    return openapiRequest({
      path: '/api/v1/dataset-categories/{category_id}',
      method: 'patch',
      pathParams: { category_id: categoryId },
      body: payload,
    })
  },

  async move(categoryId: string, payload: DatasetCategoryMoveRequest): Promise<DatasetCategoryOut> {
    return openapiRequest({
      path: '/api/v1/dataset-categories/{category_id}/move',
      method: 'post',
      pathParams: { category_id: categoryId },
      body: payload,
    })
  },

  async delete(categoryId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/dataset-categories/{category_id}',
      method: 'delete',
      pathParams: { category_id: categoryId },
    })
  },
}
