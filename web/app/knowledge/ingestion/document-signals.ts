import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckSamplesResponse,
  Document,
} from '@/types'

import type { SampleDisposition } from './types'

export function safeNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

export function stringifyForDisplay(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }
  if (typeof value === 'symbol') return value.description ?? ''

  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return ''
  }
}

export function firstDisplayValue(...values: unknown[]): string {
  for (const value of values) {
    const text = stringifyForDisplay(value).trim()
    if (text) return text
  }
  return ''
}

export function estimatePdfPageCountFromSignals({
  characters,
  fileSize,
}: {
  characters: number
  fileSize: number
}): number {
  const chars = Number(characters || 0)
  const size = Number(fileSize || 0)
  const pagesFromText = chars > 0 ? Math.ceil(chars / 900) : 0
  const pagesFromSize = size > 0 ? Math.ceil(size / (350 * 1024)) : 0
  const estimated = pagesFromText || pagesFromSize
  return Math.max(0, Math.min(2000, estimated))
}

export const MARKDOWN_IMAGE_REF_PATTERN = /!\[[^\]]*]\([^)]*\)/g
export const HTML_TABLE_PATTERN = /<table\b/gi

export function getRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : null
}

export function getDocumentMetadataRecord(
  document: Document
): Record<string, unknown> {
  return getRecord(document.metadata) ?? {}
}

export function isExecutionMonitorDocument(document: Document) {
  const meta = getDocumentMetadataRecord(document)
  return String(meta.ingest_stage || '').toLowerCase() !== 'uploaded_only'
}

export function firstPositiveNumber(...values: unknown[]): number {
  for (const value of values) {
    const numeric = safeNumber(value)
    if (numeric > 0) return numeric
  }
  return 0
}

export function getDocumentAnalyticsRecord(
  document: Document
): Record<string, unknown> | null {
  const meta = getDocumentMetadataRecord(document)
  const pipeline = getRecord(meta.pipeline)
  return (
    getRecord(pipeline?.analytics_raw) ??
    getRecord(meta.document_analytics_raw) ??
    getRecord(meta.analytics_raw)
  )
}

export function getDocumentPdfQualityRecord(
  document: Document
): Record<string, unknown> | null {
  const meta = getDocumentMetadataRecord(document)
  const qualityGate = getRecord(meta.quality_gate)
  return (
    getRecord(meta.pdf_quality) ??
    getRecord(qualityGate?.pdf_quality) ??
    getRecord(qualityGate?.stats)
  )
}

export function getDocumentElementTexts(document: Document): string[] {
  const elements = getDocumentMetadataRecord(document).elements
  if (!Array.isArray(elements)) return []

  return elements
    .map((element) => {
      const record = getRecord(element)
      const text = record?.text ?? record?.content ?? record?.markdown
      return typeof text === 'string' ? text : ''
    })
    .filter(Boolean)
}

export function countPatternInTexts(texts: string[], pattern: RegExp): number {
  return texts.reduce((sum, text) => {
    pattern.lastIndex = 0
    let count = 0
    let match: RegExpExecArray | null

    while ((match = pattern.exec(text)) !== null) {
      count += 1
      if (!pattern.global) break
      if (match[0] === '') pattern.lastIndex += 1
    }

    return sum + count
  }, 0)
}

export function countDocumentImageRefs(document: Document): number {
  const elements = getDocumentMetadataRecord(document).elements
  const elementKindCount = Array.isArray(elements)
    ? elements.filter((element) => {
        const record = getRecord(element)
        const kind = firstDisplayValue(
          record?.kind ??
            record?.type ??
            record?.category ??
            record?.visual_kind
        ).toLowerCase()
        return ['image', 'figure', 'picture'].includes(kind)
      }).length
    : 0

  return (
    elementKindCount +
    countPatternInTexts(getDocumentElementTexts(document), MARKDOWN_IMAGE_REF_PATTERN)
  )
}

export function countDocumentTableRefs(document: Document): number {
  const elements = getDocumentMetadataRecord(document).elements
  const elementKindCount = Array.isArray(elements)
    ? elements.filter((element) => {
        const record = getRecord(element)
        const kind = firstDisplayValue(
          record?.kind ?? record?.type ?? record?.category
        ).toLowerCase()
        return kind === 'table'
      }).length
    : 0

  return (
    elementKindCount +
    countPatternInTexts(getDocumentElementTexts(document), HTML_TABLE_PATTERN)
  )
}

export function getDocumentRuntimeStats(document: Document) {
  const meta = getDocumentMetadataRecord(document)
  const analytics = getDocumentAnalyticsRecord(document)
  const pdfQuality = getDocumentPdfQualityRecord(document)
  const stageDurations = getRecord(meta.ingest_stage_durations_ms)

  const pageCount = firstPositiveNumber(
    meta.page_count,
    analytics?.page_count,
    pdfQuality?.page_count
  )
  const imageCount =
    firstPositiveNumber(meta.image_count, analytics?.image_count) ||
    countDocumentImageRefs(document)
  const tableCount =
    firstPositiveNumber(meta.table_count, analytics?.table_count) ||
    countDocumentTableRefs(document)
  const blockCount = firstPositiveNumber(
    meta.block_count,
    analytics?.block_count,
    Array.isArray(meta.elements) ? meta.elements.length : 0
  )
  const parseDurationSec = firstPositiveNumber(
    meta.parse_duration_sec,
    stageDurations?.parse
      ? safeNumber(stageDurations.parse) / 1000
      : undefined
  )

  return {
    blockCount,
    imageCount,
    pageCount,
    pageCountSource: getPageCountSourceLabel(meta, pageCount),
    parseDurationSec,
    tableCount,
  }
}

export function getDocumentUserMeta(document: Document): Record<string, unknown> | null {
  const meta = document.metadata
  if (!meta || typeof meta !== 'object') return null
  const user = (meta as Record<string, unknown>).user
  return user && typeof user === 'object'
    ? (user as Record<string, unknown>)
    : null
}

export function getPersistedSampleDisposition(
  document: Document
): SampleDisposition | null {
  const disposition = getDocumentUserMeta(document)?.precheck_disposition
  return disposition === 'approved' || disposition === 'manual'
    ? disposition
    : null
}

export function getPersistedSalesAuditDisposition(
  file: DatasetPrecheckFileOut
): SampleDisposition | null {
  const disposition = file.review_disposition
  const reviewedAt =
    typeof file.reviewed_at === 'string' ? file.reviewed_at : null
  if (!reviewedAt) return null
  return disposition === 'approved' || disposition === 'manual'
    ? disposition
    : null
}

export function collectSalesAuditSampleFiles(
  samples: DatasetPrecheckSamplesResponse | null
): DatasetPrecheckFileOut[] {
  if (!samples) return []

  const representative = samples.representative ?? []
  const needsReview = Object.values(samples.needs_review ?? {}).flat()
  const topLargeFiles = samples.top_large_files ?? []
  const topLongText = samples.top_long_text ?? []
  const unique = new Map<string, DatasetPrecheckFileOut>()

  for (const file of [
    ...needsReview,
    ...topLargeFiles,
    ...topLongText,
    ...representative,
  ]) {
    unique.set(String(file.name), file)
  }

  return Array.from(unique.values())
}

export function formatClockLabel(value: number): string {
  const date = new Date(value)
  const hours = `${date.getHours()}`.padStart(2, '0')
  const minutes = `${date.getMinutes()}`.padStart(2, '0')
  return `${hours}:${minutes}`
}

export function formatMonthDayLabel(value: number): string {
  const date = new Date(value)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function formatClockSecondsLabel(value: number | string | Date): string {
  const date = new Date(value)
  const hours = `${date.getHours()}`.padStart(2, '0')
  const minutes = `${date.getMinutes()}`.padStart(2, '0')
  const seconds = `${date.getSeconds()}`.padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

export function formatDurationClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const hours = `${Math.floor(safe / 3600)}`.padStart(2, '0')
  const minutes = `${Math.floor((safe % 3600) / 60)}`.padStart(2, '0')
  const seconds = `${safe % 60}`.padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
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

export function getPageCountSourceLabel(
  meta: Record<string, unknown>,
  pageCount: number
): string {
  if (typeof meta.page_count_source === 'string') return meta.page_count_source
  if (pageCount) return 'metadata'
  return ''
}
