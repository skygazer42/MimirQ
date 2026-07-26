'use client'

import { formatDate } from '@/lib/utils'

import type {
  DatasetReport,
  DatasetReportDataProvenance,
} from '@/types'

import type {
  DataPillTone,
  IssueRow,
  ReportConnectorRun,
  ReportFinding,
  ReportMetricDatum,
  RetrievalAudit,
  RetrievalAuditMetricRow,
} from './types'

export function shortPipelineHash(hash: string) {
  const value = String(hash || '').trim()
  if (value.length <= 18) return value
  return `${value.slice(0, 10)}…${value.slice(-6)}`
}

export function safeNumber(value: unknown): number {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n : 0
}

export function formatPct(numerator: number, denominator: number) {
  if (!denominator || !Number.isFinite(denominator)) return '0%'
  return `${((numerator / denominator) * 100).toFixed(1).replace('.0', '')}%`
}

export function sumRecordValues(value: Record<string, number> | null | undefined) {
  return Object.values(value || {}).reduce(
    (acc, item) => acc + safeNumber(item),
    0
  )
}

export function capCoverageValue(value: unknown, max: number) {
  if (max <= 0) return 0
  return Math.max(0, Math.min(max, safeNumber(value)))
}

export function reportStatusLabel(isLoadingReport: boolean, report: DatasetReport | null | undefined): string {
  if (isLoadingReport) return '生成中'
  if (report) return '已就绪'
  return '待生成'
}

export function reportStatusTone(
  isLoadingReport: boolean,
  report: DatasetReport | null | undefined
): DataPillTone {
  if (isLoadingReport) return 'amber'
  if (report) return 'green'
  return 'slate'
}

export function reportDataSourceLabel(dataProvenance: DatasetReportDataProvenance | null | undefined): string {
  if (dataProvenance?.mocked === false && dataProvenance.source === 'database') {
    return '真实数据'
  }
  if (dataProvenance?.source) return String(dataProvenance.source)
  return '等待数据源'
}

export function reportDataSourceSub(dataProvenance: DatasetReportDataProvenance | null | undefined): string {
  if (dataProvenance?.mocked === false) return '数据库 / API 实时聚合'
  return '未返回来源证明'
}

export function reportPipelineFilterLabel(pipelineHash: string): string {
  if (pipelineHash) return shortPipelineHash(pipelineHash)
  return '当前版本'
}

export function pipelineVersionLabel(pipelineHash: string | null | undefined): string {
  const value = String(pipelineHash || '').trim()
  if (!value || value === 'unknown') return '当前版本'
  return shortPipelineHash(value)
}

export function findingSeverityLabel(severity: string | null | undefined): string {
  if (severity === 'error') return '错误'
  if (severity === 'warning') return '警告'
  return '信息'
}

export function issueLevelClass(level: string): string {
  if (level === '错误') return 'text-destructive'
  if (level === '警告') return 'text-warning'
  return 'text-success'
}

export function reportPreviewEmptyTitle(datasetId: string, isLoadingReport: boolean): string {
  if (!datasetId) return '请选择数据集'
  if (isLoadingReport) return '报告加载中...'
  return '暂无预览'
}

export function reportPreviewEmptyDescription(datasetId: string, isLoadingReport: boolean): string {
  if (!datasetId) return '选择一个数据集后即可生成报告预览并导出。'
  if (isLoadingReport) return '正在加载报告数据...'
  return '点击“重新生成报告”拉取最新报告。'
}

export function filterReportFindings(
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

export function countFindingsByPattern(rows: ReportFinding[], pattern: RegExp): number {
  return rows
    .filter((item) => pattern.test(`${item.key} ${item.label}`))
    .reduce((acc, item) => acc + safeNumber(item.count), 0)
}

export function buildTopDocumentRows(
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

export function buildIssueRows(
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

export function chunkStatsCoverage(report: DatasetReport | null, totalDocs: number): number {
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

export function governanceAuditStatValue(
  hasSamples: boolean,
  value: number | undefined
): string {
  if (!hasSamples) return '待评估'
  return String(value || 0)
}

export function retrievalAuditStatusLabel(status: string | undefined): string {
  const value = String(status || '').trim().toLowerCase()
  if (value === 'passed' || value === 'completed' || value === 'success') {
    return '通过'
  }
  if (value === 'failed' || value === 'error') return '失败'
  if (value === 'running' || value === 'pending') return '生成中'
  return '待评估'
}

export function retrievalAuditTone(
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

export function trimFixedNumber(value: string): string {
  let end = value.length
  while (end > 0 && value[end - 1] === '0') {
    end -= 1
  }
  if (end > 0 && value[end - 1] === '.') {
    end -= 1
  }
  return value.slice(0, end) || '0'
}

export function formatRetrievalAuditMetric(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (Math.abs(value) <= 1) return `${(value * 100).toFixed(1)}%`
    return trimFixedNumber(value.toFixed(3))
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string' && value.trim()) return value
  return '-'
}

export function retrievalAuditMetricRows(
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

export function retrievalAuditFailureText(
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

export function retrievalAuditHashText(
  retrievalAudit: RetrievalAudit | null | undefined
): string {
  const hashes = retrievalAudit?.plugin_package_hashes || []
  if (!hashes.length) return '未绑定'
  return hashes.map((hash) => shortPipelineHash(hash)).slice(0, 2).join(' / ')
}

export function retrievalAuditKgRecommendationText(
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
