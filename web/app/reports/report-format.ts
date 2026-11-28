import type { DatasetReport, DatasetReportDataProvenance } from '@/lib/report-schema'
import type { ReportFinding, RetrievalAudit } from './types'

export function shortPipelineHash(hash: string) {
  return hash.length <= 18 ? hash : `${hash.slice(0, 10)}…${hash.slice(-6)}`
}

export function formatReportText(value: string | null) {
  if (value === null) return '—'
  return value.length === 0 ? '""' : value
}

export function formatReportPercent(value: number | null) {
  return value === null ? '—' : `${value.toFixed(1).replace(/\.0$/, '')}%`
}

export function reportDataSourceLabel(provenance: DatasetReportDataProvenance) {
  if (provenance.source === 'database' && provenance.mocked === false) return '真实数据'
  return formatReportText(provenance.source)
}

export function reportPipelineFilterLabel(pipelineHash: string | null) {
  return pipelineHash === null ? '全部处理版本' : formatReportText(shortPipelineHash(pipelineHash))
}

export function findingSeverityLabel(severity: ReportFinding['severity']) {
  const labels = { info: '信息', warning: '警告', error: '错误' }
  return labels[severity]
}

export function filterReportFindings(findings: readonly ReportFinding[], onlyIssues: boolean) {
  return onlyIssues ? findings.filter((finding) => finding.severity !== 'info' && finding.count > 0) : findings
}

export function formatGovernanceCount(
  audit: DatasetReport['governance_audit'],
  counter: 'urls_changed_total' | 'images_removed_total',
) {
  if (audit === null || audit.used_documents === 0) return '待评估'
  return String(audit[counter])
}

const PASSED_AUDIT_STATUSES = new Set(['passed', 'completed', 'success'])
const FAILED_AUDIT_STATUSES = new Set(['failed', 'error'])
const AUDIT_STATUSES: Readonly<Record<string, string>> = {
  running: '进行中',
  pending: '待处理',
  unavailable: '未取得',
}
export function retrievalAuditStatusLabel(status: string | undefined) {
  if (status === undefined) return '未取得'
  if (PASSED_AUDIT_STATUSES.has(status)) return '通过'
  if (FAILED_AUDIT_STATUSES.has(status)) return '失败'
  return Object.hasOwn(AUDIT_STATUSES, status) ? AUDIT_STATUSES[status] : formatReportText(status)
}

export function retrievalAuditTone(status: string | undefined): 'green' | 'amber' | 'rose' | 'slate' {
  if (status === undefined) return 'slate'
  if (PASSED_AUDIT_STATUSES.has(status)) return 'green'
  if (FAILED_AUDIT_STATUSES.has(status)) return 'rose'
  if (status === 'running' || status === 'pending') return 'amber'
  return 'slate'
}

const RATIO_METRICS = new Set([
  'hit_at_1',
  'hit_at_3',
  'retrieval_hit_at_1',
  'retrieval_hit_at_3',
  'expected_metadata_hit_rate',
  'expected_metadata_recall',
  'retrieval_effective_context_rate',
  'retrieval_noise_rate',
  'kg_noise_rate',
])
export function formatRetrievalAuditMetric(key: string, value: unknown): string {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('召回指标必须是有限数值')
    return RATIO_METRICS.has(key)
      ? formatReportPercent(value * 100)
      : value.toLocaleString('zh-CN', { maximumFractionDigits: 3, useGrouping: false })
  }
  if (typeof value === 'string') return formatReportText(value)
  const text = JSON.stringify(value)
  if (text === undefined) throw new TypeError('召回指标没有 JSON 表示')
  return text
}

const FAILURE_NAMES: Readonly<Record<string, string>> = {
  scope: '范围',
  chunking: '切块',
  ranking: '排序',
  absence: '缺内容',
  kg_noise: 'KG 噪声',
  adapter: '适配器',
}
export function retrievalAuditFailureText(audit: RetrievalAudit | null) {
  if (audit === null) return '未取得'
  const categories = Object.entries(audit.failure_categories).filter(([, count]) => count !== 0)
  if (categories.length > 0)
    return categories
      .map(
        ([key, count]) => `${Object.hasOwn(FAILURE_NAMES, key) ? FAILURE_NAMES[key] : formatReportText(key)} ${count}`,
      )
      .join(' / ')
  if (PASSED_AUDIT_STATUSES.has(audit.status)) return '无失败记录'
  return FAILED_AUDIT_STATUSES.has(audit.status) ? '未提供归因' : '未提供失败记录'
}

const KG_RECOMMENDATIONS: Readonly<Record<string, string>> = {
  full_kg_assist: '可启用完整 KG',
  query_expansion_only: '仅启用查询扩展',
  boost_only: '仅启用 KG boost',
  none: '保持关闭',
}
export function retrievalAuditKgRecommendationText(audit: RetrievalAudit | null) {
  if (audit === null || audit.kg_recommendation === null) return '未提供建议'
  const recommendation = audit.kg_recommendation
  return Object.hasOwn(KG_RECOMMENDATIONS, recommendation)
    ? KG_RECOMMENDATIONS[recommendation]
    : formatReportText(recommendation)
}
