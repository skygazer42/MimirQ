import type { DatasetReport, ReportFolderNode } from '@/lib/report-schema'
import type { ReportRecordRow, ReportMetricDatum } from './types'
import { formatReportPercent, formatReportText, formatRetrievalAuditMetric } from './report-format'

const STATUS_LABELS: Readonly<Record<string, string>> = {
  pending: '待处理',
  parsing: '解析中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  quarantined: '隔离',
  cancelled: '已取消',
  deleting: '删除中',
}
export function reportStatusRows(counts: Readonly<Record<string, number>>) {
  return Object.entries(counts)
    .filter(([, count]) => count !== 0)
    .map(([key, value]) => ({
      key,
      value,
      label: Object.hasOwn(STATUS_LABELS, key) ? STATUS_LABELS[key] : formatReportText(key),
      tone: key === 'completed' ? 'success' : key === 'failed' ? 'danger' : key === 'quarantined' ? 'warning' : 'info',
    }))
}

const AUDIT_METRICS = [
  { keys: ['hit_at_1', 'retrieval_hit_at_1'], label: '召回命中 Hit@1' },
  { keys: ['hit_at_3', 'retrieval_hit_at_3'], label: '召回命中 Hit@3' },
  { keys: ['expected_metadata_hit_rate'], label: '元数据命中' },
  { keys: ['expected_metadata_recall'], label: '元数据召回' },
  { keys: ['retrieval_effective_context_rate'], label: '有效上下文' },
  { keys: ['retrieval_noise_rate'], label: '噪声占比' },
  { keys: ['kg_noise_rate'], label: '图谱噪声' },
  { keys: ['retrieval_mrr'], label: 'MRR' },
  { keys: ['retrieval_ndcg'], label: 'NDCG' },
  { keys: ['retrieval_ndcg_at_20'], label: 'NDCG@20' },
] as const

export function reportAuditRows(audit: DatasetReport['retrieval_audit']) {
  if (audit === null) return []
  return audit.gates.flatMap((gate, index) =>
    AUDIT_METRICS.flatMap((metric) => {
      const key = metric.keys.find((key) => Object.hasOwn(gate.metrics, key))
      return key === undefined
        ? []
        : [
            {
              key: JSON.stringify([index, key]),
              label: metric.label,
              value: formatRetrievalAuditMetric(key, gate.metrics[key]),
              gate: gate.name,
              status: gate.status,
            },
          ]
    }),
  )
}

export function formatRecordShare(count: number, total: number) {
  return formatReportPercent(total > 0 ? (count / total) * 100 : null)
}
export function recordedRiskValue(value: number, hasRecord: boolean) {
  return value !== 0 || hasRecord ? String(value) : '待评估'
}

function sumCounts(counts: Readonly<Record<string, number>>) {
  return Object.values(counts).reduce((total, count) => total + count, 0)
}

export function buildReportOverview(report: DatasetReport) {
  const profile = report.profile
  const completedDocuments = Object.hasOwn(profile.by_status, 'completed') ? profile.by_status.completed : 0
  const failedDocuments = report.compliance.failed_documents
  const piiHits = sumCounts(report.compliance.pii_hits_total)
  const secretHits = sumCounts(report.compliance.secrets_hits_total)
  const documentRecords: ReportRecordRow[] = [
    { label: '处理状态', count: sumCounts(profile.by_status), total: profile.total_documents },
    { label: '文件类型', count: sumCounts(profile.by_file_type), total: profile.total_documents },
    { label: '文档目录', count: sumCounts(profile.by_directory), total: profile.total_documents },
    { label: '解析来源', count: profile.parsing_provenance.docs_with_provenance, total: profile.total_documents },
    {
      label: '包含切块',
      count: profile.chunk_count_histogram.reduce((total, bin) => total + bin.count, 0),
      total: profile.total_documents,
    },
  ]
  const governanceRecords: ReportRecordRow[] = []
  const audit = report.governance_audit
  if (audit !== null)
    governanceRecords.push(
      { label: '字符统计记录', count: audit.docs_with_char_stats, total: audit.used_documents },
      { label: '解析持久化记录', count: audit.docs_with_parsed_content_persisted, total: audit.used_documents },
      { label: '变更文档', count: audit.docs_changed, total: audit.used_documents },
      { label: '过滤文档', count: audit.docs_dropped, total: audit.used_documents },
    )
  const governance = report.governance_metrics
  if (governance !== null)
    governanceRecords.push({
      label: '治理记录',
      count: governance.docs_with_governance,
      total: governance.used_documents,
    })
  return {
    completedDocuments,
    failedDocuments,
    completionPercent: profile.total_documents > 0 ? (completedDocuments / profile.total_documents) * 100 : null,
    failurePercent: profile.total_documents > 0 ? (failedDocuments / profile.total_documents) * 100 : null,
    piiHits,
    secretHits,
    sensitiveHits: piiHits + secretHits,
    documentRecords,
    governanceRecords,
  }
}

function topGroups(rows: ReportMetricDatum[]) {
  return rows.sort((a, b) => b.value - a.value || a.name.localeCompare(b.name)).slice(0, 12)
}
function topCounts(counts: Readonly<Record<string, number>>) {
  return topGroups(Object.entries(counts).map(([name, value]) => ({ name, value })))
}

export function buildReportCharts(report: DatasetReport) {
  const governance = report.governance_metrics
  const audit = report.governance_audit
  let folderSubtrees: ReportMetricDatum[] | null = null
  if (report.folder_tree !== null) {
    const rows: ReportMetricDatum[] = []
    function walk(node: ReportFolderNode) {
      rows.push({ name: node.path, value: node.documents })
      for (const child of node.children) walk(child)
    }
    for (const child of report.folder_tree.root.children) walk(child)
    folderSubtrees = topGroups(rows)
  }
  return {
    drop_reasons_top:
      governance === null || governance.used_documents === 0 ? null : topCounts(governance.drop_reasons_total),
    rule_packs_top:
      governance === null || governance.used_documents === 0 ? null : topCounts(governance.rule_packs_docs),
    governance_audit:
      audit === null || audit.used_documents === 0
        ? null
        : {
            chars: [
              { name: 'original_chars_total', value: audit.original_chars_total },
              { name: 'cleaned_chars_total', value: audit.cleaned_chars_total },
            ],
            reduction_histogram: audit.char_reduction_pct_histogram.map((bin) => ({
              name: bin.label,
              value: bin.count,
            })),
            density_histogram: audit.density_pct_histogram.map((bin) => ({ name: bin.label, value: bin.count })),
            heading_ratio_histogram: audit.heading_ratio_pct_histogram.map((bin) => ({
              name: bin.label,
              value: bin.count,
            })),
            effects_top: topCounts({
              paragraphs_dropped_total: audit.paragraphs_dropped_total,
              references_removed_lines_total: audit.references_removed_lines_total,
              urls_changed_total: audit.urls_changed_total,
              boilerplate_removed_lines_total: audit.boilerplate_removed_lines_total,
              images_removed_total: audit.images_removed_total,
              tables_normalized_total: audit.tables_normalized_total,
              code_lines_stripped_total: audit.code_lines_stripped_total,
            }),
          },
    folder_subtrees: folderSubtrees,
  }
}
