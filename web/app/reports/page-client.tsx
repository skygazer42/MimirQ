'use client'

import { wrap, type Remote } from 'comlink'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  Archive,
  BarChart3,
  CheckCircle2,
  Clock3,
  Database,
  Download,
  FileSearch,
  FileText,
  Layers,
  Loader2,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { PageHeader } from '@/components/ui/page-header'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Label } from '@/components/ui/label'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'
import { reportApi } from '@/lib/api/reports'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError, reportClientWarning } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { flattenFolderTree } from '@/lib/report-transforms'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'

import type { FlatFolderRow } from '@/lib/report-transforms'
import type {
  DatasetCategoryNode,
  DatasetReport,
  DatasetReportDataProvenance,
  DatasetReportPipelineVersion,
} from '@/types'
import type { ReportTransformsWorkerApi } from '@/workers/report-transforms.worker'

const PIE_COLORS = [
  '#3b82f6',
  '#0ea5e9',
  '#14b8a6',
  '#22c55e',
  '#f59e0b',
  '#6366f1',
  '#64748b',
]
const CHART_TOOLTIP_STYLE = {
  borderRadius: 10,
  border: '1px solid #cbd5e1',
  background: 'rgba(255,255,255,0.96)',
  boxShadow: '0 8px 26px rgba(15,23,42,0.12)',
  padding: '8px 10px',
}
const CHART_TOOLTIP_LABEL_STYLE = { color: '#334155', fontWeight: 600 }
const CHART_TOOLTIP_CURSOR = { fill: 'rgba(148,163,184,0.08)' }
const DEFAULT_PIPELINE_VERSION_VALUE = '__mimirq_default_pipeline_version__'
const REPORT_LABEL_CLASS =
  'text-[0.6875rem] font-medium uppercase tracking-[0.11em] text-slate-500/90'
const REPORT_VALUE_CLASS =
  'truncate text-[0.875rem] font-semibold leading-5 tracking-[-0.01em] text-slate-900'
const REPORT_SUBTEXT_CLASS = 'text-[0.75rem] leading-5 text-slate-500'
const REPORT_METRIC_VALUE_CLASS =
  'text-[1.375rem] font-semibold leading-none tracking-[-0.035em] tabular-nums text-slate-950'
const REPORT_RISK_VALUE_CLASS =
  'text-[1.25rem] font-semibold leading-none tracking-[-0.03em] tabular-nums'
const REPORT_PANEL_TITLE_CLASS =
  'text-[0.9375rem] font-semibold leading-6 tracking-[-0.015em] text-slate-950'
const REPORT_TABLE_HEADER_CLASS =
  'text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-slate-500'
const REPORT_TABLE_ROW_CLASS = 'text-[0.8125rem] leading-5 text-slate-700'
type DataPillTone = 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
type ReportMetricDatum = { name: string; value: number }
type CategoryMetricDatum = ReportMetricDatum & { depth: number }
type CoverageRow = { label: string; value: number; max: number }
type DatasetOption = Awaited<ReturnType<typeof datasetApi.list>>['items'][number]
type PipelineVersionOption = { pipeline_hash: string; documents: number }
type ReportFinding = DatasetReport['profile']['findings'][number]
type ReportConnectorRun = DatasetReport['connectors'][number]
type RetrievalAudit = NonNullable<DatasetReport['retrieval_audit']>
type RetrievalAuditMetricRow = {
  key: string
  label: string
  value: string
}
type IssueRow = {
  id: string
  time: string
  level: string
  type: string
  description: string
  target: string
}
type PipelineVersionDatum = DatasetReportPipelineVersion & { fill: string }
type ReportExportParams = {
  pipeline_hash?: string
  connector_runs_limit: number
  redact?: boolean
}
type ReportBlobExporter = (
  datasetId: string,
  params: ReportExportParams
) => Promise<Blob>
type RefetchFn = () => unknown

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function reportPipelineSuffix(pipelineHash: string) {
  const hash = pipelineHash.trim()
  return hash ? `.${hash.slice(0, 8)}` : ''
}

function reportExportParams(
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

function selectedPipelineHashValue(value: string) {
  if (value === DEFAULT_PIPELINE_VERSION_VALUE) return ''
  return value
}

function refreshReportQueries(
  datasetId: string,
  refetchDatasets: RefetchFn,
  refetchCategories: RefetchFn,
  refetchReport: RefetchFn
) {
  refetchDatasets()
  refetchCategories()
  if (datasetId) refetchReport()
}

async function exportReportBlobFile({
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

function downloadReportJsonPayload({
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

function exportChartsJsonPayload({
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

function exportCompleteReportJsonPayload({
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

function shortPipelineHash(hash: string) {
  const value = String(hash || '').trim()
  if (value.length <= 18) return value
  return `${value.slice(0, 10)}…${value.slice(-6)}`
}

function safeNumber(value: unknown): number {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n : 0
}

function formatPct(numerator: number, denominator: number) {
  if (!denominator || !Number.isFinite(denominator)) return '0%'
  return `${((numerator / denominator) * 100).toFixed(1).replace('.0', '')}%`
}

function sumRecordValues(value: Record<string, number> | null | undefined) {
  return Object.values(value || {}).reduce(
    (acc, item) => acc + safeNumber(item),
    0
  )
}

function capCoverageValue(value: unknown, max: number) {
  if (max <= 0) return 0
  return Math.max(0, Math.min(max, safeNumber(value)))
}

function reportStatusLabel(isLoadingReport: boolean, report: DatasetReport | null | undefined): string {
  if (isLoadingReport) return '生成中'
  if (report) return '已生成'
  return '待生成'
}

function reportDataSourceLabel(dataProvenance: DatasetReportDataProvenance | null | undefined): string {
  if (dataProvenance?.mocked === false && dataProvenance.source === 'database') {
    return '真实后端数据'
  }
  if (dataProvenance?.source) return String(dataProvenance.source)
  return '等待后端数据'
}

function reportDataSourceSub(dataProvenance: DatasetReportDataProvenance | null | undefined): string {
  if (dataProvenance?.mocked === false) return '后端数据库 / API 实时聚合'
  return '未返回来源证明'
}

function reportPipelineFilterLabel(pipelineHash: string): string {
  if (pipelineHash) return shortPipelineHash(pipelineHash)
  return '当前活动版本'
}

function findingSeverityLabel(severity: string | null | undefined): string {
  if (severity === 'error') return '错误'
  if (severity === 'warning') return '警告'
  return '信息'
}

function issueLevelClass(level: string): string {
  if (level === '错误') return 'text-rose-600'
  if (level === '警告') return 'text-amber-600'
  return 'text-emerald-600'
}

function reportPreviewEmptyTitle(datasetId: string, isLoadingReport: boolean): string {
  if (!datasetId) return '请选择数据集'
  if (isLoadingReport) return '报告加载中...'
  return '暂无预览'
}

function reportPreviewEmptyDescription(datasetId: string, isLoadingReport: boolean): string {
  if (!datasetId) return '选择一个数据集后即可生成报告预览并导出。'
  if (isLoadingReport) return '正在拉取后端报告数据...'
  return '点击“重新生成报告”拉取最新后端报告。'
}

function filterReportFindings(
  findings: ReportFinding[],
  showOnlyIssues: boolean
): ReportFinding[] {
  if (!showOnlyIssues) return findings
  return findings.filter(
    (item) =>
      item.severity === 'warning' ||
      item.severity === 'error' ||
      safeNumber(item.count) > 0
  )
}

function countFindingsByPattern(rows: ReportFinding[], pattern: RegExp): number {
  return rows
    .filter((item) => pattern.test(`${item.key} ${item.label}`))
    .reduce((acc, item) => acc + safeNumber(item.count), 0)
}

function buildTopDocumentRows(
  folderBarData: ReportMetricDatum[],
  byFileType: Record<string, number> | undefined
): ReportMetricDatum[] {
  const rows =
    folderBarData.length > 0
      ? folderBarData
      : Object.entries(byFileType || {}).map(([name, value]) => ({
          name,
          value: safeNumber(value),
        }))
  return rows
    .slice()
    .sort((a, b) => safeNumber(b.value) - safeNumber(a.value))
    .slice(0, 3)
}

function buildIssueRows(
  activeFindingRows: ReportFinding[],
  connectorRuns: ReportConnectorRun[]
): IssueRow[] {
  return [
    ...activeFindingRows.map((item) => ({
      id: `finding-${item.key}`,
      time: '质量扫描',
      level: findingSeverityLabel(item.severity),
      type: item.label || item.key,
      description: item.description || `${item.label || item.key}：${item.count}`,
      target: `${item.count}`,
    })),
    ...connectorRuns
      .filter((item) => /fail|error|failed/i.test(String(item.status || '')))
      .map((item) => ({
        id: `connector-${item.id}`,
        time: formatDate(item.created_at),
        level: '错误',
        type: '连接器运行',
        description: item.error_message || item.status,
        target: item.connector_id || '-',
      })),
  ].slice(0, 5)
}

function chunkStatsCoverage(report: DatasetReport | null, totalDocs: number): number {
  const histogramCoverage = sumRecordValues(
    Object.fromEntries(
      (report?.profile?.chunk_count_histogram || []).map((bin, index) => [
        `${bin.label || index}`,
        safeNumber(bin.count),
      ])
    )
  )
  if (histogramCoverage) return histogramCoverage
  if (
    totalDocs > 0 &&
    safeNumber(report?.profile?.chunk_count_percentiles?.p50) > 0
  ) {
    return totalDocs
  }
  return 0
}

function governanceAuditStatValue(
  hasSamples: boolean,
  value: number | undefined
): string {
  if (!hasSamples) return '未统计'
  return String(value || 0)
}

function retrievalAuditStatusLabel(status: string | undefined): string {
  const value = String(status || '').trim().toLowerCase()
  if (value === 'passed' || value === 'completed' || value === 'success') {
    return '通过'
  }
  if (value === 'failed' || value === 'error') return '失败'
  if (value === 'running' || value === 'pending') return '生成中'
  return '未评估'
}

function retrievalAuditTone(
  status: string | undefined
): 'green' | 'amber' | 'rose' | 'slate' {
  const value = String(status || '').trim().toLowerCase()
  if (value === 'passed' || value === 'completed' || value === 'success') {
    return 'green'
  }
  if (value === 'failed' || value === 'error') return 'rose'
  if (value === 'running' || value === 'pending') return 'amber'
  return 'slate'
}

function trimFixedNumber(value: string): string {
  let end = value.length
  while (end > 0 && value[end - 1] === '0') {
    end -= 1
  }
  if (end > 0 && value[end - 1] === '.') {
    end -= 1
  }
  return value.slice(0, end) || '0'
}

function formatRetrievalAuditMetric(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (Math.abs(value) <= 1) return `${(value * 100).toFixed(1)}%`
    return trimFixedNumber(value.toFixed(3))
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string' && value.trim()) return value
  return '-'
}

function retrievalAuditMetricRows(
  retrievalAudit: RetrievalAudit | null | undefined
): RetrievalAuditMetricRow[] {
  const fields = [
    ['hit_at_1', 'hit@1'],
    ['hit_at_3', 'hit@3'],
    ['expected_metadata_hit_rate', 'metadata hit'],
    ['expected_metadata_recall', 'metadata recall'],
    ['retrieval_effective_context_rate', 'effective context'],
    ['retrieval_noise_rate', 'noise'],
    ['kg_noise_rate', 'KG noise'],
  ]
  const rows: RetrievalAuditMetricRow[] = []
  for (const gate of retrievalAudit?.gates || []) {
    const metrics = gate.metrics || {}
    const gateName = String(gate.name || 'gate').trim() || 'gate'
    for (const [key, label] of fields) {
      if (!Object.prototype.hasOwnProperty.call(metrics, key)) continue
      rows.push({
        key: `${gateName}:${key}`,
        label: `${label} · ${gateName}`,
        value: formatRetrievalAuditMetric(metrics[key]),
      })
    }
  }
  return rows
}

function retrievalAuditFailureText(
  retrievalAudit: RetrievalAudit | null | undefined
): string {
  const categories = retrievalAudit?.failure_categories || {}
  const entries = Object.entries(categories).filter(([, value]) => Number(value) > 0)
  if (!entries.length) {
    return retrievalAudit?.status === 'failed' || retrievalAudit?.status === 'error' ? '未归因' : '暂无'
  }
  const labels: Record<string, string> = {
    scope: '范围',
    chunking: '切块',
    ranking: '排序',
    absence: '缺内容',
    kg_noise: 'KG 噪声',
    adapter: '适配器',
  }
  return entries.map(([key, value]) => `${labels[key] || key} ${value}`).join(' / ')
}

function retrievalAuditHashText(
  retrievalAudit: RetrievalAudit | null | undefined
): string {
  const hashes = retrievalAudit?.plugin_package_hashes || []
  if (!hashes.length) return '未绑定'
  return hashes.map((hash) => shortPipelineHash(hash)).slice(0, 2).join(' / ')
}

function retrievalAuditKgRecommendationText(
  retrievalAudit: RetrievalAudit | null | undefined
): string {
  const recommendation = retrievalAudit?.kg_recommendation || ''
  const labels: Record<string, string> = {
    full_kg_assist: '可启用完整 KG',
    query_expansion_only: '仅启用查询扩展',
    boost_only: '仅启用 KG boost',
    none: '保持关闭',
  }
  return labels[recommendation] || '未评估'
}

function DataPill({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub?: string
  tone?: DataPillTone
}>) {
  const toneClass = {
    blue: 'bg-blue-50 text-blue-600 ring-blue-100',
    green: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
    amber: 'bg-amber-50 text-amber-600 ring-amber-100',
    rose: 'bg-rose-50 text-rose-600 ring-rose-100',
    violet: 'bg-violet-50 text-violet-600 ring-violet-100',
    slate: 'bg-slate-50 text-slate-600 ring-slate-100',
  }[tone]

  return (
    <div className="flex min-w-[170px] items-center gap-3 border-l border-slate-200/80 px-4 py-2 first:border-l-0">
      <div
        className={cn(
          'flex size-8 items-center justify-center rounded-xl ring-1',
          toneClass
        )}
      >
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <div className={REPORT_LABEL_CLASS}>{label}</div>
        <div className={REPORT_VALUE_CLASS}>{value}</div>
        {sub ? (
          <div className={cn('mt-0.5 truncate', REPORT_SUBTEXT_CLASS)}>
            {sub}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function AuditMetricCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'bg-blue-50 text-blue-600 ring-blue-100',
    green: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
    amber: 'bg-amber-50 text-amber-600 ring-amber-100',
    rose: 'bg-rose-50 text-rose-600 ring-rose-100',
    violet: 'bg-violet-50 text-violet-600 ring-violet-100',
    slate: 'bg-slate-50 text-slate-600 ring-slate-100',
  }[tone]

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="flex items-start justify-between gap-3">
        <div
          className={cn(
            'flex size-10 items-center justify-center rounded-2xl ring-1',
            toneClass
          )}
        >
          <Icon className="size-5" />
        </div>
      </div>
      <div className={cn('mt-3', REPORT_LABEL_CLASS)}>{label}</div>
      <div className={cn('mt-1', REPORT_METRIC_VALUE_CLASS)}>
        {value}
      </div>
      <div className={cn('mt-3', REPORT_SUBTEXT_CLASS)}>{sub}</div>
    </div>
  )
}

function MiniRiskCard({
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'text-blue-600',
    green: 'text-emerald-600',
    amber: 'text-amber-600',
    rose: 'text-rose-600',
    violet: 'text-violet-600',
    slate: 'text-slate-600',
  }[tone]
  return (
    <div className="rounded-xl border border-slate-200/80 bg-card/80 p-3">
      <div className={REPORT_LABEL_CLASS}>{label}</div>
      <div
        className={cn('mt-2', REPORT_RISK_VALUE_CLASS, toneClass)}
      >
        {value}
      </div>
      <div className={cn('mt-2', REPORT_SUBTEXT_CLASS)}>{sub}</div>
    </div>
  )
}

function CompactAuditFact({
  label,
  value,
  sub,
  tone = 'slate',
}: Readonly<{
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'text-blue-700',
    green: 'text-emerald-700',
    amber: 'text-amber-700',
    rose: 'text-rose-700',
    violet: 'text-violet-700',
    slate: 'text-slate-700',
  }[tone]
  return (
    <div className="min-w-0 rounded-lg border border-slate-200/70 bg-white/70 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="truncate text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-slate-500">
          {label}
        </div>
        <div
          className={cn(
            'max-w-[58%] truncate text-right text-[0.8125rem] font-semibold tracking-[-0.01em]',
            toneClass
          )}
          title={value}
        >
          {value}
        </div>
      </div>
      <div className="mt-1 truncate text-[0.6875rem] leading-4 text-slate-500" title={sub}>
        {sub}
      </div>
    </div>
  )
}

function ProgressRow({
  label,
  value,
  max,
}: Readonly<{ label: string; value: number; max: number }>) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  return (
    <div
      className={cn(
        'grid grid-cols-[120px_1fr_48px] items-center gap-3',
        REPORT_TABLE_ROW_CLASS
      )}
    >
      <div className="truncate text-slate-600" title={label}>
        {label}
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-blue-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right tabular-nums text-slate-600">
        {formatPct(value, max)}
      </div>
    </div>
  )
}

function useFlatReportFolders(folderTree: DatasetReport['folder_tree']) {
  const [flatFolders, setFlatFolders] = useState<FlatFolderRow[] | null>(null)
  const transformsWorkerRef = useRef<Worker | null>(null)
  const transformsApiRef = useRef<Remote<ReportTransformsWorkerApi> | null>(
    null
  )
  const transformsDisabledRef = useRef(false)
  const flatFoldersSeqRef = useRef(0)

  useEffect(() => {
    return () => {
      if (transformsWorkerRef.current) {
        transformsWorkerRef.current.terminate()
        transformsWorkerRef.current = null
        transformsApiRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    const seq = ++flatFoldersSeqRef.current

    if (!folderTree) {
      setFlatFolders(null)
      return
    }

    // Null => computed pending for this folder tree.
    setFlatFolders(null)

    const computeSync = () => {
      try {
        const rows = flattenFolderTree(folderTree)
        if (flatFoldersSeqRef.current === seq) setFlatFolders(rows)
      } catch (e) {
        reportClientWarning(
          'Failed to flatten folder tree; falling back to empty list',
          e
        )
        if (flatFoldersSeqRef.current === seq) setFlatFolders([])
      }
    }

    if (transformsDisabledRef.current || typeof Worker === 'undefined') {
      computeSync()
      return
    }

    let cancelled = false
    detachPromise(
      (async () => {
        try {
          if (!transformsWorkerRef.current || !transformsApiRef.current) {
            transformsWorkerRef.current = new Worker(
              new URL(
                '../../workers/report-transforms.worker.ts',
                import.meta.url
              ),
              { type: 'module' }
            )
            transformsApiRef.current = wrap<ReportTransformsWorkerApi>(
              transformsWorkerRef.current
            )
          }

          const rows =
            await transformsApiRef.current.flattenFolderTree(folderTree)
          if (cancelled) return
          if (flatFoldersSeqRef.current !== seq) return
          setFlatFolders(rows)
        } catch (e) {
          // If the environment can't load a worker bundle (or Comlink fails), keep the page functional.
          reportClientWarning(
            'Report transforms worker failed; falling back to main thread',
            e
          )
          transformsDisabledRef.current = true
          computeSync()
        }
      })()
    )

    return () => {
      cancelled = true
    }
  }, [folderTree])

  return flatFolders
}

function ReportMetricGrid({
  totalDocs,
  totalBytes,
  successDocs,
  successRate,
  failed,
  failedRate,
  pipelineVersionsCount,
  pipelineFilterLabel,
  latestAuditTime,
}: Readonly<{
  totalDocs: number
  totalBytes: number
  successDocs: number
  successRate: string
  failed: number
  failedRate: string
  pipelineVersionsCount: number
  pipelineFilterLabel: string
  latestAuditTime: string
}>) {
  return (
    <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <AuditMetricCard
        icon={FileText}
        label="文档总数"
        value={String(totalDocs)}
        sub="来自后端报告 profile.total_documents"
        tone="blue"
      />
      <AuditMetricCard
        icon={BarChart3}
        label="总大小"
        value={formatFileSize(Number(totalBytes || 0))}
        sub="来自后端报告 profile.total_size_bytes"
        tone="violet"
      />
      <AuditMetricCard
        icon={CheckCircle2}
        label="成功文档数"
        value={String(successDocs)}
        sub={`成功率 ${successRate}`}
        tone="green"
      />
      <AuditMetricCard
        icon={AlertTriangle}
        label="失败文档数"
        value={String(failed)}
        sub={`失败率 ${failedRate}`}
        tone="amber"
      />
      <AuditMetricCard
        icon={Layers}
        label="版本数"
        value={String(pipelineVersionsCount)}
        sub={`过滤：${pipelineFilterLabel}`}
        tone="blue"
      />
      <AuditMetricCard
        icon={Clock3}
        label="报告生成"
        value={latestAuditTime}
        sub="本次报告生成时间"
        tone="slate"
      />
    </div>
  )
}

function RiskMetricPanel({
  missingFindingCount,
  duplicateFindingCount,
  lowQualityFindingCount,
  totalDocs,
  failed,
  failedRate,
}: Readonly<{
  missingFindingCount: number
  duplicateFindingCount: number
  lowQualityFindingCount: number
  totalDocs: number
  failed: number
  failedRate: string
}>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className={cn('mb-4', REPORT_PANEL_TITLE_CLASS)}>
        边缘指标 / 风险指标
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <MiniRiskCard
          label="缺失字段率"
          value={formatPct(missingFindingCount, totalDocs)}
          sub={`${missingFindingCount} 条后端 finding`}
          tone={missingFindingCount ? 'amber' : 'blue'}
        />
        <MiniRiskCard
          label="重复文档率"
          value={formatPct(duplicateFindingCount, totalDocs)}
          sub={`${duplicateFindingCount} 条后端 finding`}
          tone={duplicateFindingCount ? 'violet' : 'blue'}
        />
        <MiniRiskCard
          label="低置信度率"
          value={formatPct(lowQualityFindingCount, totalDocs)}
          sub={`${lowQualityFindingCount} 条质量 finding`}
          tone={lowQualityFindingCount ? 'amber' : 'green'}
        />
        <MiniRiskCard
          label="解析失败率"
          value={failedRate}
          sub={`${failed} 个失败文档`}
          tone={failed ? 'rose' : 'green'}
        />
      </div>
    </div>
  )
}

function RetrievalAuditPanel({
  retrievalAudit,
}: Readonly<{ retrievalAudit: RetrievalAudit | null | undefined }>) {
  const status = retrievalAuditStatusLabel(retrievalAudit?.status)
  const tone = retrievalAuditTone(retrievalAudit?.status)
  const metricRows = retrievalAuditMetricRows(retrievalAudit)
  const pluginRefs = retrievalAudit?.plugin_refs || []
  const hasFailureCategories = Object.values(retrievalAudit?.failure_categories || {}).some(
    (value) => Number(value) > 0
  )
  const statusToneClass = {
    green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    rose: 'border-rose-200 bg-rose-50 text-rose-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-600',
  }[tone]

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FileSearch className="size-4 text-blue-600" />
            <div className={REPORT_PANEL_TITLE_CLASS}>召回审计</div>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-500">
              Retrieval Audit
            </span>
          </div>
          <div className={cn('mt-1', REPORT_SUBTEXT_CLASS)}>
            汇总 Golden / regression、元数据范围、KG 与压缩证据，判断当前知识库能否进入生产召回。
          </div>
        </div>
        <Badge
          variant="outline"
          className={cn('rounded-full px-2.5 py-1 text-[11px]', statusToneClass)}
        >
          {status}
        </Badge>
      </div>

      <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <CompactAuditFact
          label="失败归因"
          value={retrievalAuditFailureText(retrievalAudit)}
          sub="scope / chunk / rank / KG"
          tone={hasFailureCategories ? 'rose' : 'slate'}
        />
        <CompactAuditFact
          label="门禁证据"
          value={`${retrievalAudit?.gates?.length || 0} 项`}
          sub="latest regression gate"
          tone={retrievalAudit?.gates?.length ? 'violet' : 'slate'}
        />
        <CompactAuditFact
          label="KG 建议"
          value={retrievalAuditKgRecommendationText(retrievalAudit)}
          sub="KG-on/off compare"
          tone={retrievalAudit?.kg_recommendation === 'full_kg_assist' ? 'green' : 'slate'}
        />
        <CompactAuditFact
          label="插件包"
          value={retrievalAuditHashText(retrievalAudit)}
          sub={`${pluginRefs.length} 个 plugin ref`}
          tone={pluginRefs.length ? 'blue' : 'slate'}
        />
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-slate-100">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/80 px-3 py-2">
          <div className="text-[0.75rem] font-semibold tracking-[-0.01em] text-slate-700">
            门禁指标
          </div>
          <div className="text-[0.6875rem] text-slate-500">
            来自 latest regression gate
          </div>
        </div>
        <div
          className={cn(
            'grid grid-cols-[1fr_120px] bg-white px-3 py-2',
            REPORT_TABLE_HEADER_CLASS
          )}
        >
          <span>指标</span>
          <span className="text-right">数值</span>
        </div>
        {metricRows.length === 0 ? (
          <div className="border-t border-slate-100 px-3 py-5 text-center">
            <div className="text-[0.8125rem] font-medium text-slate-700">
              未生成评估指标
            </div>
            <div className={cn('mt-1', REPORT_SUBTEXT_CLASS)}>
              运行 Golden / regression 后，这里会显示 hit@k、metadata hit、有效上下文和噪声率。
            </div>
          </div>
        ) : (
          metricRows.map((row) => (
            <div
              key={row.key}
              className={cn(
                'grid grid-cols-[1fr_120px] border-t border-slate-100 px-3 py-2',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <span className="truncate" title={row.key}>
                {row.label}
              </span>
              <span className="text-right font-medium tabular-nums text-slate-800">
                {row.value}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function FieldCoveragePanel({
  fieldCoverageRows,
  fieldCoverageBadge,
}: Readonly<{
  fieldCoverageRows: CoverageRow[]
  fieldCoverageBadge: string
}>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className={REPORT_PANEL_TITLE_CLASS}>字段覆盖分布</div>
        <Badge variant="outline" className="rounded-full text-[11px]">
          {fieldCoverageBadge}
        </Badge>
      </div>
      <div className="space-y-3">
        {fieldCoverageRows.map((row) => (
          <ProgressRow
            key={row.label}
            label={row.label}
            value={row.value}
            max={row.max}
          />
        ))}
      </div>
    </div>
  )
}

function TopDocumentPanel({
  topDocumentRows,
  topDocumentMax,
  onClearFolderQuery,
}: Readonly<{
  topDocumentRows: ReportMetricDatum[]
  topDocumentMax: number
  onClearFolderQuery: () => void
}>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className={REPORT_PANEL_TITLE_CLASS}>文档分布 Top</div>
        <Button
          variant="link"
          className="h-auto p-0 text-xs"
          onClick={onClearFolderQuery}
        >
          查看全部
        </Button>
      </div>
      {topDocumentRows.length === 0 ? (
        <EmptyState
          title="暂无分布数据"
          description="后端报告未返回目录或文件类型分布。"
        />
      ) : (
        <div className="space-y-3">
          {topDocumentRows.map((row) => (
            <div
              key={row.name}
              className={cn(
                'grid grid-cols-[1fr_52px_100px] items-center gap-3',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <div className="truncate font-medium text-slate-700" title={row.name}>
                {row.name}
              </div>
              <div className="tabular-nums text-slate-700">{row.value}</div>
              <div className="h-2 rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-blue-500"
                  style={{
                    width: `${Math.max(3, (safeNumber(row.value) / topDocumentMax) * 100)}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ContentHealthPanel({
  governanceAuditUrlValue,
  governanceAuditUrlSub,
  governanceAuditImageValue,
  governanceAuditImageSub,
  governanceAuditHasSamples,
  sensitiveHits,
  piiHits,
  secretHits,
  lowQualityFindingCount,
}: Readonly<{
  governanceAuditUrlValue: string
  governanceAuditUrlSub: string
  governanceAuditImageValue: string
  governanceAuditImageSub: string
  governanceAuditHasSamples: boolean
  sensitiveHits: number
  piiHits: number
  secretHits: number
  lowQualityFindingCount: number
}>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className={cn('mb-4', REPORT_PANEL_TITLE_CLASS)}>
        污染观察 / 内容健康
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <MiniRiskCard
          label="可疑链接数"
          value={governanceAuditUrlValue}
          sub={governanceAuditUrlSub}
          tone={governanceAuditHasSamples ? 'blue' : 'slate'}
        />
        <MiniRiskCard
          label="外部附件数"
          value={governanceAuditImageValue}
          sub={governanceAuditImageSub}
          tone={governanceAuditHasSamples ? 'green' : 'slate'}
        />
        <MiniRiskCard
          label="敏感词命中"
          value={String(sensitiveHits)}
          sub={`PII ${piiHits} / Secret ${secretHits}`}
          tone={sensitiveHits ? 'amber' : 'green'}
        />
        <MiniRiskCard
          label="低质量片段数"
          value={String(lowQualityFindingCount)}
          sub="后端质量 finding"
          tone={lowQualityFindingCount ? 'rose' : 'violet'}
        />
      </div>
    </div>
  )
}

function CategoryChartPanel({
  categoryBarData,
}: Readonly<{ categoryBarData: CategoryMetricDatum[] }>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className={cn('mb-4', REPORT_PANEL_TITLE_CLASS)}>知识分类统计</div>
      {categoryBarData.length === 0 ? (
        <EmptyState
          title="暂无分类数据"
          description="后端分类树没有可展示的计数。"
        />
      ) : (
        <SafeResponsiveChart className="h-[260px]" minHeight={260}>
          <BarChart
            data={categoryBarData.slice(0, 8)}
            margin={{ left: 8, right: 12, top: 8, bottom: 8 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#e2e8f0"
              opacity={0.55}
            />
            <XAxis dataKey="name" />
            <YAxis allowDecimals={false} />
            <Tooltip
              cursor={CHART_TOOLTIP_CURSOR}
              contentStyle={CHART_TOOLTIP_STYLE}
              labelStyle={CHART_TOOLTIP_LABEL_STYLE}
            />
            <Bar dataKey="value" radius={[7, 7, 0, 0]} fill="#2563eb" />
          </BarChart>
        </SafeResponsiveChart>
      )}
    </div>
  )
}

function PipelineVersionsPanel({
  pipelineVersions,
  pipelineVersionsWithFill,
  versionTotal,
}: Readonly<{
  pipelineVersions: DatasetReportPipelineVersion[]
  pipelineVersionsWithFill: PipelineVersionDatum[]
  versionTotal: number
}>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className={cn('mb-4', REPORT_PANEL_TITLE_CLASS)}>
        源状态版本分布 Top
      </div>
      {pipelineVersions.length === 0 ? (
        <EmptyState
          title="暂无版本数据"
          description="后端报告未返回 pipeline_versions。"
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr] xl:grid-cols-1 2xl:grid-cols-[1fr_1fr]">
          <SafeResponsiveChart className="h-[210px]" minHeight={210}>
            <PieChart>
              <Pie
                data={pipelineVersionsWithFill}
                dataKey="documents"
                nameKey="pipeline_hash"
                innerRadius={54}
                outerRadius={84}
              />
              <Tooltip
                cursor={CHART_TOOLTIP_CURSOR}
                contentStyle={CHART_TOOLTIP_STYLE}
                labelStyle={CHART_TOOLTIP_LABEL_STYLE}
              />
            </PieChart>
          </SafeResponsiveChart>
          <div className="space-y-2 self-center">
            {pipelineVersions.slice(0, 5).map((version, idx) => (
              <div
                key={version.pipeline_hash}
                className={cn(
                  'flex items-center justify-between gap-2',
                  REPORT_TABLE_ROW_CLASS
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2 rounded-full"
                    style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}
                  />
                  <span
                    className="truncate font-mono"
                    title={version.pipeline_hash}
                  >
                    {shortPipelineHash(version.pipeline_hash)}
                  </span>
                </span>
                <span className="tabular-nums text-slate-500">
                  {version.documents} ({formatPct(version.documents, versionTotal)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function IssueRowsPanel({ issueRows }: Readonly<{ issueRows: IssueRow[] }>) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className={REPORT_PANEL_TITLE_CLASS}>风险命中记录</div>
        <Badge variant="outline" className="rounded-full text-[11px]">
          仅显示命中项
        </Badge>
      </div>
      {issueRows.length === 0 ? (
        <EmptyState
          title="暂无异常记录"
          description="当前后端报告没有命中的失败连接器或风险 finding。"
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-100">
          <div
            className={cn(
              'grid grid-cols-[120px_72px_120px_1fr_64px] bg-slate-50 px-3 py-2',
              REPORT_TABLE_HEADER_CLASS
            )}
          >
            <span>来源/时间</span>
            <span>级别</span>
            <span>类型</span>
            <span>描述</span>
            <span className="text-right">命中数</span>
          </div>
          {issueRows.map((row) => (
            <div
              key={row.id}
              className={cn(
                'grid grid-cols-[120px_72px_120px_1fr_64px] items-center border-t border-slate-100 px-3 py-3',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <span className="truncate">{row.time}</span>
              <span className={cn('font-medium', issueLevelClass(row.level))}>
                {row.level}
              </span>
              <span className="truncate">{row.type}</span>
              <span className="truncate" title={row.description}>
                {row.description}
              </span>
              <span className="text-right tabular-nums">{row.target}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ReportsDashboard({
  totalDocs,
  totalBytes,
  successDocs,
  successRate,
  failed,
  failedRate,
  pipelineVersions,
  pipelineVersionsWithFill,
  pipelineFilterLabel,
  latestAuditTime,
  retrievalAudit,
  missingFindingCount,
  duplicateFindingCount,
  lowQualityFindingCount,
  fieldCoverageRows,
  fieldCoverageBadge,
  topDocumentRows,
  topDocumentMax,
  onClearFolderQuery,
  governanceAuditUrlValue,
  governanceAuditUrlSub,
  governanceAuditImageValue,
  governanceAuditImageSub,
  governanceAuditHasSamples,
  sensitiveHits,
  piiHits,
  secretHits,
  categoryBarData,
  versionTotal,
  issueRows,
}: Readonly<{
  totalDocs: number
  totalBytes: number
  successDocs: number
  successRate: string
  failed: number
  failedRate: string
  pipelineVersions: DatasetReportPipelineVersion[]
  pipelineVersionsWithFill: PipelineVersionDatum[]
  pipelineFilterLabel: string
  latestAuditTime: string
  retrievalAudit: RetrievalAudit | null
  missingFindingCount: number
  duplicateFindingCount: number
  lowQualityFindingCount: number
  fieldCoverageRows: CoverageRow[]
  fieldCoverageBadge: string
  topDocumentRows: ReportMetricDatum[]
  topDocumentMax: number
  onClearFolderQuery: () => void
  governanceAuditUrlValue: string
  governanceAuditUrlSub: string
  governanceAuditImageValue: string
  governanceAuditImageSub: string
  governanceAuditHasSamples: boolean
  sensitiveHits: number
  piiHits: number
  secretHits: number
  categoryBarData: CategoryMetricDatum[]
  versionTotal: number
  issueRows: IssueRow[]
}>) {
  return (
    <section className="space-y-4">
      <ReportMetricGrid
        totalDocs={totalDocs}
        totalBytes={totalBytes}
        successDocs={successDocs}
        successRate={successRate}
        failed={failed}
        failedRate={failedRate}
        pipelineVersionsCount={pipelineVersions.length}
        pipelineFilterLabel={pipelineFilterLabel}
        latestAuditTime={latestAuditTime}
      />

      <RetrievalAuditPanel retrievalAudit={retrievalAudit} />

      <div className="grid gap-4 xl:grid-cols-[1.05fr_1.2fr_1.05fr_0.95fr]">
        <RiskMetricPanel
          missingFindingCount={missingFindingCount}
          duplicateFindingCount={duplicateFindingCount}
          lowQualityFindingCount={lowQualityFindingCount}
          totalDocs={totalDocs}
          failed={failed}
          failedRate={failedRate}
        />
        <FieldCoveragePanel
          fieldCoverageRows={fieldCoverageRows}
          fieldCoverageBadge={fieldCoverageBadge}
        />
        <TopDocumentPanel
          topDocumentRows={topDocumentRows}
          topDocumentMax={topDocumentMax}
          onClearFolderQuery={onClearFolderQuery}
        />
        <ContentHealthPanel
          governanceAuditUrlValue={governanceAuditUrlValue}
          governanceAuditUrlSub={governanceAuditUrlSub}
          governanceAuditImageValue={governanceAuditImageValue}
          governanceAuditImageSub={governanceAuditImageSub}
          governanceAuditHasSamples={governanceAuditHasSamples}
          sensitiveHits={sensitiveHits}
          piiHits={piiHits}
          secretHits={secretHits}
          lowQualityFindingCount={lowQualityFindingCount}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.9fr_1.4fr]">
        <CategoryChartPanel categoryBarData={categoryBarData} />
        <PipelineVersionsPanel
          pipelineVersions={pipelineVersions}
          pipelineVersionsWithFill={pipelineVersionsWithFill}
          versionTotal={versionTotal}
        />
        <IssueRowsPanel issueRows={issueRows} />
      </div>
    </section>
  )
}

function LoadingButtonIcon({
  loading,
  icon: Icon,
}: Readonly<{ loading: boolean; icon: LucideIcon }>) {
  if (loading) {
    return <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
  }
  return <Icon className="size-4" />
}

function ReportsHeaderPills({
  selectedDatasetName,
  datasetId,
  totalDocs,
  isLoadingReport,
  report,
  latestAuditTime,
  dataSourceLabel,
  dataSourceSub,
  dataProvenance,
}: Readonly<{
  selectedDatasetName: string
  datasetId: string
  totalDocs: number
  isLoadingReport: boolean
  report: DatasetReport | null
  latestAuditTime: string
  dataSourceLabel: string
  dataSourceSub: string
  dataProvenance: DatasetReportDataProvenance | null
}>) {
  return (
    <div className="flex flex-wrap overflow-hidden rounded-2xl border border-slate-200/80 bg-card/90 shadow-[0_10px_30px_rgba(15,23,42,0.05)]">
      <DataPill
        icon={Database}
        label="数据集"
        value={selectedDatasetName}
        sub={datasetId ? shortPipelineHash(datasetId) : '未选择'}
        tone="blue"
      />
      <DataPill
        icon={FileSearch}
        label="文档总数"
        value={`${totalDocs} 篇文档`}
        sub="后端 profile"
        tone="blue"
      />
      <DataPill
        icon={ShieldCheck}
        label="报告状态"
        value={reportStatusLabel(isLoadingReport, report)}
        sub={report ? '后端报告已返回' : '等待生成报告'}
        tone={report ? 'green' : 'slate'}
      />
      <DataPill
        icon={Clock3}
        label="报告生成"
        value={latestAuditTime}
        sub={report ? '后端生成时间' : '暂无'}
        tone="slate"
      />
      <DataPill
        icon={ShieldCheck}
        label="数据来源"
        value={dataSourceLabel}
        sub={dataSourceSub}
        tone={dataProvenance?.mocked === false ? 'green' : 'amber'}
      />
    </div>
  )
}

function ReportsControlPanel({
  datasetId,
  datasets,
  isLoadingDatasets,
  pipelineVersionSelectValue,
  pipelineVersionOptions,
  connectorRunsLimit,
  showOnlyIssues,
  redact,
  isExportingJson,
  isExportingHtml,
  isExportingRagAuditHtml,
  isExportingBundle,
  report,
  isLoadingReport,
  onDatasetChange,
  onPipelineHashChange,
  onConnectorRunsLimitChange,
  onShowOnlyIssuesChange,
  onRedactChange,
  onExportJson,
  onExportCompleteJson,
  onExportChartsJson,
  onExportRagAuditHtml,
  onExportBundleZip,
  onExportHtml,
  onRegenerateReport,
  onRefresh,
}: Readonly<{
  datasetId: string
  datasets: DatasetOption[]
  isLoadingDatasets: boolean
  pipelineVersionSelectValue: string
  pipelineVersionOptions: PipelineVersionOption[]
  connectorRunsLimit: number
  showOnlyIssues: boolean
  redact: boolean
  isExportingJson: boolean
  isExportingHtml: boolean
  isExportingRagAuditHtml: boolean
  isExportingBundle: boolean
  report: DatasetReport | null
  isLoadingReport: boolean
  onDatasetChange: (value: string) => void
  onPipelineHashChange: (value: string) => void
  onConnectorRunsLimitChange: (value: number) => void
  onShowOnlyIssuesChange: (value: boolean) => void
  onRedactChange: (value: boolean) => void
  onExportJson: () => void
  onExportCompleteJson: () => void
  onExportChartsJson: () => void
  onExportRagAuditHtml: () => void
  onExportBundleZip: () => void
  onExportHtml: () => void
  onRegenerateReport: () => void
  onRefresh: () => void
}>) {
  return (
    <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.95)]">
      <div className="grid gap-3 xl:grid-cols-[1.25fr_1.1fr_0.9fr_auto] xl:items-end">
        <div className="space-y-2">
          <Label htmlFor="dataset-select">数据集</Label>
          <Select value={datasetId} onValueChange={onDatasetChange}>
            <SelectTrigger
              id="dataset-select"
              className="h-8 w-full border-slate-200/80 bg-card text-[12px]"
            >
              <SelectValue
                placeholder={isLoadingDatasets ? '加载中...' : '请选择数据集'}
              />
            </SelectTrigger>
            <SelectContent>
              {datasets.map((ds) => (
                <SelectItem key={ds.id} value={ds.id}>
                  {ds.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="pipeline-hash">处理版本</Label>
          <Select
            value={pipelineVersionSelectValue}
            onValueChange={onPipelineHashChange}
          >
            <SelectTrigger
              id="pipeline-hash"
              className="h-8 w-full border-slate-200/80 bg-card text-[12px]"
            >
              <SelectValue placeholder="选择或使用当前活动版本" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_PIPELINE_VERSION_VALUE}>
                当前活动版本（默认）
              </SelectItem>
              {pipelineVersionOptions.map((v) => (
                <SelectItem key={v.pipeline_hash} value={v.pipeline_hash}>
                  {shortPipelineHash(v.pipeline_hash)} · {v.documents} 个文档
                </SelectItem>
              ))}
              {pipelineVersionOptions.length === 0 ? (
                <SelectItem value="__mimirq_no_pipeline_versions__" disabled>
                  暂无可选历史版本
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="connector-limit">返回记录数量限制</Label>
          <Select
            value={String(connectorRunsLimit)}
            onValueChange={(value) => onConnectorRunsLimitChange(Number(value || 20))}
          >
            <SelectTrigger
              id="connector-limit"
              className="h-8 w-full border-slate-200/80 bg-card text-[12px]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">不包含</SelectItem>
              <SelectItem value="10">限制 10 条</SelectItem>
              <SelectItem value="20">限制 20 条（默认）</SelectItem>
              <SelectItem value="50">限制 50 条</SelectItem>
              <SelectItem value="100">限制 100 条</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2 pb-1">
          <Switch
            id="only-issues-switch"
            checked={showOnlyIssues}
            onCheckedChange={onShowOnlyIssuesChange}
          />
          <Label
            htmlFor="only-issues-switch"
            className="whitespace-nowrap text-[12px]"
          >
            仅显示异常/失败
          </Label>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/80 pt-3">
        <div className="flex items-center gap-2">
          <Switch
            id="redact-switch"
            checked={redact}
            onCheckedChange={onRedactChange}
          />
          <Label htmlFor="redact-switch" className="text-[12px]">
            分享导出时隐藏敏感字段
          </Label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onExportJson}
            disabled={!datasetId || isExportingJson}
            aria-label="导出 JSON"
          >
            <LoadingButtonIcon loading={isExportingJson} icon={Download} />
            <span className="ml-2">导出 JSON</span>
          </Button>
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onExportCompleteJson}
            disabled={!datasetId || !report}
            aria-label="导出完整 JSON"
          >
            <Archive className="size-4" />
            <span className="ml-2">导出完整 JSON</span>
          </Button>
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onExportChartsJson}
            disabled={!datasetId || !report}
            aria-label="导出 RAG 统计"
          >
            <BarChart3 className="size-4" />
            <span className="ml-2">导出 RAG 统计</span>
          </Button>
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onExportRagAuditHtml}
            disabled={!datasetId || isExportingRagAuditHtml}
            aria-label="导出 RAG 审计报告"
          >
            <LoadingButtonIcon
              loading={isExportingRagAuditHtml}
              icon={Download}
            />
            <span className="ml-2">导出 RAG 审计</span>
          </Button>
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onExportBundleZip}
            disabled={!datasetId || isExportingBundle}
            aria-label="导出数据包 ZIP"
          >
            <LoadingButtonIcon loading={isExportingBundle} icon={Download} />
            <span className="ml-2">导出数据包 ZIP</span>
          </Button>
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onExportHtml}
            disabled={!datasetId || isExportingHtml}
            aria-label="导出 HTML"
          >
            <LoadingButtonIcon loading={isExportingHtml} icon={Download} />
            <span className="ml-2">导出 HTML</span>
          </Button>
          <Button
            className="h-8 rounded-lg bg-blue-600 text-info-foreground shadow-[0_8px_20px_rgba(37,99,235,0.22)] hover:bg-blue-700"
            onClick={onRegenerateReport}
            disabled={!datasetId || isLoadingReport}
            aria-label="重新生成报告"
          >
            <LoadingButtonIcon loading={isLoadingReport} icon={PlayCircle} />
            <span className="ml-2">重新生成报告</span>
          </Button>
          <Button
            variant="outline"
            className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
            onClick={onRefresh}
            disabled={isLoadingDatasets}
            aria-label="刷新"
          >
            <LoadingButtonIcon loading={isLoadingDatasets} icon={RefreshCw} />
            <span className="ml-2">刷新</span>
          </Button>
        </div>
      </div>
    </section>
  )
}

function ReportsResultSection({
  report,
  datasetId,
  isLoadingReport,
  totalDocs,
  totalBytes,
  successDocs,
  successRate,
  failed,
  failedRate,
  pipelineVersions,
  pipelineVersionsWithFill,
  pipelineFilterLabel,
  latestAuditTime,
  retrievalAudit,
  missingFindingCount,
  duplicateFindingCount,
  lowQualityFindingCount,
  fieldCoverageRows,
  fieldCoverageBadge,
  topDocumentRows,
  topDocumentMax,
  onClearFolderQuery,
  governanceAuditUrlValue,
  governanceAuditUrlSub,
  governanceAuditImageValue,
  governanceAuditImageSub,
  governanceAuditHasSamples,
  sensitiveHits,
  piiHits,
  secretHits,
  categoryBarData,
  versionTotal,
  issueRows,
}: Readonly<{
  report: DatasetReport | null
  datasetId: string
  isLoadingReport: boolean
  totalDocs: number
  totalBytes: number
  successDocs: number
  successRate: string
  failed: number
  failedRate: string
  pipelineVersions: DatasetReportPipelineVersion[]
  pipelineVersionsWithFill: PipelineVersionDatum[]
  pipelineFilterLabel: string
  latestAuditTime: string
  retrievalAudit: RetrievalAudit | null
  missingFindingCount: number
  duplicateFindingCount: number
  lowQualityFindingCount: number
  fieldCoverageRows: CoverageRow[]
  fieldCoverageBadge: string
  topDocumentRows: ReportMetricDatum[]
  topDocumentMax: number
  onClearFolderQuery: () => void
  governanceAuditUrlValue: string
  governanceAuditUrlSub: string
  governanceAuditImageValue: string
  governanceAuditImageSub: string
  governanceAuditHasSamples: boolean
  sensitiveHits: number
  piiHits: number
  secretHits: number
  categoryBarData: CategoryMetricDatum[]
  versionTotal: number
  issueRows: IssueRow[]
}>) {
  if (!report) {
    return (
      <EmptyState
        title={reportPreviewEmptyTitle(datasetId, isLoadingReport)}
        description={reportPreviewEmptyDescription(datasetId, isLoadingReport)}
      />
    )
  }

  return (
    <ReportsDashboard
      totalDocs={totalDocs}
      totalBytes={totalBytes}
      successDocs={successDocs}
      successRate={successRate}
      failed={failed}
      failedRate={failedRate}
      pipelineVersions={pipelineVersions}
      pipelineVersionsWithFill={pipelineVersionsWithFill}
      pipelineFilterLabel={pipelineFilterLabel}
      latestAuditTime={latestAuditTime}
      retrievalAudit={retrievalAudit}
      missingFindingCount={missingFindingCount}
      duplicateFindingCount={duplicateFindingCount}
      lowQualityFindingCount={lowQualityFindingCount}
      fieldCoverageRows={fieldCoverageRows}
      fieldCoverageBadge={fieldCoverageBadge}
      topDocumentRows={topDocumentRows}
      topDocumentMax={topDocumentMax}
      onClearFolderQuery={onClearFolderQuery}
      governanceAuditUrlValue={governanceAuditUrlValue}
      governanceAuditUrlSub={governanceAuditUrlSub}
      governanceAuditImageValue={governanceAuditImageValue}
      governanceAuditImageSub={governanceAuditImageSub}
      governanceAuditHasSamples={governanceAuditHasSamples}
      sensitiveHits={sensitiveHits}
      piiHits={piiHits}
      secretHits={secretHits}
      categoryBarData={categoryBarData}
      versionTotal={versionTotal}
      issueRows={issueRows}
    />
  )
}

export default function ReportsCenterPage() {
  const [datasetId, setDatasetId] = useState<string>('')
  const [pipelineHash, setPipelineHash] = useState<string>('')
  const [connectorRunsLimit, setConnectorRunsLimit] = useState<number>(20)
  const [redact, setRedact] = useState<boolean>(true)
  const [showOnlyIssues, setShowOnlyIssues] = useState<boolean>(false)

  const [isExportingJson, setIsExportingJson] = useState(false)
  const [isExportingHtml, setIsExportingHtml] = useState(false)
  const [isExportingRagAuditHtml, setIsExportingRagAuditHtml] = useState(false)
  const [isExportingBundle, setIsExportingBundle] = useState(false)

  const [folderQuery, setFolderQuery] = useState<string>('')
  const [categoryQuery] = useState<string>('')

  const reportParams = useMemo(
    () => ({
      pipeline_hash: pipelineHash.trim() || undefined,
      connector_runs_limit: connectorRunsLimit,
    }),
    [connectorRunsLimit, pipelineHash]
  )

  const datasetsQuery = useQuery<Awaited<ReturnType<typeof datasetApi.list>>>({
    queryKey: queryKeys.datasets.list({ skip: 0, limit: 200, purpose: 'reports' }),
    queryFn: () => datasetApi.list({ skip: 0, limit: 200 }),
  })
  const categoriesQuery = useQuery<
    Awaited<ReturnType<typeof datasetCategoryApi.listTree>>
  >({
    queryKey: queryKeys.reports.categories,
    queryFn: () => datasetCategoryApi.listTree(),
  })
  const reportQuery = useQuery<DatasetReport>({
    queryKey: queryKeys.reports.dataset(datasetId, reportParams),
    queryFn: () => reportApi.getDatasetReport(datasetId, reportParams),
    enabled: Boolean(datasetId),
  })

  const datasets = useMemo(
    () => datasetsQuery.data?.items || [],
    [datasetsQuery.data?.items]
  )
  const categoryTree = useMemo(
    () => categoriesQuery.data?.items || [],
    [categoriesQuery.data?.items]
  )
  const report = reportQuery.data ?? null
  const isLoadingDatasets = datasetsQuery.isFetching
  const isLoadingReport = reportQuery.isFetching
  const selectedDataset = useMemo(
    () => datasets.find((d) => d.id === datasetId) || null,
    [datasets, datasetId]
  )

  useEffect(() => {
    if (!datasets.length) return
    if (datasetId && datasets.some((dataset) => dataset.id === datasetId)) {
      return
    }
    setDatasetId(datasets[0].id)
    setPipelineHash('')
  }, [datasetId, datasets])

  const handleDatasetChange = useCallback((value: string) => {
    setDatasetId(value)
    setPipelineHash('')
  }, [])
  const handlePipelineHashChange = useCallback((value: string) => {
    setPipelineHash(selectedPipelineHashValue(value))
  }, [])
  const handleRefresh = useCallback(() => {
    refreshReportQueries(
      datasetId,
      datasetsQuery.refetch,
      categoriesQuery.refetch,
      reportQuery.refetch
    )
  }, [categoriesQuery.refetch, datasetId, datasetsQuery.refetch, reportQuery.refetch])
  const handleClearFolderQuery = useCallback(() => {
    setFolderQuery('')
  }, [])

  const handleExportJson = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        setLoading: setIsExportingJson,
        getBlob: reportApi.exportDatasetReportJson,
        filenameStem: 'report',
        extension: 'json',
        errorFallback: '导出 JSON 报告失败',
      })
    )
  }, [connectorRunsLimit, datasetId, pipelineHash, selectedDataset?.name])

  const handleExportHtml = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        redact,
        setLoading: setIsExportingHtml,
        getBlob: reportApi.exportDatasetReportHtml,
        filenameStem: 'report',
        extension: 'html',
        errorFallback: '导出 HTML 报告失败',
      })
    )
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const handleExportRagAuditHtml = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        redact,
        setLoading: setIsExportingRagAuditHtml,
        getBlob: reportApi.exportDatasetRagAuditHtml,
        filenameStem: 'rag_audit',
        extension: 'html',
        errorFallback: '导出 RAG Audit 报告失败',
      })
    )
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const handleExportBundleZip = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        redact,
        setLoading: setIsExportingBundle,
        getBlob: reportApi.exportDatasetReportBundleZip,
        filenameStem: 'report-bundle',
        extension: 'zip',
        errorFallback: '导出完整归档包失败',
      })
    )
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const totalDocs = report?.profile?.total_documents || 0
  const totalBytes = report?.profile?.total_size_bytes || 0
  const quarantined = report?.compliance?.quarantined_documents || 0
  const failed = report?.compliance?.failed_documents || 0
  const pipelineVersions = useMemo(
    () => report?.pipeline_versions ?? [],
    [report?.pipeline_versions]
  )
  const pipelineVersionsWithFill = useMemo(
    () =>
      pipelineVersions.map((version, idx) => ({
        ...version,
        fill: PIE_COLORS[idx % PIE_COLORS.length],
      })),
    [pipelineVersions]
  )
  const connectorRuns = report?.connectors || []
  const folderTree = report?.folder_tree || null
  const flatFolders = useFlatReportFolders(folderTree)
  const governance = report?.governance_metrics || null
  const governanceAudit = report?.governance_audit || null
  const retrievalAudit = report?.retrieval_audit || null
  const pipelineVersionOptions = useMemo(() => {
    const seen = new Set<string>()
    return pipelineVersions
      .map((v) => ({
        pipeline_hash: String(v.pipeline_hash || '').trim(),
        documents: Number(v.documents || 0),
      }))
      .filter((v) => {
        if (
          !v.pipeline_hash ||
          v.pipeline_hash === 'unknown' ||
          seen.has(v.pipeline_hash)
        )
          return false
        seen.add(v.pipeline_hash)
        return true
      })
  }, [pipelineVersions])
  const pipelineVersionSelectValue =
    pipelineHash.trim() || DEFAULT_PIPELINE_VERSION_VALUE

  const folderBarData = useMemo(() => {
    const rows = flatFolders ?? []
    const q = folderQuery.trim().toLowerCase()
    const filtered = q
      ? rows.filter((f) => f.path.toLowerCase().includes(q))
      : rows
    return filtered
      .slice()
      .sort((a, b) => b.documents - a.documents)
      .slice(0, 12)
      .map((f) => ({ name: f.path || '/', value: Number(f.documents || 0) }))
  }, [flatFolders, folderQuery])

  const flatCategories = useMemo(() => {
    const out: Array<{
      id: string
      name: string
      depth: number
      datasets: number
    }> = []
    const walk = (node: DatasetCategoryNode) => {
      out.push({
        id: String(node.id),
        name: String(node.name || ''),
        depth: Number(node.depth || 0),
        datasets: Number(node.datasets || 0),
      })
      for (const child of node.children || []) walk(child)
    }
    for (const n of categoryTree || []) walk(n)
    return out
  }, [categoryTree])

  const categoryBarData = useMemo(() => {
    const q = categoryQuery.trim().toLowerCase()
    const filtered = q
      ? flatCategories.filter((c) => c.name.toLowerCase().includes(q))
      : flatCategories
    return filtered
      .slice()
      .sort((a, b) => b.datasets - a.datasets)
      .slice(0, 12)
      .map((c) => ({
        name: c.name || c.id,
        value: Number(c.datasets || 0),
        depth: c.depth,
      }))
  }, [categoryQuery, flatCategories])

  const dropReasonsData = useMemo(() => {
    const m = governance?.drop_reasons_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governance?.drop_reasons_total])

  const rulePacksData = useMemo(() => {
    const m = governance?.rule_packs_docs || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governance?.rule_packs_docs])

  const govAuditCharData = useMemo(() => {
    if (!governanceAudit) return []
    return [
      {
        name: 'original_chars_total',
        value: Number(governanceAudit.original_chars_total || 0),
      },
      {
        name: 'cleaned_chars_total',
        value: Number(governanceAudit.cleaned_chars_total || 0),
      },
    ]
  }, [governanceAudit])

  const govAuditReductionHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.char_reduction_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditDensityHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.density_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditHeadingRatioHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.heading_ratio_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditEffectsData = useMemo(() => {
    if (!governanceAudit) return []
    const items = [
      {
        name: '段落去重（dropped）',
        value: Number(governanceAudit.paragraphs_dropped_total || 0),
      },
      {
        name: '裁剪 References（lines）',
        value: Number(governanceAudit.references_removed_lines_total || 0),
      },
      {
        name: 'URL 规范化（changed）',
        value: Number(governanceAudit.urls_changed_total || 0),
      },
      {
        name: '去样板（lines）',
        value: Number(governanceAudit.boilerplate_removed_lines_total || 0),
      },
      {
        name: '移除图片（count）',
        value: Number(governanceAudit.images_removed_total || 0),
      },
      {
        name: '表格规范化（tables）',
        value: Number(governanceAudit.tables_normalized_total || 0),
      },
      {
        name: '代码行号移除（lines）',
        value: Number(governanceAudit.code_lines_stripped_total || 0),
      },
    ]
    return items
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governanceAudit])

  const statusCounts = report?.profile?.by_status || {}
  const hasStatusCounts = Object.keys(statusCounts).length > 0
  const completedDocs = safeNumber(
    statusCounts.completed ?? statusCounts.ready ?? statusCounts.done
  )
  const successDocs = hasStatusCounts
    ? completedDocs
    : Math.max(0, totalDocs - failed - quarantined)
  const successRate = formatPct(successDocs, totalDocs)
  const failedRate = formatPct(failed, totalDocs)
  const selectedDatasetName =
    selectedDataset?.name || report?.dataset_name || '未选择数据集'
  const latestAuditTime = report?.generated_at
    ? formatDate(report.generated_at)
    : '-'
  const dataProvenance = report?.data_provenance || null
  const dataSourceLabel = reportDataSourceLabel(dataProvenance)
  const dataSourceSub = reportDataSourceSub(dataProvenance)
  const piiHits = sumRecordValues(report?.compliance?.pii_hits_total)
  const secretHits = sumRecordValues(report?.compliance?.secrets_hits_total)
  const sensitiveHits = piiHits + secretHits
  const findingRows = filterReportFindings(
    report?.profile?.findings || [],
    showOnlyIssues
  )
  const duplicateFindingCount = countFindingsByPattern(
    findingRows,
    /duplicate|重复/i
  )
  const missingFindingCount = countFindingsByPattern(
    findingRows,
    /missing|缺失/i
  )
  const lowQualityFindingCount = countFindingsByPattern(
    findingRows,
    /quality|低质量|low/i
  )
  const topDocumentRows = buildTopDocumentRows(
    folderBarData,
    report?.profile?.by_file_type
  )
  const topDocumentMax = Math.max(
    1,
    ...topDocumentRows.map((item) => safeNumber(item.value))
  )
  const versionTotal = pipelineVersions.reduce(
    (acc, item) => acc + safeNumber(item.documents),
    0
  )
  const pipelineFilterLabel = reportPipelineFilterLabel(pipelineHash)
  const activeFindingRows = findingRows.filter(
    (item) => safeNumber(item.count) > 0
  )
  const issueRows = buildIssueRows(activeFindingRows, connectorRuns)
  const governanceCoverageMax =
    safeNumber(governanceAudit?.used_documents) ||
    safeNumber(governance?.used_documents)
  const governanceAuditHasSamples =
    safeNumber(governanceAudit?.used_documents) > 0
  const governanceAuditUnavailableSub = '当前报告无治理审计样本'
  const governanceAuditUrlValue = governanceAuditHasSamples
    ? String(governanceAudit?.urls_changed_total || 0)
    : governanceAuditStatValue(governanceAuditHasSamples, governanceAudit?.urls_changed_total)
  const governanceAuditImageValue = governanceAuditHasSamples
    ? String(governanceAudit?.images_removed_total || 0)
    : governanceAuditStatValue(governanceAuditHasSamples, governanceAudit?.images_removed_total)
  const governanceAuditUrlSub = governanceAuditHasSamples
    ? 'URL 规范化变更'
    : governanceAuditUnavailableSub
  const governanceAuditImageSub = governanceAuditHasSamples
    ? '治理审计图片移除'
    : governanceAuditUnavailableSub
  const hasGovernanceCoverage = governanceCoverageMax > 0
  const chunkStatsCovered = chunkStatsCoverage(report, totalDocs)
  const baseCoverageRows = [
    {
      label: '状态字段覆盖',
      value: capCoverageValue(sumRecordValues(statusCounts), totalDocs),
      max: totalDocs,
    },
    {
      label: '文件类型覆盖',
      value: capCoverageValue(
        sumRecordValues(report?.profile?.by_file_type),
        totalDocs
      ),
      max: totalDocs,
    },
    {
      label: '目录字段覆盖',
      value: capCoverageValue(
        sumRecordValues(report?.profile?.by_directory),
        totalDocs
      ),
      max: totalDocs,
    },
    {
      label: '解析来源覆盖',
      value: capCoverageValue(
        report?.profile?.parsing_provenance?.docs_with_provenance,
        totalDocs
      ),
      max: totalDocs,
    },
    {
      label: '分块统计覆盖',
      value: capCoverageValue(chunkStatsCovered, totalDocs),
      max: totalDocs,
    },
  ]
  const governanceCoverageRows = [
    {
      label: '字符统计覆盖',
      value: capCoverageValue(
        governanceAudit?.docs_with_char_stats,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
    {
      label: '解析内容持久化',
      value: capCoverageValue(
        governanceAudit?.docs_with_parsed_content_persisted,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
    {
      label: '治理记录覆盖',
      value: capCoverageValue(
        governance?.docs_with_governance,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
    {
      label: '变更文档占比',
      value: capCoverageValue(governanceAudit?.docs_changed, governanceCoverageMax),
      max: governanceCoverageMax,
    },
    {
      label: '过滤/隔离占比',
      value: capCoverageValue(
        governanceAudit?.docs_dropped || quarantined,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
  ]
  const fieldCoverageRows = hasGovernanceCoverage
    ? governanceCoverageRows
    : baseCoverageRows
  const fieldCoverageBadge = hasGovernanceCoverage ? '后端治理审计' : '后端基础画像'

  const handleExportChartsJson = useCallback(() => {
    exportChartsJsonPayload({
      datasetId,
      report,
      selectedDatasetName: selectedDataset?.name,
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
    })
  }, [
    categoryBarData,
    categoryQuery,
    datasetId,
    dropReasonsData,
    folderBarData,
    folderQuery,
    govAuditCharData,
    govAuditDensityHistData,
    govAuditReductionHistData,
    govAuditHeadingRatioHistData,
    govAuditEffectsData,
    pipelineHash,
    report,
    rulePacksData,
    selectedDataset?.name,
  ])

  const handleExportCompleteJson = useCallback(() => {
    exportCompleteReportJsonPayload({
      datasetId,
      report,
      selectedDatasetName: selectedDataset?.name,
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
    })
  }, [
    categoryBarData,
    datasetId,
    failedRate,
    fieldCoverageRows,
    findingRows,
    pipelineHash,
    report,
    selectedDataset?.name,
    sensitiveHits,
    successDocs,
    successRate,
    topDocumentRows,
    versionTotal,
  ])

  return (
    <AppFrame>
      <AnalysisPageShell
        title="数据报告与审计概览"
        description="一键导出数据报告与审计结果，支持多种格式与指标视图，便于数据治理与合规审查。"
        icon={FileText}
        iconColor="text-primary"
        badge="报告"
        size="full"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="!pb-0"
        bodyContainerClassName="max-w-none"
      >
        <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-[linear-gradient(180deg,#f8fafc_0%,#ffffff_22%)] shadow-[0_1px_0_rgba(15,23,42,0.04)]">
          <div className="border-b border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] px-5 py-4">
            <PageHeader
              title="数据报告与审计概览"
              description="一键导出数据报告与审计结果，所有指标均来自后端报告接口与数据集接口。"
              iconImage="report-export"
              icon={FileText}
              iconColor="text-info"
              badge="报告"
              compact
              className="p-0"
            >
              <ReportsHeaderPills
                selectedDatasetName={selectedDatasetName}
                datasetId={datasetId}
                totalDocs={totalDocs}
                isLoadingReport={isLoadingReport}
                report={report}
                latestAuditTime={latestAuditTime}
                dataSourceLabel={dataSourceLabel}
                dataSourceSub={dataSourceSub}
                dataProvenance={dataProvenance}
              />
            </PageHeader>
          </div>
          <div className="space-y-3 p-3">
            <ReportsControlPanel
              datasetId={datasetId}
              datasets={datasets}
              isLoadingDatasets={isLoadingDatasets}
              pipelineVersionSelectValue={pipelineVersionSelectValue}
              pipelineVersionOptions={pipelineVersionOptions}
              connectorRunsLimit={connectorRunsLimit}
              showOnlyIssues={showOnlyIssues}
              redact={redact}
              isExportingJson={isExportingJson}
              isExportingHtml={isExportingHtml}
              isExportingRagAuditHtml={isExportingRagAuditHtml}
              isExportingBundle={isExportingBundle}
              report={report}
              isLoadingReport={isLoadingReport}
              onDatasetChange={handleDatasetChange}
              onPipelineHashChange={handlePipelineHashChange}
              onConnectorRunsLimitChange={setConnectorRunsLimit}
              onShowOnlyIssuesChange={setShowOnlyIssues}
              onRedactChange={setRedact}
              onExportJson={handleExportJson}
              onExportCompleteJson={handleExportCompleteJson}
              onExportChartsJson={handleExportChartsJson}
              onExportRagAuditHtml={handleExportRagAuditHtml}
              onExportBundleZip={handleExportBundleZip}
              onExportHtml={handleExportHtml}
              onRegenerateReport={reportQuery.refetch}
              onRefresh={handleRefresh}
            />

            <ReportsResultSection
              report={report}
              datasetId={datasetId}
              isLoadingReport={isLoadingReport}
              totalDocs={totalDocs}
              totalBytes={totalBytes}
              successDocs={successDocs}
              successRate={successRate}
              failed={failed}
              failedRate={failedRate}
              pipelineVersions={pipelineVersions}
              pipelineVersionsWithFill={pipelineVersionsWithFill}
              pipelineFilterLabel={pipelineFilterLabel}
              latestAuditTime={latestAuditTime}
              retrievalAudit={retrievalAudit}
              missingFindingCount={missingFindingCount}
              duplicateFindingCount={duplicateFindingCount}
              lowQualityFindingCount={lowQualityFindingCount}
              fieldCoverageRows={fieldCoverageRows}
              fieldCoverageBadge={fieldCoverageBadge}
              topDocumentRows={topDocumentRows}
              topDocumentMax={topDocumentMax}
              onClearFolderQuery={handleClearFolderQuery}
              governanceAuditUrlValue={governanceAuditUrlValue}
              governanceAuditUrlSub={governanceAuditUrlSub}
              governanceAuditImageValue={governanceAuditImageValue}
              governanceAuditImageSub={governanceAuditImageSub}
              governanceAuditHasSamples={governanceAuditHasSamples}
              sensitiveHits={sensitiveHits}
              piiHits={piiHits}
              secretHits={secretHits}
              categoryBarData={categoryBarData}
              versionTotal={versionTotal}
              issueRows={issueRows}
            />
          </div>
        </div>
      </AnalysisPageShell>
    </AppFrame>
  )
}
