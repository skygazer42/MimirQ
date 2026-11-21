import type { DatasetPrecheckFileOut, DatasetPrecheckSamplesResponse, Document } from '@/types'
import { recordSchema } from '@/lib/response-schema'

import type { SampleDisposition } from './types'

export function safeNumber(value: unknown): number {
  if (typeof value !== 'number' && typeof value !== 'string') return 0
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

export function stringifyForDisplay(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value)
  }
  if (typeof value === 'symbol') return value.description ?? ''

  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return ''
  }
}

export function estimatePdfPageCountFromSignals({
  characters,
  fileSize,
}: {
  characters: number
  fileSize: number
}): number {
  const estimated = characters > 0 ? Math.ceil(characters / 900) : Math.ceil(fileSize / (350 * 1024))
  return Math.max(0, Math.min(2000, estimated))
}

const MARKDOWN_IMAGE_REF_PATTERN = /!\[[^\]]*]\([^)]*\)/g
const HTML_TABLE_PATTERN = /<table\b/gi

function getRecord(value: unknown): Record<string, unknown> | null {
  const result = recordSchema.safeParse(value)
  return result.success ? result.data : null
}

function getDocumentMetadataRecord(document: Document): Record<string, unknown> {
  return getRecord(document.metadata) ?? {}
}

export function isExecutionMonitorDocument(document: Document) {
  const stage = document.metadata?.ingest_stage
  return typeof stage !== 'string' || stage.toLowerCase() !== 'uploaded_only'
}

function firstPositiveNumber(...values: unknown[]): number {
  for (const value of values) {
    const numeric = safeNumber(value)
    if (numeric > 0) return numeric
  }
  return 0
}

function getDocumentAnalyticsRecord(document: Document): Record<string, unknown> | null {
  const meta = getDocumentMetadataRecord(document)
  const pipeline = getRecord(meta.pipeline)
  return getRecord(pipeline?.analytics_raw) ?? getRecord(meta.document_analytics_raw) ?? getRecord(meta.analytics_raw)
}

function getDocumentPdfQualityRecord(document: Document): Record<string, unknown> | null {
  const meta = getDocumentMetadataRecord(document)
  const qualityGate = getRecord(meta.quality_gate)
  return getRecord(meta.pdf_quality) ?? getRecord(qualityGate?.pdf_quality) ?? getRecord(qualityGate?.stats)
}

function getDocumentElementTexts(document: Document): string[] {
  const elements = getDocumentMetadataRecord(document).elements
  if (!Array.isArray(elements)) return []

  return elements.flatMap((element) => {
    const record = getRecord(element)
    const text = record?.text ?? record?.content ?? record?.markdown
    return typeof text === 'string' && text.length > 0 ? [text] : []
  })
}

function countPatternInTexts(texts: string[], pattern: RegExp): number {
  return texts.reduce((sum, text) => sum + (text.match(pattern)?.length ?? 0), 0)
}

function countDocumentImageRefs(document: Document): number {
  const elements = getDocumentMetadataRecord(document).elements
  const elementKindCount = Array.isArray(elements)
    ? elements.filter((element) => {
        const record = getRecord(element)
        const kind = stringifyForDisplay(record?.kind ?? record?.type ?? record?.category ?? record?.visual_kind)
          .trim()
          .toLowerCase()
        return ['image', 'figure', 'picture'].includes(kind)
      }).length
    : 0

  return elementKindCount + countPatternInTexts(getDocumentElementTexts(document), MARKDOWN_IMAGE_REF_PATTERN)
}

function countDocumentTableRefs(document: Document): number {
  const elements = getDocumentMetadataRecord(document).elements
  const elementKindCount = Array.isArray(elements)
    ? elements.filter((element) => {
        const record = getRecord(element)
        const kind = stringifyForDisplay(record?.kind ?? record?.type ?? record?.category)
          .trim()
          .toLowerCase()
        return kind === 'table'
      }).length
    : 0

  return elementKindCount + countPatternInTexts(getDocumentElementTexts(document), HTML_TABLE_PATTERN)
}

export function getDocumentRuntimeStats(document: Document) {
  const meta = getDocumentMetadataRecord(document)
  const analytics = getDocumentAnalyticsRecord(document)
  const pdfQuality = getDocumentPdfQualityRecord(document)

  const pageCount = firstPositiveNumber(meta.page_count, analytics?.page_count, pdfQuality?.page_count)
  const imageCount = firstPositiveNumber(meta.image_count, analytics?.image_count) || countDocumentImageRefs(document)
  const tableCount = firstPositiveNumber(meta.table_count, analytics?.table_count) || countDocumentTableRefs(document)
  const blockCount = firstPositiveNumber(
    meta.block_count,
    analytics?.block_count,
    Array.isArray(meta.elements) ? meta.elements.length : 0,
  )

  return {
    blockCount,
    imageCount,
    pageCount,
    tableCount,
  }
}

export function getPersistedSampleDisposition(document: Document): SampleDisposition | null {
  const disposition = getRecord(document.metadata?.user)?.precheck_disposition
  return disposition === 'approved' || disposition === 'manual' ? disposition : null
}

export function getPersistedSalesAuditDisposition(file: DatasetPrecheckFileOut): SampleDisposition | null {
  const disposition = file.review_disposition
  const reviewedAt = typeof file.reviewed_at === 'string' ? file.reviewed_at : null
  if (!reviewedAt) return null
  return disposition === 'approved' || disposition === 'manual' ? disposition : null
}

export function collectSalesAuditSampleFiles(samples: DatasetPrecheckSamplesResponse | null): DatasetPrecheckFileOut[] {
  if (samples === null) return []

  const { representative, top_large_files: topLargeFiles, top_long_text: topLongText } = samples
  const needsReview = Object.values(samples.needs_review).flat()
  const unique = new Map<string, DatasetPrecheckFileOut>()

  for (const file of [...needsReview, ...topLargeFiles, ...topLongText, ...representative]) {
    unique.set(file.name, file)
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
  if (Number.isNaN(date.getTime())) return '—'
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
