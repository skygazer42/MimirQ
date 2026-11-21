'use client'

import type { DatasetReport } from '@/lib/report-schema'
import { downloadBlob } from '@/lib/download'
import { buildReportCharts, buildReportOverview } from './report-overview-model'
import type { CategoryMetricDatum, ReportExportParams } from './types'

export function reportPipelineSuffix(pipelineHash: string | null) {
  if (pipelineHash === null) return ''
  const hash = pipelineHash.trim()
  return hash.length > 0 ? `.${hash.slice(0, 8)}` : ''
}

export function reportExportParams(
  pipelineHash: string,
  connectorRunsLimit: number,
  redact?: boolean,
): ReportExportParams {
  const params: ReportExportParams = { connector_runs_limit: connectorRunsLimit }
  const hash = pipelineHash.trim()
  if (hash.length > 0) params.pipeline_hash = hash
  if (redact !== undefined) params.redact = redact
  return params
}

function downloadReportJson(report: DatasetReport, stem: string, payload: Record<string, unknown>) {
  const filename = `${report.dataset_id}.${stem}${reportPipelineSuffix(report.pipeline_hash)}.json`
  downloadBlob(filename, new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }))
}

type CategorySnapshot = Readonly<{
  status: 'pending' | 'error' | 'success'
  rows: readonly CategoryMetricDatum[] | undefined
}>

export function downloadReportChartsJson(report: DatasetReport, categories: CategorySnapshot) {
  downloadReportJson(report, 'charts', {
    schema: 'mimirq.report_charts.v2',
    exported_at: new Date().toISOString(),
    generated_at: report.generated_at,
    dataset: { id: report.dataset_id, name: report.dataset_name },
    pipeline_hash: report.pipeline_hash,
    governance_metrics: report.governance_metrics,
    ...buildReportCharts(report),
    categories: { scope: 'tenant', status: categories.status, top: categories.rows },
  })
}

export function downloadCompleteReportJson(report: DatasetReport, categories: CategorySnapshot) {
  const overview = buildReportOverview(report)
  downloadReportJson(report, 'complete-report', {
    schema: 'mimirq.dataset_report_complete.v2',
    exported_at: new Date().toISOString(),
    report,
    derived: {
      completed_documents: overview.completedDocuments,
      completion_percent: overview.completionPercent,
      failed_documents: overview.failedDocuments,
      failure_percent: overview.failurePercent,
      sensitive_hits: overview.sensitiveHits,
      document_records: overview.documentRecords,
      governance_records: overview.governanceRecords,
      categories: { scope: 'tenant', status: categories.status, top: categories.rows },
    },
  })
}
