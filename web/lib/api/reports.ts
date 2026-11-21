import { datasetReportSchema, type DatasetReport } from '@/lib/report-schema'
import { parseApiResponse } from '@/lib/openapi-request'
import { matchesResourceId } from '@/lib/resource-id'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'

type DatasetReportQuery = OpenApiQueryParams<'/api/v1/reports/datasets/{dataset_id}', 'get'>
type DatasetReportExportQuery = OpenApiQueryParams<'/api/v1/reports/datasets/{dataset_id}/export-html', 'get'>

export const reportApi = {
  async getDatasetReport(
    datasetId: string,
    params?: DatasetReportQuery,
    options: ApiRequestOptions = {},
  ): Promise<DatasetReport> {
    const response = await apiClient.get<unknown>(`/reports/datasets/${encodeURIComponent(datasetId)}`, {
      params,
      signal: options.signal,
    })
    const report = parseApiResponse(response, datasetReportSchema, 'DatasetReport')
    if (!matchesResourceId(report.dataset_id, datasetId)) throw new Error('报告的数据集不匹配，请重新读取')
    return report
  },

  async exportDatasetReportJson(
    datasetId: string,
    params?: DatasetReportQuery,
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/reports/datasets/${encodeURIComponent(datasetId)}/export`, {
      params,
      responseType: 'blob',
      signal: options.signal,
    })
    return data
  },

  async exportDatasetReportHtml(
    datasetId: string,
    params?: DatasetReportExportQuery,
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/reports/datasets/${encodeURIComponent(datasetId)}/export-html`, {
      params,
      responseType: 'blob',
      signal: options.signal,
    })
    return data
  },

  async exportDatasetRagAuditHtml(
    datasetId: string,
    params?: DatasetReportExportQuery,
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/reports/datasets/${encodeURIComponent(datasetId)}/rag-audit/export-html`,
      {
        params,
        responseType: 'blob',
        signal: options.signal,
      },
    )
    return data
  },

  async exportDatasetReportBundleZip(
    datasetId: string,
    params?: DatasetReportExportQuery,
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/reports/datasets/${encodeURIComponent(datasetId)}/export-bundle`, {
      params,
      responseType: 'blob',
      signal: options.signal,
    })
    return data
  },
}
