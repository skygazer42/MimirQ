import { getDocumentKind } from '@/components/ingestion/monitor-utils'
import type { Document, DocumentPipelineOptions } from '@/types'

import type {
  JsonRecord,
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
      return '仅包含大纲'
    case 'low_density':
      return '正文密度过低'
    case 'empty_document':
      return '空文档'
    case 'pii_exceeded':
      return '个人信息超阈值'
    case 'secrets_exceeded':
      return '疑似密钥超阈值'
    case 'parsing_failed':
      return '文档解析失败'
    case 'embedding_failed':
    case 'vector_write_failed':
    case 'index_failed':
      return '索引写入失败'
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
    advice.push('核对原文与入库详情后，可重试或调整文档参数。')

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
