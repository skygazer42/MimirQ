import type {
  Dataset,
  DatasetCategoryAssignmentRequest,
  DatasetCategoryAssignmentResponse,
  DatasetCategoryCreate,
  DatasetCategoryMoveRequest,
  DatasetCategoryOut,
  DatasetCategoryTreeResponse,
  DatasetCategoryUpdate,
  DatasetCloneRequest,
  DatasetConfigExport,
  DatasetConfigImportRequest,
  DatasetCreate,
  DatasetHealthResponse,
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
  DatasetProfileDocumentListResponse,
  DatasetProfileFindingListResponse,
  DatasetProfileScanRunCreateRequest,
  DatasetProfileScanRunListResponse,
  DatasetProfileScanRunOut,
  DatasetProfileSummary,
  DatasetTableAsset,
  DatasetTablesListResponse,
  DatasetUpdate,
  DbCatalogTableDetail,
  DbCatalogTablesListResponse,
  DbProfileSnapshotListResponse,
  IngestionPolicy,
  IngestionPolicyImportResponse,
  IngestionPolicyRollbackRequest,
  IngestionPolicyVersionListResponse,
  LotusSemFilterRequest,
  TableAskRequest,
  TableAskResponse,
  TableQueryRequest,
  TableQueryResponse,
} from '@/types'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest } from '@/lib/api/core'

export type DatasetAnalysisFilters = {
  from_ts?: string
  to_ts?: string
  feedback_polarity?: string
  category?: string
}

export type DatasetAnalysisDashboardParams = Omit<DatasetAnalysisFilters, 'category'> & {
  limit?: number
}

export type DatasetAnalysisExamplesParams = DatasetAnalysisFilters & {
  limit?: number
}

export type DatasetAnalysisRuleSuggestionParams = Omit<DatasetAnalysisFilters, 'category'> & {
  ruleset: string
  limit?: number
}

export type DatasetAnalysisGlossaryWritebackParams = DatasetAnalysisFilters & {
  ruleset: string
  limit?: number
}

export type DatasetAnalysisResponse = Record<string, unknown>
export type DatasetPurgeResponse = Record<string, unknown>
export type DatasetRetrievalAuditPayload = {
  status: string
  plugin_refs?: string[]
  plugin_package_hashes?: string[]
  gates?: Array<{
    name: string
    status: string
    metrics?: Record<string, unknown>
    failed_conditions?: string[]
    generated_at?: string | null
    source?: string | null
  }>
  failure_categories?: Record<string, number>
  kg_recommendation?: string | null
  recommended_next_action?: string | null
}

export const datasetApi = {
  async create(params: DatasetCreate): Promise<Dataset> {
    return openapiRequest({ path: '/api/v1/datasets/', method: 'post', body: params })
  },

  async list(params?: {
    skip?: number
    limit?: number
    category_id?: string
    include_descendants?: boolean
  }): Promise<DatasetListResponse> {
    return openapiRequest({ path: '/api/v1/datasets/', method: 'get', query: params })
  },

  async get(datasetId: string): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async getIngestionStats(datasetId: string): Promise<DatasetIngestionStats> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion/stats',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async getHealth(datasetId: string): Promise<DatasetHealthResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/health',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async putRetrievalAudit(
    datasetId: string,
    payload: DatasetRetrievalAuditPayload
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

  async getAnalysisSummary(
    datasetId: string,
    params?: DatasetAnalysisFilters
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/summary`, { params })
    return data
  },

  async getAnalysisExamples(
    datasetId: string,
    params?: DatasetAnalysisExamplesParams
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/examples`, { params })
    return data
  },

  async getAnalysisRuleSuggestions(
    datasetId: string,
    params: DatasetAnalysisRuleSuggestionParams
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/analysis/rule-suggestions`, { params })
    return data
  },

  async exportAnalysisJson(
    datasetId: string,
    params?: DatasetAnalysisFilters
  ): Promise<DatasetAnalysisResponse> {
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
    params: DatasetAnalysisGlossaryWritebackParams
  ): Promise<DatasetAnalysisResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/analysis/glossary-writeback`, undefined, { params })
    return data
  },

  async createAnalysisPngExportTask(
    datasetId: string,
    params?: DatasetAnalysisFilters
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

  async getCategories(datasetId: string): Promise<DatasetCategoryAssignmentResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/categories',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async setCategories(datasetId: string, payload: DatasetCategoryAssignmentRequest): Promise<DatasetCategoryAssignmentResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/categories',
      method: 'put',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  async delete(datasetId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'delete',
      pathParams: { dataset_id: datasetId },
    })
  },

  async purge(
    datasetId: string,
    params?: { max_delete?: number; dry_run?: boolean }
  ): Promise<DatasetPurgeResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/purge`, undefined, { params })
    return data
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
    }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/documents/export`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async exportBundleZip(
    datasetId: string,
    params?: { limit?: number; include_sensitive?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/export`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async getProfileSummary(datasetId: string): Promise<DatasetProfileSummary> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/summary`)
    return data
  },

  async listProfileFinding(
    datasetId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetProfileFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/findings/${findingKey}`, { params })
    return data
  },

  async listProfileBucketDocuments(
    datasetId: string,
    params: {
      dimension: 'file_type' | 'language' | 'directory' | 'quality_bucket'
      bucket: string
      skip?: number
      limit?: number
      include_preview?: boolean
      preview_max_chars?: number
    }
  ): Promise<DatasetProfileDocumentListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/buckets/documents`, { params })
    return data
  },

  async startProfileScan(datasetId: string, body: DatasetProfileScanRunCreateRequest): Promise<DatasetProfileScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/profile/scan-runs`, body || {})
    return data
  },

  async listProfileScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetProfileScanRunListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/scan-runs`, { params })
    return data
  },

  async getProfileScanRun(datasetId: string, scanRunId: string): Promise<DatasetProfileScanRunOut> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/scan-runs/${scanRunId}`)
    return data
  },

  async exportProfileSummary(datasetId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/export`, { responseType: 'blob' })
    return data as Blob
  },

  async exportProfileHtml(datasetId: string, params?: { redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/export-html`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async startPrecheckScan(datasetId: string, body: DatasetPrecheckScanRunCreateRequest): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs`, body || {})
    return data
  },

  async listPrecheckScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetPrecheckScanRunListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs`, { params })
    return data
  },

  async getPrecheckScanRun(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}`)
    return data
  },

  async getPrecheckSummary(datasetId: string, scanRunId: string): Promise<DatasetPrecheckSummary> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/summary`)
    return data
  },

  async listPrecheckFiles(
    datasetId: string,
    scanRunId: string,
    params?: { dir_prefix?: string; skip?: number; limit?: number }
  ): Promise<DatasetPrecheckFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/files`, { params })
    return data
  },

  async listPrecheckFinding(
    datasetId: string,
    scanRunId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetPrecheckFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/findings/${findingKey}`, {
      params,
    })
    return data
  },

  async exportPrecheckSummary(datasetId: string, scanRunId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/export`, {
      responseType: 'blob',
    })
    return data as Blob
  },

  async exportPrecheckHtml(datasetId: string, scanRunId: string, params?: { redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/export-html`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async cancelPrecheckScan(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/cancel`)
    return data
  },

  async getPrecheckSamples(
    datasetId: string,
    scanRunId: string,
    params?: { size?: number; prefer_artifact?: boolean }
  ): Promise<DatasetPrecheckSamplesResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/samples`, { params })
    return data
  },

  async patchPrecheckSampleReview(
    datasetId: string,
    scanRunId: string,
    payload: DatasetPrecheckSampleReviewPatchRequest
  ): Promise<DatasetPrecheckSampleReviewOut> {
    const { data } = await apiClient.patch(
      `/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/samples/review`,
      payload
    )
    return data
  },

  async getPrecheckNearDups(datasetId: string, scanRunId: string): Promise<DatasetPrecheckNearDupResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/near-dups`)
    return data
  },

  async diffPrecheckScanRuns(
    datasetId: string,
    scanRunId: string,
    params: { base_scan_run_id: string }
  ): Promise<DatasetPrecheckDiffResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/diff`, { params })
    return data
  },

  async suggestPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { max_names_per_bucket?: number }
  ): Promise<DatasetPrecheckIngestionSuggestionResponse> {
    const { data } = await apiClient.get(
      `/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/suggest-ingestion-policy`,
      { params }
    )
    return data
  },

  async applyPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { replace?: boolean }
  ): Promise<IngestionPolicyImportResponse> {
    const { data } = await apiClient.post(
      `/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/apply-ingestion-policy`,
      undefined,
      { params }
    )
    return data
  },

  async listTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; include_columns?: boolean; include_sample_rows?: boolean }
  ): Promise<DatasetTablesListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables`, { params })
    return data
  },

  async getTable(
    datasetId: string,
    tableId: string,
    params?: { include_columns?: boolean; include_sample_rows?: boolean }
  ): Promise<DatasetTableAsset> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}`, { params })
    return data
  },

  async previewTable(datasetId: string, tableId: string, params?: { limit?: number }): Promise<TableQueryResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/preview`, { params })
    return data
  },

  async queryTable(datasetId: string, tableId: string, body: TableQueryRequest): Promise<TableQueryResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/query`, body)
    return data
  },

  async askTable(datasetId: string, tableId: string, body: TableAskRequest): Promise<TableAskResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/ask`, body, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async lotusSemFilter(datasetId: string, tableId: string, body: LotusSemFilterRequest): Promise<TableQueryResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/lotus/sem-filter`, body, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async listDbCatalogTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; engine?: string; q?: string }
  ): Promise<DbCatalogTablesListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/db-catalog/tables`, { params })
    return data
  },

  async getDbCatalogTable(datasetId: string, tableId: string): Promise<DbCatalogTableDetail> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/db-catalog/tables/${encodeURIComponent(tableId)}`)
    return data
  },

  async listDbCatalogProfiles(
    datasetId: string,
    params: { table_id: string; entitlement_hash?: string; skip?: number; limit?: number }
  ): Promise<DbProfileSnapshotListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/db-catalog/profiles`, { params })
    return data
  },
}

export const datasetCategoryApi = {
  async listTree(): Promise<DatasetCategoryTreeResponse> {
    return openapiRequest({ path: '/api/v1/dataset-categories/', method: 'get' })
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
