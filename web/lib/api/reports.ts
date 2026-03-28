import type { DatasetReport } from '@/types'

import { apiClient } from '@/lib/api/core'

export const reportApi = {
  async getDatasetReport(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number }
  ): Promise<DatasetReport> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}`, { params })
    return data
  },

  async exportDatasetReportJson(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetReportHtml(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetRagAuditHtml(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/rag-audit/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetReportBundleZip(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export-bundle`, { params, responseType: 'blob' })
    return data as Blob
  },
}
