import type { Dataset } from '@/types/datasets'
import type { DatasetReport, DatasetReportPipelineVersion } from '@/lib/report-schema'

export type ReportMetricDatum = { name: string; value: number }
export type CategoryMetricDatum = ReportMetricDatum & { key: string; depth: number }
export type ReportRecordRow = { label: string; count: number; total: number }
export type DatasetOption = Pick<Dataset, 'id' | 'name'>
export type PipelineVersionOption = DatasetReportPipelineVersion
export type ReportFinding = DatasetReport['profile']['findings'][number]
export type RetrievalAudit = NonNullable<DatasetReport['retrieval_audit']>
export type ReportExportParams = {
  pipeline_hash?: string
  connector_runs_limit: number
  redact?: boolean
}
