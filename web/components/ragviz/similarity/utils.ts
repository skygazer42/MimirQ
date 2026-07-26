import type { RagvizSimilarityMatrixResult } from '@/types'

export type JsonRecord = Record<string, unknown>

export function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function similarityDisplayString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }
  return ''
}

export function firstSimilarityDisplayString(...values: unknown[]): string {
  for (const value of values) {
    const text = similarityDisplayString(value)
    if (text) return text
  }
  return ''
}

export function isSimilarityMatrixResult(
  value: unknown
): value is RagvizSimilarityMatrixResult {
  return (
    isRecord(value) &&
    Array.isArray(value.matrix) &&
    Array.isArray(value.x_data) &&
    Array.isArray(value.y_data) &&
    Array.isArray(value.x_available_fields) &&
    Array.isArray(value.y_available_fields) &&
    isRecord(value.metadata)
  )
}

export function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  if (error instanceof Error && error.message.trim())
    return error.message.trim()
  const text = similarityDisplayString(error)
  return text || fallback
}

export function importedPayloadEntries(raw: unknown): unknown[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (isRecord(raw) && Array.isArray(raw.entries)) return raw.entries
  return [raw]
}

export function collectionLabel(
  explicitLabel: unknown,
  collectionId: string,
  fallback: string
) {
  return firstSimilarityDisplayString(explicitLabel, collectionId, fallback)
}

export function metricToneClass(tone?: string) {
  return tone === 'danger' ? 'text-destructive' : 'text-foreground'
}

export function emptyMatrixSwatchClass(index: number) {
  if (index % 4 === 0) return 'bg-primary'
  if (index % 3 === 0) return 'bg-primary'
  return 'bg-primary/15'
}

export function emptyMatrixCellClass(index: number) {
  if (index % 9 === 0) return 'bg-primary'
  if (index % 5 === 0) return 'bg-primary/30'
  return 'bg-primary/15'
}

export function diagnosticCandidateStatusClass(
  isDisabled: boolean,
  isMarked: boolean
) {
  if (isDisabled) return 'border-border bg-muted text-muted-foreground'
  if (isMarked) {
    return 'border-warning/30 bg-warning/10 text-warning'
  }
  return 'border-warning/30 bg-warning/10 text-warning'
}

export function diagnosticCandidateStatusLabel(
  isDisabled: boolean,
  isMarked: boolean
) {
  if (isDisabled) return '已禁用'
  if (isMarked) return '待审'
  return '待处理'
}

function uniqueLabelRaw(item: Record<string, unknown>, field: string) {
  if (!field) return ''
  return similarityDisplayString(item[field])
}

function compactAxisLabel(value: string, maxLength = 42) {
  const text = value.trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(1, maxLength - 3))}...`
}

function oneBasedItemNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(1, Math.trunc(value) + 1)
    : null
}

export function axisLabelForItem(item: Record<string, unknown>, field: string) {
  const fieldText = uniqueLabelRaw(item, field)
  const documentText = firstSimilarityDisplayString(item.document, item.name)
  const chunkNumber = oneBasedItemNumber(item.chunk_index)
  if (chunkNumber !== null) {
    const base = documentText || fieldText || `chunk ${chunkNumber}`
    return `${compactAxisLabel(base, 34)} · chunk ${chunkNumber}`
  }

  const questionNumber = oneBasedItemNumber(item.order_id)
  if (questionNumber !== null && fieldText) {
    return `Q${questionNumber} · ${compactAxisLabel(fieldText, 44)}`
  }

  return compactAxisLabel(fieldText)
}

export function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}
