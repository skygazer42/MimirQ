import type { RagvizSimilarityMatrixResult } from '@/types'
import { readNonEmptyString } from '@/lib/primitive-text'

type JsonRecord = Record<string, unknown>

export function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function similarityDisplayString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
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

export function isSimilarityMatrixResult(value: unknown): value is RagvizSimilarityMatrixResult {
  if (!isRecord(value) || !isRecord(value.metadata)) return false
  if (value.stats != null && (!isRecord(value.stats) || !Object.values(value.stats).every(Number.isFinite)))
    return false

  const { matrix, x_data, y_data } = value
  if (!Array.isArray(x_data) || x_data.length === 0 || !x_data.every(isRecord)) return false
  if (!Array.isArray(y_data) || y_data.length === 0 || !y_data.every(isRecord)) return false
  return (
    Array.isArray(matrix) &&
    matrix.length === y_data.length &&
    matrix.every((row) => Array.isArray(row) && row.length === x_data.length && row.every(Number.isFinite)) &&
    Array.isArray(value.x_available_fields) &&
    value.x_available_fields.every((field) => typeof field === 'string') &&
    Array.isArray(value.y_available_fields) &&
    value.y_available_fields.every((field) => typeof field === 'string')
  )
}

export function readSimilarityItemId(item: JsonRecord): string | undefined {
  const id = item.id
  return (
    readNonEmptyString(item.case_id) ??
    (typeof id === 'number' && Number.isFinite(id) ? String(id) : readNonEmptyString(id))
  )
}

export function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim()
  const text = similarityDisplayString(error)
  return text || fallback
}

export function importedPayloadEntries(raw: unknown): unknown[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (isRecord(raw) && Array.isArray(raw.entries)) return raw.entries
  return [raw]
}

export function collectionLabel(explicitLabel: unknown, collectionId: string, fallback: string) {
  return firstSimilarityDisplayString(explicitLabel, collectionId, fallback)
}

export function diagnosticCandidateStatusClass(isDisabled: boolean) {
  if (isDisabled) return 'border-border bg-muted text-muted-foreground'
  return 'border-warning/30 bg-warning/10 text-warning'
}

export function diagnosticCandidateStatusLabel(isDisabled: boolean, isMarked: boolean) {
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
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(1, Math.trunc(value) + 1) : null
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
