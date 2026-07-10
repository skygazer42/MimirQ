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
  ChevronDown,
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
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import {
  KNOWLEDGE_OPS_BACKGROUND_CLASS,
  KnowledgeOpsHero,
} from '@/components/ui/knowledge-ops-hero'
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
  'text-xs font-medium tracking-[0.02em] text-slate-500/90'
const REPORT_VALUE_CLASS =
  'truncate text-[0.875rem] font-semibold leading-5 tracking-[-0.01em] text-slate-900'
const REPORT_SUBTEXT_CLASS = 'text-xs leading-4 text-slate-500'
const REPORT_METRIC_VALUE_CLASS =
  'text-[1.375rem] font-semibold leading-none tracking-[-0.04em] tabular-nums text-slate-950'
const REPORT_PANEL_TITLE_CLASS =
  'text-[0.9375rem] font-semibold leading-5 tracking-[-0.015em] text-slate-950'
const REPORT_TABLE_HEADER_CLASS =
  'text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-slate-500'
const REPORT_TABLE_ROW_CLASS = 'text-[0.8125rem] leading-5 text-slate-700'
const REPORT_PANEL_CLASS =
  'rounded-[1.15rem] border border-slate-200/75 bg-white/92 p-3.5 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.28)]'
const REPORT_SECONDARY_ACTION_CLASS =
  'h-9 gap-1.5 rounded-xl border-slate-200/80 bg-white/90 px-3 text-xs font-medium text-slate-600 shadow-none hover:border-sky-200 hover:bg-sky-50/70 hover:text-sky-800'
const REPORT_PRIMARY_ACTION_CLASS =
  'h-9 gap-1.5 rounded-xl bg-sky-600 px-3.5 text-xs font-semibold text-white shadow-[0_12px_24px_-14px_rgba(2,132,199,0.8)] hover:bg-sky-700'
const REPORT_FILTER_LABEL_CLASS =
  'text-xs font-medium tracking-[0.02em] text-slate-600'
const REPORT_SELECT_TRIGGER_CLASS =
  'h-9 w-full rounded-xl border-slate-200/80 bg-white/90 text-xs font-medium text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.04)] hover:border-sky-200'
const REPORT_SELECT_ITEM_CLASS =
  'py-2 text-xs font-medium text-slate-700'
const REPORT_METRIC_LEDGER_CLASS =
  'grid overflow-hidden rounded-[1.2rem] border border-slate-200/75 bg-slate-200/75 shadow-[0_18px_42px_-34px_rgba(15,23,42,0.35)] md:grid-cols-3 2xl:grid-cols-6'
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
type PipelineVersionDatum = DatasetReportPipelineVersion & {
  display_label: string
  fill: string
}
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
  if (report) return '已就绪'
  return '待生成'
}

function reportStatusTone(
  isLoadingReport: boolean,
  report: DatasetReport | null | undefined
): DataPillTone {
  if (isLoadingReport) return 'amber'
  if (report) return 'green'
  return 'slate'
}

function reportDataSourceLabel(dataProvenance: DatasetReportDataProvenance | null | undefined): string {
  if (dataProvenance?.mocked === false && dataProvenance.source === 'database') {
    return '真实数据'
  }
  if (dataProvenance?.source) return String(dataProvenance.source)
  return '等待数据源'
}

function reportDataSourceSub(dataProvenance: DatasetReportDataProvenance | null | undefined): string {
  if (dataProvenance?.mocked === false) return '数据库 / API 实时聚合'
  return '未返回来源证明'
}

function reportPipelineFilterLabel(pipelineHash: string): string {
  if (pipelineHash) return shortPipelineHash(pipelineHash)
  return '当前版本'
}

function pipelineVersionLabel(pipelineHash: string | null | undefined): string {
  const value = String(pipelineHash || '').trim()
  if (!value || value === 'unknown') return '当前版本'
  return shortPipelineHash(value)
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
  if (isLoadingReport) return '正在加载报告数据...'
  return '点击“重新生成报告”拉取最新报告。'
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
  if (!hasSamples) return '待评估'
  return String(value || 0)
}

function retrievalAuditStatusLabel(status: string | undefined): string {
  const value = String(status || '').trim().toLowerCase()
  if (value === 'passed' || value === 'completed' || value === 'success') {
    return '通过'
  }
  if (value === 'failed' || value === 'error') return '失败'
  if (value === 'running' || value === 'pending') return '生成中'
  return '待评估'
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
    return retrievalAudit?.status === 'failed' || retrievalAudit?.status === 'error'
      ? '待归因'
      : '无异常'
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
  return labels[recommendation] || '待评估'
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
  const valueToneClass = {
    blue: 'text-slate-900',
    green: 'text-emerald-700',
    amber: 'text-amber-700',
    rose: 'text-rose-700',
    violet: 'text-violet-700',
    slate: 'text-slate-800',
  }[tone]

  return (
    <div className="flex min-w-0 items-center gap-2.5 bg-white/88 px-3 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
      <div
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-xl ring-1',
          toneClass
        )}
      >
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <div className={REPORT_LABEL_CLASS}>{label}</div>
        <div className={cn(REPORT_VALUE_CLASS, valueToneClass)}>{value}</div>
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
    <article className="min-w-0 bg-white/95 px-4 py-3.5">
      <div className="flex items-center gap-3">
        <div
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-[0.85rem] ring-1',
            toneClass
          )}
        >
          <Icon className="size-[1.05rem]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className={REPORT_LABEL_CLASS}>{label}</div>
          <div className={cn('mt-0.5', REPORT_METRIC_VALUE_CLASS)}>
            {value}
          </div>
          <div className={cn('mt-1 truncate', REPORT_SUBTEXT_CLASS)} title={sub}>
            {sub}
          </div>
        </div>
      </div>
    </article>
  )
}

function ReportSignalRow({
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
  const dotClass = {
    blue: 'bg-blue-500',
    green: 'bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-500',
    violet: 'bg-violet-500',
    slate: 'bg-slate-400',
  }[tone]

  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200/70 bg-white/70 px-2.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.72)]">
      <span className={cn('size-2 shrink-0 rounded-full', dotClass)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <div
            className="truncate text-[0.75rem] font-medium text-slate-700"
            title={label}
          >
            {label}
          </div>
          <div
            className={cn(
              'shrink-0 text-[0.875rem] font-semibold tabular-nums',
              toneClass
            )}
          >
            {value}
          </div>
        </div>
        <div className={cn('mt-0.5 truncate', REPORT_SUBTEXT_CLASS)} title={sub}>
          {sub}
        </div>
      </div>
    </div>
  )
}

function ReportInlineEmpty({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/55 px-3 py-3">
      <div className="text-[0.8125rem] font-semibold tracking-[-0.01em] text-slate-700">
        {title}
      </div>
      <div className={cn('mt-1 max-w-[32rem]', REPORT_SUBTEXT_CLASS)}>
        {description}
      </div>
    </div>
  )
}

function CompactAuditFact({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: {
      shell: 'border-blue-100 bg-blue-50/45',
      icon: 'bg-blue-100 text-blue-700 ring-blue-200',
      rail: 'bg-blue-500',
      value:
        'border-blue-100 bg-white/80 text-blue-700 shadow-[0_1px_2px_rgba(37,99,235,0.08)]',
    },
    green: {
      shell: 'border-emerald-100 bg-emerald-50/45',
      icon: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
      rail: 'bg-emerald-500',
      value:
        'border-emerald-100 bg-white/80 text-emerald-700 shadow-[0_1px_2px_rgba(5,150,105,0.08)]',
    },
    amber: {
      shell: 'border-amber-100 bg-amber-50/50',
      icon: 'bg-amber-100 text-amber-700 ring-amber-200',
      rail: 'bg-amber-500',
      value:
        'border-amber-100 bg-white/85 text-amber-700 shadow-[0_1px_2px_rgba(217,119,6,0.08)]',
    },
    rose: {
      shell: 'border-rose-100 bg-rose-50/45',
      icon: 'bg-rose-100 text-rose-700 ring-rose-200',
      rail: 'bg-rose-500',
      value:
        'border-rose-100 bg-white/85 text-rose-700 shadow-[0_1px_2px_rgba(225,29,72,0.08)]',
    },
    violet: {
      shell: 'border-violet-100 bg-violet-50/45',
      icon: 'bg-violet-100 text-violet-700 ring-violet-200',
      rail: 'bg-violet-500',
      value:
        'border-violet-100 bg-white/80 text-violet-700 shadow-[0_1px_2px_rgba(124,58,237,0.08)]',
    },
    slate: {
      shell: 'border-slate-200/70 bg-slate-50/55',
      icon: 'bg-slate-100 text-slate-600 ring-slate-200',
      rail: 'bg-slate-300',
      value:
        'border-slate-200 bg-white/80 text-slate-600 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
    },
  }[tone]

  return (
    <div
      className={cn(
        'relative min-w-0 overflow-hidden rounded-xl border px-2.5 py-2',
        toneClass.shell
      )}
    >
      <span
        className={cn('absolute inset-y-2 left-0 w-1 rounded-r-full', toneClass.rail)}
        aria-hidden="true"
      />
      <div className="flex min-w-0 items-center gap-2 pl-1">
        <div
          className={cn(
            'flex size-7 shrink-0 items-center justify-center rounded-lg ring-1',
            toneClass.icon
          )}
        >
          <Icon className="size-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[0.75rem] font-semibold tracking-[-0.01em] text-slate-800">
            {label}
          </div>
          <div className="mt-0.5 truncate text-[0.6875rem] leading-4 text-slate-500" title={sub}>
            {sub}
          </div>
        </div>
        <div
          className={cn(
            'inline-flex h-6 max-w-[46%] shrink-0 items-center justify-center truncate rounded-full border px-2 text-center text-[0.75rem] font-semibold tracking-[-0.01em] tabular-nums',
            toneClass.value
          )}
          title={value}
        >
          {value}
        </div>
      </div>
    </div>
  )
}

function AuditMetricPlaceholder({
  label,
  hint,
}: Readonly<{ label: string; hint: string }>) {
  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-white/65 px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[0.75rem] font-semibold tracking-[-0.01em] text-slate-700">
          {label}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[0.6875rem] font-medium text-slate-500">
          待运行
        </span>
      </div>
      <div className={cn('mt-1 truncate', REPORT_SUBTEXT_CLASS)} title={hint}>
        {hint}
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
        'grid grid-cols-[104px_1fr_42px] items-center gap-2',
        REPORT_TABLE_ROW_CLASS
      )}
    >
      <div className="truncate text-slate-600" title={label}>
        {label}
      </div>
      <div className="h-1.5 rounded-full bg-slate-100">
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
    <div className={REPORT_METRIC_LEDGER_CLASS}>
      <AuditMetricCard
        icon={FileText}
        label="文档总数"
        value={String(totalDocs)}
        sub="数据集画像统计"
        tone="blue"
      />
      <AuditMetricCard
        icon={BarChart3}
        label="总大小"
        value={formatFileSize(Number(totalBytes || 0))}
        sub="累计文件体积"
        tone="violet"
      />
      <AuditMetricCard
        icon={CheckCircle2}
        label="成功"
        value={String(successDocs)}
        sub={`成功率 ${successRate}`}
        tone="green"
      />
      <AuditMetricCard
        icon={AlertTriangle}
        label="失败"
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
        label="生成时间"
        value={latestAuditTime}
        sub="当前报告快照"
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
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2', REPORT_PANEL_TITLE_CLASS)}>
        风险概览
      </div>
      <div className="space-y-1">
        <ReportSignalRow
          label="缺失字段"
          value={formatPct(missingFindingCount, totalDocs)}
          sub={`${missingFindingCount} 条规则命中`}
          tone={missingFindingCount ? 'amber' : 'blue'}
        />
        <ReportSignalRow
          label="重复文档"
          value={formatPct(duplicateFindingCount, totalDocs)}
          sub={`${duplicateFindingCount} 条规则命中`}
          tone={duplicateFindingCount ? 'violet' : 'blue'}
        />
        <ReportSignalRow
          label="低置信度"
          value={formatPct(lowQualityFindingCount, totalDocs)}
          sub={`${lowQualityFindingCount} 条质量规则命中`}
          tone={lowQualityFindingCount ? 'amber' : 'green'}
        />
        <ReportSignalRow
          label="解析失败"
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
  const gateCount = retrievalAudit?.gates?.length || 0
  const hasFailureCategories = Object.values(retrievalAudit?.failure_categories || {}).some(
    (value) => Number(value) > 0
  )
  const statusToneClass = {
    green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    rose: 'border-rose-200 bg-rose-50 text-rose-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-600',
  }[tone]
  const statusIconClass = {
    green: 'bg-emerald-100 text-emerald-700',
    amber: 'bg-amber-100 text-amber-700',
    rose: 'bg-rose-100 text-rose-700',
    slate: 'bg-slate-100 text-slate-600',
  }[tone]
  const StatusIcon = {
    green: CheckCircle2,
    amber: Clock3,
    rose: AlertTriangle,
    slate: FileSearch,
  }[tone]

  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2 overflow-hidden rounded-xl border border-slate-200/70 bg-[linear-gradient(120deg,#f8fbff_0%,#ffffff_54%,#f2fbff_100%)] px-2.5 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100">
              <FileSearch className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <div className={REPORT_PANEL_TITLE_CLASS}>召回审计</div>
                <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-medium tracking-[0.08em] text-blue-700">
                  生产准入
                </span>
              </div>
              <div className={cn('mt-0.5 truncate', REPORT_SUBTEXT_CLASS)}>
                评测、元数据、KG 与压缩证据集中校验。
              </div>
            </div>
          </div>
          <Badge
            variant="outline"
            className={cn(
              'gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold',
              statusToneClass
            )}
          >
            <span className={cn('rounded-full p-0.5', statusIconClass)}>
              <StatusIcon className="size-3" />
            </span>
            {status}
          </Badge>
        </div>
      </div>

      <div className="mt-2 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
        <CompactAuditFact
          icon={AlertTriangle}
          label="失败归因"
          value={retrievalAuditFailureText(retrievalAudit)}
          sub="范围 / 切块 / 排序 / KG"
          tone={hasFailureCategories ? 'rose' : 'slate'}
        />
        <CompactAuditFact
          icon={ShieldCheck}
          label="门禁证据"
          value={gateCount ? `${gateCount} 项` : '未配置'}
          sub="最新回归门禁"
          tone={gateCount ? 'violet' : 'slate'}
        />
        <CompactAuditFact
          icon={Layers}
          label="KG 建议"
          value={retrievalAuditKgRecommendationText(retrievalAudit)}
          sub="KG 开关对比"
          tone={retrievalAudit?.kg_recommendation === 'full_kg_assist' ? 'green' : 'slate'}
        />
        <CompactAuditFact
          icon={Archive}
          label="插件包"
          value={retrievalAuditHashText(retrievalAudit)}
          sub={pluginRefs.length ? `${pluginRefs.length} 个插件引用` : '未接入插件'}
          tone={pluginRefs.length ? 'blue' : 'slate'}
        />
      </div>

      <div className="mt-2 overflow-hidden rounded-lg border border-slate-100">
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/80 px-2.5 py-1.5">
          <div className="text-[0.75rem] font-semibold tracking-[-0.01em] text-slate-700">
            门禁指标
          </div>
          <div className="text-[0.6875rem] text-slate-500">
            最新回归门禁
          </div>
        </div>
        <div
          className={cn(
            'grid grid-cols-[1fr_104px] bg-white px-2.5 py-1.5',
            REPORT_TABLE_HEADER_CLASS
          )}
        >
          <span>指标</span>
          <span className="text-right">数值</span>
        </div>
        {metricRows.length === 0 ? (
          <div className="border-t border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] px-2.5 py-2">
            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
              <AuditMetricPlaceholder
                label="Hit@K"
                hint="召回命中门槛"
              />
              <AuditMetricPlaceholder
                label="Metadata"
                hint="元数据命中/召回"
              />
              <AuditMetricPlaceholder
                label="Context"
                hint="有效上下文占比"
              />
              <AuditMetricPlaceholder
                label="Noise"
                hint="噪声与 KG 噪声"
              />
            </div>
            <div className={cn('mt-2 text-center', REPORT_SUBTEXT_CLASS)}>
              运行 Golden / regression 后填充真实门禁数据。
            </div>
          </div>
        ) : (
          metricRows.map((row) => (
            <div
              key={row.key}
              className={cn(
                'grid grid-cols-[1fr_104px] border-t border-slate-100 px-2.5 py-1.5',
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
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className={REPORT_PANEL_TITLE_CLASS}>字段覆盖分布</div>
        <Badge variant="outline" className="rounded-full text-[11px]">
          {fieldCoverageBadge}
        </Badge>
      </div>
      <div className="space-y-2">
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
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className={REPORT_PANEL_TITLE_CLASS}>文档分布 Top</div>
        <Button
          variant="link"
          className="h-auto p-0 text-[0.71875rem]"
          onClick={onClearFolderQuery}
        >
          查看全部
        </Button>
      </div>
      {topDocumentRows.length === 0 ? (
        <EmptyState
          title="暂无分布数据"
          description="当前报告没有目录或文件类型分布。"
        />
      ) : (
        <div className="space-y-2">
          {topDocumentRows.map((row) => (
            <div
              key={row.name}
              className={cn(
                'grid grid-cols-[1fr_44px_84px] items-center gap-2',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <div className="truncate font-medium text-slate-700" title={row.name}>
                {row.name}
              </div>
              <div className="tabular-nums text-slate-700">{row.value}</div>
              <div className="h-1.5 rounded-full bg-slate-100">
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
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2', REPORT_PANEL_TITLE_CLASS)}>
        内容健康
      </div>
      <div className="space-y-1">
        <ReportSignalRow
          label="可疑链接"
          value={governanceAuditUrlValue}
          sub={governanceAuditUrlSub}
          tone={governanceAuditHasSamples ? 'blue' : 'slate'}
        />
        <ReportSignalRow
          label="外部附件"
          value={governanceAuditImageValue}
          sub={governanceAuditImageSub}
          tone={governanceAuditHasSamples ? 'green' : 'slate'}
        />
        <ReportSignalRow
          label="敏感信息"
          value={String(sensitiveHits)}
          sub={`隐私 ${piiHits} / 密钥 ${secretHits}`}
          tone={sensitiveHits ? 'amber' : 'green'}
        />
        <ReportSignalRow
          label="低质量片段"
          value={String(lowQualityFindingCount)}
          sub="质量规则命中"
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
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2.5', REPORT_PANEL_TITLE_CLASS)}>知识分类</div>
      {categoryBarData.length === 0 ? (
        <ReportInlineEmpty
          title="分类尚未建立"
          description="当前数据集还没有分类计数；绑定分类或同步分类树后，这里会展示分布。"
        />
      ) : (
        <SafeResponsiveChart className="h-[220px]" minHeight={220}>
          <BarChart
            data={categoryBarData.slice(0, 8)}
            margin={{ left: 0, right: 8, top: 4, bottom: 4 }}
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
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2.5', REPORT_PANEL_TITLE_CLASS)}>
        处理版本分布
      </div>
      {pipelineVersions.length === 0 ? (
        <ReportInlineEmpty
          title="暂无版本快照"
          description="完成一次解析或治理后，这里会展示不同处理版本的文档分布。"
        />
      ) : (
        <div className="grid gap-2.5 lg:grid-cols-[1fr_1fr] xl:grid-cols-1 2xl:grid-cols-[1fr_1fr]">
          <SafeResponsiveChart className="h-[180px]" minHeight={180}>
            <PieChart>
              <Pie
                data={pipelineVersionsWithFill}
                dataKey="documents"
                nameKey="display_label"
                innerRadius={44}
                outerRadius={72}
              />
              <Tooltip
                cursor={CHART_TOOLTIP_CURSOR}
                contentStyle={CHART_TOOLTIP_STYLE}
                labelStyle={CHART_TOOLTIP_LABEL_STYLE}
              />
            </PieChart>
          </SafeResponsiveChart>
          <div className="space-y-1.5 self-center">
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
                    {pipelineVersionLabel(version.pipeline_hash)}
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
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className={REPORT_PANEL_TITLE_CLASS}>风险命中记录</div>
        <Badge variant="outline" className="rounded-full px-2 text-[11px]">
          命中项
        </Badge>
      </div>
      {issueRows.length === 0 ? (
        <ReportInlineEmpty
          title="暂无风险命中"
          description="当前报告没有失败任务或质量规则命中；后续出现异常会在这里列出。"
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-100">
          <div
            className={cn(
            'grid grid-cols-[104px_64px_104px_1fr_56px] bg-slate-50 px-2.5 py-1.5',
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
                'grid grid-cols-[104px_64px_104px_1fr_56px] items-center border-t border-slate-100 px-2.5 py-2',
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

function ReportSectionHeading({
  index,
  title,
  description,
}: Readonly<{
  index: string
  title: string
  description: string
}>) {
  return (
    <div className="flex items-end gap-3 border-b border-slate-200/70 pb-2.5">
      <span className="pb-0.5 font-mono text-[11px] font-semibold tracking-[0.16em] text-sky-600">
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-[0.9375rem] font-semibold tracking-[-0.015em] text-slate-950">
          {title}
        </h2>
        <p className="mt-0.5 text-xs leading-4 text-slate-500">{description}</p>
      </div>
      <span
        className="mb-1 hidden h-px w-20 bg-gradient-to-r from-sky-300/80 to-transparent sm:block"
        aria-hidden="true"
      />
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
      <ReportSectionHeading
        index="01"
        title="报告摘要"
        description="先核对规模、处理结果与召回门禁，再进入质量细节。"
      />
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

      <ReportSectionHeading
        index="02"
        title="数据质量"
        description="从风险、字段覆盖、内容规模和治理痕迹四个维度检查当前快照。"
      />
      <div className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-[1.05fr_1.2fr_1.05fr_0.95fr]">
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

      <ReportSectionHeading
        index="03"
        title="结构与风险"
        description="查看分类分布、处理版本与可追溯的风险命中记录。"
      />
      <div className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-[1.2fr_0.9fr_1.4fr]">
        <CategoryChartPanel categoryBarData={categoryBarData} />
        <PipelineVersionsPanel
          pipelineVersions={pipelineVersions}
          pipelineVersionsWithFill={pipelineVersionsWithFill}
          versionTotal={versionTotal}
        />
        <div className="xl:col-span-2 2xl:col-span-1">
          <IssueRowsPanel issueRows={issueRows} />
        </div>
      </div>
    </section>
  )
}

function LoadingButtonIcon({
  loading,
  icon: Icon,
}: Readonly<{ loading: boolean; icon: LucideIcon }>) {
  if (loading) {
    return <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
  }
  return <Icon className="size-3.5" />
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
    <div className="grid min-w-0 gap-px overflow-hidden rounded-2xl border border-sky-200/70 bg-sky-200/60 shadow-[0_16px_38px_-30px_rgba(14,116,144,0.5)] sm:grid-cols-2 xl:grid-cols-[1.35fr_0.86fr_0.9fr_0.88fr_1.15fr]">
      <DataPill
        icon={Database}
        label="数据集"
        value={selectedDatasetName}
        sub={datasetId ? `ID ${shortPipelineHash(datasetId)}` : '未选择'}
        tone="blue"
      />
      <DataPill
        icon={FileSearch}
        label="文档"
        value={`${totalDocs} 篇文档`}
        sub="报告画像"
        tone="blue"
      />
      <DataPill
        icon={ShieldCheck}
        label="状态"
        value={reportStatusLabel(isLoadingReport, report)}
        sub={report ? '可导出 / 可审计' : '等待生成报告'}
        tone={reportStatusTone(isLoadingReport, report)}
      />
      <DataPill
        icon={Clock3}
        label="生成"
        value={latestAuditTime}
        sub={report ? '报告快照时间' : '暂无'}
        tone="slate"
      />
      <DataPill
        icon={ShieldCheck}
        label="来源"
        value={dataSourceLabel}
        sub={dataSourceSub}
        tone={dataProvenance?.mocked === false ? 'green' : 'amber'}
      />
    </div>
  )
}

function ReportsPageHero({
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
    <KnowledgeOpsHero
      iconImage="report-export"
      eyebrow="Report Ops"
      badge="审计证据与导出中心"
      title="数据报告"
      description="汇总数据集画像、召回门禁与治理风险，形成可导出的审计快照。"
      className="lg:flex-col lg:items-stretch 2xl:flex-row 2xl:items-start"
      summary={
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
      }
    />
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
    <section className="space-y-3 rounded-[1.2rem] border border-slate-200/75 bg-white/88 p-3.5 shadow-[0_18px_44px_-36px_rgba(15,23,42,0.35)] backdrop-blur">
      <div className="grid gap-3 xl:grid-cols-[1.25fr_1.1fr_0.85fr_auto] xl:items-end">
        <div className="space-y-1.5">
          <Label
            htmlFor="dataset-select"
            className={REPORT_FILTER_LABEL_CLASS}
          >
            数据集
          </Label>
          <Select value={datasetId} onValueChange={onDatasetChange}>
            <SelectTrigger
              id="dataset-select"
              className={REPORT_SELECT_TRIGGER_CLASS}
            >
              <SelectValue
                placeholder={isLoadingDatasets ? '加载中...' : '请选择数据集'}
              />
            </SelectTrigger>
            <SelectContent>
              {datasets.map((ds) => (
                <SelectItem
                  key={ds.id}
                  value={ds.id}
                  className={REPORT_SELECT_ITEM_CLASS}
                >
                  {ds.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label
            htmlFor="pipeline-hash"
            className={REPORT_FILTER_LABEL_CLASS}
          >
            处理版本
          </Label>
          <Select
            value={pipelineVersionSelectValue}
            onValueChange={onPipelineHashChange}
          >
            <SelectTrigger
              id="pipeline-hash"
              className={REPORT_SELECT_TRIGGER_CLASS}
            >
              <SelectValue placeholder="选择处理版本" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                value={DEFAULT_PIPELINE_VERSION_VALUE}
                className={REPORT_SELECT_ITEM_CLASS}
              >
                当前版本（默认）
              </SelectItem>
              {pipelineVersionOptions.map((v) => (
                <SelectItem
                  key={v.pipeline_hash}
                  value={v.pipeline_hash}
                  className={REPORT_SELECT_ITEM_CLASS}
                >
                  {shortPipelineHash(v.pipeline_hash)} · {v.documents} 个文档
                </SelectItem>
              ))}
              {pipelineVersionOptions.length === 0 ? (
                <SelectItem
                  value="__mimirq_no_pipeline_versions__"
                  disabled
                  className={REPORT_SELECT_ITEM_CLASS}
                >
                  暂无可选历史版本
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label
            htmlFor="connector-limit"
            className={REPORT_FILTER_LABEL_CLASS}
          >
            运行记录
          </Label>
          <Select
            value={String(connectorRunsLimit)}
            onValueChange={(value) => onConnectorRunsLimitChange(Number(value || 20))}
          >
            <SelectTrigger
              id="connector-limit"
              className={REPORT_SELECT_TRIGGER_CLASS}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0" className={REPORT_SELECT_ITEM_CLASS}>
                不附带记录
              </SelectItem>
              <SelectItem value="10" className={REPORT_SELECT_ITEM_CLASS}>
                10 条记录
              </SelectItem>
              <SelectItem value="20" className={REPORT_SELECT_ITEM_CLASS}>
                20 条记录（默认）
              </SelectItem>
              <SelectItem value="50" className={REPORT_SELECT_ITEM_CLASS}>
                50 条记录
              </SelectItem>
              <SelectItem value="100" className={REPORT_SELECT_ITEM_CLASS}>
                100 条记录
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex h-9 items-center gap-2 rounded-xl border border-slate-200/70 bg-slate-50/70 px-3">
          <Switch
            id="only-issues-switch"
            checked={showOnlyIssues}
            onCheckedChange={onShowOnlyIssuesChange}
          />
          <Label
            htmlFor="only-issues-switch"
            className="whitespace-nowrap text-xs font-medium text-slate-600"
          >
            只看异常
          </Label>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/70 pt-3">
        <div className="flex h-9 items-center gap-2 rounded-xl bg-slate-50/90 px-3 ring-1 ring-inset ring-slate-200/70">
          <Switch
            id="redact-switch"
            checked={redact}
            onCheckedChange={onRedactChange}
          />
          <Label
            htmlFor="redact-switch"
            className="text-xs font-medium text-slate-600"
          >
            导出脱敏
          </Label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className={REPORT_SECONDARY_ACTION_CLASS}
                disabled={!datasetId}
                aria-label="打开报告导出菜单"
              >
                <LoadingButtonIcon
                  loading={
                    isExportingJson ||
                    isExportingHtml ||
                    isExportingRagAuditHtml ||
                    isExportingBundle
                  }
                  icon={Download}
                />
                <span>导出报告</span>
                <ChevronDown className="size-3.5 text-slate-400" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-64 rounded-2xl border-slate-200/80 bg-white/95 p-1.5 shadow-[0_24px_70px_-28px_rgba(15,23,42,0.38)] backdrop-blur-xl"
            >
              <DropdownMenuLabel className="px-2.5 pb-1 pt-2 text-[11px] font-semibold tracking-[0.08em] text-slate-400">
                基础与完整数据
              </DropdownMenuLabel>
              <DropdownMenuGroup>
                <DropdownMenuItem
                  onSelect={onExportJson}
                  disabled={!datasetId || isExportingJson}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-sky-50 focus:text-sky-800"
                  aria-label="导出 JSON"
                >
                  <LoadingButtonIcon loading={isExportingJson} icon={Download} />
                  <span>标准 JSON 报告</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportCompleteJson}
                  disabled={!datasetId || !report}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-sky-50 focus:text-sky-800"
                  aria-label="导出完整 JSON"
                >
                  <Archive className="size-3.5" />
                  <span>完整 JSON 快照</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportChartsJson}
                  disabled={!datasetId || !report}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-sky-50 focus:text-sky-800"
                  aria-label="导出 RAG 统计"
                >
                  <BarChart3 className="size-3.5" />
                  <span>RAG 统计数据</span>
                </DropdownMenuItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator className="my-1.5" />
              <DropdownMenuLabel className="px-2.5 pb-1 pt-1 text-[11px] font-semibold tracking-[0.08em] text-slate-400">
                审计与交付物
              </DropdownMenuLabel>
              <DropdownMenuGroup>
                <DropdownMenuItem
                  onSelect={onExportRagAuditHtml}
                  disabled={!datasetId || isExportingRagAuditHtml}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-sky-50 focus:text-sky-800"
                  aria-label="导出 RAG 审计报告"
                >
                  <LoadingButtonIcon
                    loading={isExportingRagAuditHtml}
                    icon={ShieldCheck}
                  />
                  <span>RAG 审计报告</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportBundleZip}
                  disabled={!datasetId || isExportingBundle}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-sky-50 focus:text-sky-800"
                  aria-label="导出数据包 ZIP"
                >
                  <LoadingButtonIcon loading={isExportingBundle} icon={Archive} />
                  <span>数据包 Bundle ZIP</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportHtml}
                  disabled={!datasetId || isExportingHtml}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-sky-50 focus:text-sky-800"
                  aria-label="导出 HTML"
                >
                  <LoadingButtonIcon loading={isExportingHtml} icon={FileText} />
                  <span>HTML 阅读版</span>
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            className={REPORT_PRIMARY_ACTION_CLASS}
            onClick={onRegenerateReport}
            disabled={!datasetId || isLoadingReport}
            aria-label="重新生成报告"
          >
            <LoadingButtonIcon loading={isLoadingReport} icon={PlayCircle} />
            <span>重新生成</span>
          </Button>
          <Button
            variant="outline"
            className={REPORT_SECONDARY_ACTION_CLASS}
            onClick={onRefresh}
            disabled={isLoadingDatasets}
            aria-label="刷新"
          >
            <LoadingButtonIcon loading={isLoadingDatasets} icon={RefreshCw} />
            <span>刷新</span>
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
        display_label: pipelineVersionLabel(version.pipeline_hash),
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
  const governanceAuditUnavailableSub = '运行治理审计后展示'
  const governanceAuditUrlValue = governanceAuditHasSamples
    ? String(governanceAudit?.urls_changed_total || 0)
    : governanceAuditStatValue(governanceAuditHasSamples, governanceAudit?.urls_changed_total)
  const governanceAuditImageValue = governanceAuditHasSamples
    ? String(governanceAudit?.images_removed_total || 0)
    : governanceAuditStatValue(governanceAuditHasSamples, governanceAudit?.images_removed_total)
  const governanceAuditUrlSub = governanceAuditHasSamples
    ? 'URL 变更记录'
    : governanceAuditUnavailableSub
  const governanceAuditImageSub = governanceAuditHasSamples
    ? '图片处理记录'
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
  const fieldCoverageBadge = hasGovernanceCoverage ? '治理审计' : '基础画像'

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
      <div className={KNOWLEDGE_OPS_BACKGROUND_CLASS}>
        <AnalysisPageShell
          title="数据报告与审计概览"
          description="一键导出数据报告与审计结果，支持多种格式与指标视图，便于数据治理与合规审查。"
          icon={FileText}
          iconColor="text-primary"
          badge="报告"
          size="full"
          showHeader={false}
          bodyGutter="none"
          bodyClassName="!pb-0 !pt-0"
          bodyContainerClassName="max-w-none"
        >
          <div
            data-reports-dossier="true"
            className="space-y-4 px-4 py-4 md:px-6 md:py-5"
          >
            <ReportsPageHero
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
        </AnalysisPageShell>
      </div>
    </AppFrame>
  )
}
