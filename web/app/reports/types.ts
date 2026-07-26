import type { datasetApi } from '@/lib/api/datasets'
import type {
  DatasetReport,
  DatasetReportPipelineVersion,
} from '@/types'

export type DataPillTone = 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
export type ReportMetricDatum = { name: string; value: number }
export type CategoryMetricDatum = ReportMetricDatum & { depth: number }
export type CoverageRow = { label: string; value: number; max: number }
export type DatasetOption = Awaited<ReturnType<typeof datasetApi.list>>['items'][number]
export type PipelineVersionOption = { pipeline_hash: string; documents: number }
export type ReportFinding = DatasetReport['profile']['findings'][number]
export type ReportConnectorRun = DatasetReport['connectors'][number]
export type RetrievalAudit = NonNullable<DatasetReport['retrieval_audit']>
export type RetrievalAuditMetricRow = {
  key: string
  label: string
  value: string
}
export type IssueRow = {
  id: string
  time: string
  level: string
  type: string
  description: string
  target: string
}
export type PipelineVersionDatum = DatasetReportPipelineVersion & {
  display_label: string
  fill: string
}
export type ReportExportParams = {
  pipeline_hash?: string
  connector_runs_limit: number
  redact?: boolean
}
