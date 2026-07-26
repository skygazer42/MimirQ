'use client'

import { toast } from 'sonner'

import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { sanitizeFilename } from '@/lib/sanitize'

import type { DatasetReport } from '@/types'

import type {
  CategoryMetricDatum,
  CoverageRow,
  ReportExportParams,
  ReportFinding,
  ReportMetricDatum,
} from './types'

type ReportBlobExporter = (
  datasetId: string,
  params: ReportExportParams
) => Promise<Blob>

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function reportPipelineSuffix(pipelineHash: string) {
  const hash = pipelineHash.trim()
  return hash ? `.${hash.slice(0, 8)}` : ''
}

export function reportExportParams(
  pipelineHash: string,
  connectorRunsLimit: number,
  redact?: boolean
): ReportExportParams {
  const params: ReportExportParams = {
    connector_runs_limit: connectorRunsLimit,
  }
  const hash = pipelineHash.trim()
  if (hash) params.pipeline_hash = hash
  if (redact !== undefined) params.redact = redact
  return params
}

export async function exportReportBlobFile({
  datasetId,
  datasetName,
  pipelineHash,
  connectorRunsLimit,
  redact,
  setLoading,
  getBlob,
  filenameStem,
  extension,
  errorFallback,
}: Readonly<{
  datasetId: string
  datasetName: string
  pipelineHash: string
  connectorRunsLimit: number
  redact?: boolean
  setLoading: (loading: boolean) => void
  getBlob: ReportBlobExporter
  filenameStem: string
  extension: string
  errorFallback: string
}>) {
  if (!datasetId) return
  setLoading(true)
  try {
    const blob = await getBlob(
      datasetId,
      reportExportParams(pipelineHash, connectorRunsLimit, redact)
    )
    const safe = sanitizeFilename(datasetName || 'dataset')
    downloadBlob(blob, `${safe}.${filenameStem}${reportPipelineSuffix(pipelineHash)}.${extension}`)
  } catch (e: unknown) {
    reportClientError(errorFallback, e)
    toast.error(formatApiError(e, errorFallback))
  } finally {
    setLoading(false)
  }
}

export function downloadReportJsonPayload({
  datasetName,
  pipelineHash,
  filenameStem,
  payload,
}: Readonly<{
  datasetName: string
  pipelineHash: string
  filenameStem: string
  payload: unknown
}>) {
  const safe = sanitizeFilename(datasetName || 'dataset')
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  downloadBlob(blob, `${safe}.${filenameStem}${reportPipelineSuffix(pipelineHash)}.json`)
}

export function exportChartsJsonPayload({
  datasetId,
  report,
  selectedDatasetName,
  pipelineHash,
  dropReasonsData,
  rulePacksData,
  govAuditCharData,
  govAuditReductionHistData,
  govAuditDensityHistData,
  govAuditHeadingRatioHistData,
  govAuditEffectsData,
  folderQuery,
  folderBarData,
  categoryQuery,
  categoryBarData,
}: Readonly<{
  datasetId: string
  report: DatasetReport | null
  selectedDatasetName?: string | null
  pipelineHash: string
  dropReasonsData: ReportMetricDatum[]
  rulePacksData: ReportMetricDatum[]
  govAuditCharData: ReportMetricDatum[]
  govAuditReductionHistData: ReportMetricDatum[]
  govAuditDensityHistData: ReportMetricDatum[]
  govAuditHeadingRatioHistData: ReportMetricDatum[]
  govAuditEffectsData: ReportMetricDatum[]
  folderQuery: string
  folderBarData: ReportMetricDatum[]
  categoryQuery: string
  categoryBarData: CategoryMetricDatum[]
}>) {
  if (!datasetId || !report) return
  downloadReportJsonPayload({
    datasetName: selectedDatasetName || report.dataset_name || 'dataset',
    pipelineHash,
    filenameStem: 'charts',
    payload: {
      schema: 'mimirq.report_charts.v1',
      exported_at: new Date().toISOString(),
      dataset: {
        id: datasetId,
        name: selectedDatasetName || report.dataset_name || null,
      },
      pipeline_hash: report.pipeline_hash || null,
      governance: {
        metrics: report.governance_metrics || null,
        audit: report.governance_audit || null,
        drop_reasons_top: dropReasonsData,
        rule_packs_top: rulePacksData,
        audit_chars: govAuditCharData,
        audit_reduction_histogram: govAuditReductionHistData,
        audit_density_histogram: govAuditDensityHistData,
        audit_heading_ratio_histogram: govAuditHeadingRatioHistData,
        audit_effects_top: govAuditEffectsData,
      },
      folders: {
        query: folderQuery,
        top: folderBarData,
      },
      categories: {
        query: categoryQuery,
        top: categoryBarData,
      },
    },
  })
}

export function exportCompleteReportJsonPayload({
  datasetId,
  report,
  selectedDatasetName,
  pipelineHash,
  successDocs,
  successRate,
  failedRate,
  sensitiveHits,
  findingRows,
  fieldCoverageRows,
  topDocumentRows,
  categoryBarData,
  versionTotal,
}: Readonly<{
  datasetId: string
  report: DatasetReport | null
  selectedDatasetName?: string | null
  pipelineHash: string
  successDocs: number
  successRate: string
  failedRate: string
  sensitiveHits: number
  findingRows: ReportFinding[]
  fieldCoverageRows: CoverageRow[]
  topDocumentRows: ReportMetricDatum[]
  categoryBarData: CategoryMetricDatum[]
  versionTotal: number
}>) {
  if (!datasetId || !report) return
  downloadReportJsonPayload({
    datasetName: selectedDatasetName || report.dataset_name || 'dataset',
    pipelineHash,
    filenameStem: 'complete-report',
    payload: {
      schema: 'mimirq.dataset_report_complete.v1',
      exported_at: new Date().toISOString(),
      report,
      derived: {
        success_documents: successDocs,
        success_rate: successRate,
        failed_rate: failedRate,
        sensitive_hits: sensitiveHits,
        risk_findings: findingRows,
        field_coverage: fieldCoverageRows,
        top_documents: topDocumentRows,
        category_top: categoryBarData,
        pipeline_version_total: versionTotal,
      },
    },
  })
}
