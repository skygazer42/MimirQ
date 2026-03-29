import type {
  EvidenceHardcaseDiscovery,
  EvidenceItem,
  EvidenceItemCreate,
  EvidenceItemImportResponse,
  EvidenceItemList,
  EvidenceItemPatch,
  EvidenceReferenceDriftAudit,
  EvidenceReferenceRepairRequest,
  EvidenceReferenceRepairResponse,
  EvidenceSuite,
  EvidenceSuiteCreate,
  EvidenceSuiteDashboard,
  EvidenceSuiteExportV1,
  EvidenceSuiteList,
  EvidenceSuitePatch,
  EvidenceSuiteSyncRegressionResponse,
} from '@/types'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest } from '@/lib/api/core'

export const evidenceApi = {
  async createSuite(payload: EvidenceSuiteCreate): Promise<EvidenceSuite> {
    return openapiRequest({ path: '/api/v1/evidence/suites', method: 'post', body: payload })
  },

  async listSuites(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    include_archived?: boolean
  }): Promise<EvidenceSuiteList> {
    return openapiRequest({ path: '/api/v1/evidence/suites', method: 'get', query: params })
  },

  async getSuite(suiteId: string): Promise<EvidenceSuite> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}',
      method: 'get',
      pathParams: { suite_id: suiteId },
    })
  },

  async getSuiteDashboard(
    suiteId: string,
    params?: { include_archived_items?: boolean; top_n?: number; heatmap_top_n?: number }
  ): Promise<EvidenceSuiteDashboard> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/dashboard',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async getSuiteHardcaseCandidates(
    suiteId: string,
    params?: {
      window_minutes?: number
      max_bytes?: number
      max_feedback_rows?: number
      max_candidates?: number
      max_rating?: number
      include_existing?: boolean
    }
  ): Promise<EvidenceHardcaseDiscovery> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/hardcase-candidates',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async getSuiteDriftAudit(
    suiteId: string,
    params?: {
      include_archived_items?: boolean
      include_details?: boolean
      details_limit?: number
      slice_top_n?: number
    }
  ): Promise<EvidenceReferenceDriftAudit> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/drift-audit',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async getDatasetDriftAudit(
    datasetId: string,
    params?: {
      include_archived_items?: boolean
      include_details?: boolean
      details_limit?: number
      slice_top_n?: number
    }
  ): Promise<EvidenceReferenceDriftAudit> {
    return openapiRequest({
      path: '/api/v1/evidence/datasets/{dataset_id}/drift-audit',
      method: 'get',
      pathParams: { dataset_id: datasetId },
      query: params,
    })
  },

  async repairSuiteReferenceSources(
    suiteId: string,
    payload: EvidenceReferenceRepairRequest
  ): Promise<EvidenceReferenceRepairResponse> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/repair-reference-sources',
      method: 'post',
      pathParams: { suite_id: suiteId },
      body: payload,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
  },

  async patchSuite(suiteId: string, payload: EvidenceSuitePatch): Promise<EvidenceSuite> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}',
      method: 'patch',
      pathParams: { suite_id: suiteId },
      body: payload,
    })
  },

  async createItem(suiteId: string, payload: EvidenceItemCreate): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/items',
      method: 'post',
      pathParams: { suite_id: suiteId },
      body: { ...payload, suite_id: suiteId },
    })
  },

  async listItems(
    suiteId: string,
    params?: { skip?: number; limit?: number; status?: string }
  ): Promise<EvidenceItemList> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/items',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async patchItem(itemId: string, payload: EvidenceItemPatch): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}',
      method: 'patch',
      pathParams: { item_id: itemId },
      body: payload,
    })
  },

  async reviewItem(itemId: string): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}/review',
      method: 'post',
      pathParams: { item_id: itemId },
    })
  },

  async approveItem(itemId: string): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}/approve',
      method: 'post',
      pathParams: { item_id: itemId },
    })
  },

  async archiveItem(itemId: string): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}/archive',
      method: 'post',
      pathParams: { item_id: itemId },
    })
  },

  async syncSuiteToRegression(suiteId: string): Promise<EvidenceSuiteSyncRegressionResponse> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/sync-regression',
      method: 'post',
      pathParams: { suite_id: suiteId },
    })
  },

  async exportSuite(suiteId: string, params?: { include_archived_items?: boolean }): Promise<EvidenceSuiteExportV1> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/export',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async exportSuiteLtrTrainingBundleZip(
    suiteId: string,
    params?: { include_archived_items?: boolean; max_items?: number }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/evidence/suites/${suiteId}/export-ltr-training`, {
      params,
      responseType: 'blob',
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data as Blob
  },

  async exportTrainingDataset(params: {
    dataset_id: string
    format?: 'jsonl' | 'csv'
    include_feedback?: boolean
    include_evidence?: boolean
    include_archived_evidence?: boolean
    max_rows_per_source?: number
  }): Promise<Blob> {
    const { data } = await apiClient.get('/evidence/training-export', {
      params,
      responseType: 'blob',
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data as Blob
  },

  async importItems(
    suiteId: string,
    file: File,
    params?: { max_items?: number }
  ): Promise<EvidenceItemImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await apiClient.post(`/evidence/suites/${suiteId}/items/import`, formData, {
      params,
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async persistCapsule(payload: {
    capsule: Record<string, unknown>
    capsule_id?: string | null
    overwrite?: boolean
  }): Promise<{ capsule_id: string; capsule_hash: string; path: string; overwritten: boolean }> {
    const { data } = await apiClient.post('/evidence/capsules', payload)
    return data
  },

  async getCapsule(capsuleId: string): Promise<{ capsule_id: string; capsule_hash: string; capsule: Record<string, unknown> }> {
    const { data } = await apiClient.get(`/evidence/capsules/${encodeURIComponent(capsuleId)}`)
    return data
  },

  async verifyCapsule(payload: {
    capsule: Record<string, unknown>
    capsule_id?: string | null
    overwrite?: boolean
  }): Promise<{ capsule_id?: string | null; valid: boolean; reason: string }> {
    const { data } = await apiClient.post('/evidence/capsules/verify', payload)
    return data
  },
}
