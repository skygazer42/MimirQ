import { getDocumentKind } from '@/components/ingestion/monitor-utils'
import { cn } from '@/lib/utils'
import type { Document, DocumentPipelineOptions } from '@/types'

import type {
  ActingState,
  JsonRecord,
  QuarantineAction,
  QuarantineSeverity,
  UserMetadata,
} from './types'

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getRecordField(source: JsonRecord | undefined, key: string): JsonRecord | null {
  const value = source?.[key]
  return isRecord(value) ? value : null
}

export function getUserMeta(doc: Document): UserMetadata | null {
  const meta = doc.metadata
  const user = getRecordField(meta, 'user')
  return user || null
}

export function isReviewed(doc: Document): boolean {
  const user = getUserMeta(doc)
  return Boolean(user?.quarantine_reviewed)
}

export function getDropReasons(doc: Document): string[] {
  const reasons = doc.governance?.drop_reasons || {}
  const governanceReasons =
    !reasons || typeof reasons !== 'object'
      ? []
      : Object.entries(reasons)
          .filter(([, v]) => typeof v === 'number' && v > 0)
          .map(([k]) => k)
          .sort((a, b) => a.localeCompare(b))
  if (governanceReasons.length) return governanceReasons

  const errorCode = String(doc.error_code || '').trim()
  if (errorCode) return [errorCode]

  const failedStage = String(doc.failed_stage || '').trim()
  return failedStage ? [`${failedStage}_failed`] : []
}

export function extractTuningOverrides(doc: Document): DocumentPipelineOptions {
  const meta = doc.metadata
  const pipeline = getRecordField(meta, 'pipeline')
  const governance = getRecordField(pipeline ?? undefined, 'governance')
  if (!governance) return {}

  const out: DocumentPipelineOptions = {}

  if (typeof governance.drop_outline_only === 'boolean')
    out.governance_drop_outline_only = governance.drop_outline_only
  if (typeof governance.drop_outline_min_content_chars === 'number')
    out.governance_drop_outline_min_content_chars =
      governance.drop_outline_min_content_chars
  if (typeof governance.drop_outline_max_heading_ratio === 'number')
    out.governance_drop_outline_max_heading_ratio =
      governance.drop_outline_max_heading_ratio
  if (typeof governance.drop_low_density === 'boolean')
    out.governance_drop_low_density = governance.drop_low_density
  if (typeof governance.drop_low_density_threshold === 'number')
    out.governance_drop_low_density_threshold =
      governance.drop_low_density_threshold
  if (typeof governance.pii_max_hits === 'number')
    out.governance_pii_max_hits = governance.pii_max_hits
  if (typeof governance.secrets_max_hits === 'number')
    out.governance_secrets_max_hits = governance.secrets_max_hits
  if (typeof governance.quarantine_on_drop === 'boolean')
    out.governance_quarantine_on_drop = governance.quarantine_on_drop

  return out
}

export function reasonLabel(reason: string): string {
  switch (reason) {
    case 'outline_only':
      return '大纲文档'
    case 'low_density':
      return '低密度文本'
    case 'empty_document':
      return '空文档'
    case 'pii_exceeded':
      return 'PII 超阈值'
    case 'secrets_exceeded':
      return 'Secrets 超阈值'
    default:
      return reason
  }
}

export function buildReviewAdvice(doc: Document): string[] {
  const reasons = new Set(getDropReasons(doc))
  const advice: string[] = []

  if (reasons.has('outline_only'))
    advice.push(
      '如果正文有效但被判定为大纲文档，可关闭 outline_only 过滤后重试。'
    )
  if (reasons.has('low_density'))
    advice.push(
      '如果文本主要由表格或短句构成，可放宽 low_density 阈值后重新入库。'
    )
  if (reasons.has('pii_exceeded'))
    advice.push(
      '确认是否包含真实敏感信息；若仅为误报，建议先抽样预览再决定放行。'
    )
  if (reasons.has('secrets_exceeded'))
    advice.push('优先确认命中的内容是否为真实密钥或凭证，再执行放行。')
  if (!advice.length)
    advice.push('先查看命中规则与原文片段，再决定放行、重试或删除。')

  return advice
}

export function createReviewMetadataPatch(extra?: JsonRecord): JsonRecord {
  const patch: JsonRecord = {
    quarantine_reviewed: true,
    quarantine_reviewed_at: new Date().toISOString(),
  }

  if (extra) Object.assign(patch, extra)

  return patch
}

export function getBusyIconClassName(
  acting: ActingState,
  docId: string,
  action: QuarantineAction
): string {
  return cn(
    'h-4 w-4 mr-1',
    acting?.id === docId && acting.action === action
      ? 'animate-spin motion-reduce:animate-none'
      : ''
  )
}

export function downloadTextFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function getQuarantineSource(doc: Document): string {
  const failedStage = String(doc.failed_stage || '').toLowerCase()
  if (['parsing', 'parse', 'governance', 'chunking', 'embedding', 'vector_write', 'index'].includes(failedStage)) {
    return failedStage === 'embedding' || failedStage === 'vector_write' || failedStage === 'index'
      ? '索引入库'
      : '文档解析'
  }
  const kind = getDocumentKind(doc.filename)
  if (
    kind === 'pdf' ||
    kind === 'markdown' ||
    kind === 'html' ||
    String(doc.file_type || '').toLowerCase() === 'docx'
  ) {
    return '文档解析'
  }
  if (kind === 'spreadsheet') return '数据导入'
  if (
    String(doc.dataset_id || '')
      .toLowerCase()
      .includes('api')
  )
    return 'API 接入'
  return '其他'
}

export function getQuarantineSeverity(doc: Document): QuarantineSeverity {
  const reasons = new Set(getDropReasons(doc))
  const error = String(doc.error_message || '').toLowerCase()
  if (
    reasons.has('pii_exceeded') ||
    reasons.has('secrets_exceeded') ||
    error.includes('pii') ||
    error.includes('secret') ||
    error.includes('password')
  ) {
    return '高'
  }
  if (
    reasons.has('low_density') ||
    reasons.has('outline_only') ||
    doc.status === 'quarantined'
  ) {
    return '中'
  }
  return '低'
}

export function getSeverityClassName(severity: QuarantineSeverity): string {
  switch (severity) {
    case '高':
      return 'text-rose'
    case '中':
      return 'text-warning'
    case '低':
    default:
      return 'text-success'
  }
}

export function getSeverityBarClassName(severity: QuarantineSeverity): string {
  switch (severity) {
    case '高':
      return 'bg-rose/70'
    case '中':
      return 'bg-warning/70'
    case '低':
    default:
      return 'bg-success/70'
  }
}

export function buildConicGradient(values: number[], colors: string[]): string {
  const total = values.reduce((sum, value) => sum + value, 0)
  if (!total) return 'conic-gradient(rgba(148,163,184,0.18) 0deg 360deg)'

  let current = 0
  const stops = values.map((value, index) => {
    const start = current
    const end = current + (value / total) * 360
    current = end
    return `${colors[index]} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`
  })
  return `conic-gradient(${stops.join(', ')})`
}
