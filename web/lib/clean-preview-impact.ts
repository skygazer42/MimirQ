import type { CleanPreviewResponse } from '@/types'

export type CleanPreviewImpact = {
  inputChars: number
  outputChars: number
  deltaChars: number
  deltaCharsPct: number | null
  inputLines: number
  outputLines: number
  deltaLines: number
  addedLines: number
  removedLines: number
  changedLines: number
  urlsChanged: number
  paragraphsDropped: number
  referencesRemovedLines: number
  piiHitsTotal: number
  secretsHitsTotal: number
}

function asInt(value: unknown) {
  const n = Number(value)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

function sumCounts(value: unknown) {
  if (!value || typeof value !== 'object') return 0
  let total = 0
  for (const v of Object.values(value as Record<string, unknown>)) {
    const n = Number(v)
    if (!Number.isFinite(n)) continue
    if (n > 0) total += Math.trunc(n)
  }
  return total
}

export function computeCleanPreviewImpact(preview: CleanPreviewResponse | null | undefined): CleanPreviewImpact | null {
  if (!preview) return null

  const inputChars = asInt((preview as any).input_chars)
  const outputChars = asInt((preview as any).output_chars)
  const deltaChars = outputChars - inputChars
  const deltaCharsPct = inputChars > 0 ? deltaChars / inputChars : null

  const inputLines = asInt((preview as any).input_lines)
  const outputLines = asInt((preview as any).output_lines)
  const deltaLines = outputLines - inputLines

  const piiHitsTotal = sumCounts((preview as any).pii_hits)
  const secretsHitsTotal = sumCounts((preview as any).secrets_hits)

  return {
    inputChars,
    outputChars,
    deltaChars,
    deltaCharsPct,
    inputLines,
    outputLines,
    deltaLines,
    addedLines: asInt((preview as any).added_lines),
    removedLines: asInt((preview as any).removed_lines),
    changedLines: asInt((preview as any).changed_lines),
    urlsChanged: asInt((preview as any).urls_changed),
    paragraphsDropped: asInt((preview as any).paragraphs_dropped),
    referencesRemovedLines: asInt((preview as any).references_removed_lines),
    piiHitsTotal,
    secretsHitsTotal,
  }
}
